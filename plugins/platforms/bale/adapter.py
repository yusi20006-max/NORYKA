"""Bale Messenger (پیام‌رسان بله) full production platform adapter for Noryka Gateway.

Implements BasePlatformAdapter over Bale's Bot API (https://tapi.bale.ai/bot<token>/<method>):
- First-class Platform.BALE enum identity (no collision with Telegram sessions/allowlists)
- Fail-Closed authorization check (BALE_ALLOWED_USERS / BALE_ALLOW_ALL_USERS)
- Exponential backoff on polling errors and explicit HTTP 429 retry_after handling
- Inbound & outbound media support (photo, document, voice, audio, video, sticker) via media_cache
- Interactive inline keyboard buttons for exec approvals (callback_query -> resolve_gateway_approval)
- Stream edit throttling (default 2.0s) tailored to Bale Bot API rate limits
"""

from __future__ import annotations

import asyncio
import contextlib
import html as _html
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from agent.retry_utils import jittered_backoff
from gateway.config import Platform, PlatformConfig
from gateway.platforms._shared import (
    apply_yaml_bridge,
    env_is_connected,
    extra_or_secret,
    get_scoped_secret,
    platform_gate_env,
    seed_extra_from_env,
)
from gateway.platforms.base import (
    BasePlatformAdapter,
    ExecApprovalPrompt,
    MessageEvent,
    MessageType,
    SendResult,
)
from gateway.platforms.media_cache import cache_media_bytes, mime_for_ext

logger = logging.getLogger(__name__)

BALE_DEFAULT_API_BASE = "https://tapi.bale.ai/bot"
BALE_DEFAULT_FILE_BASE = "https://tapi.bale.ai/file/bot"
BALE_STREAM_EDIT_THROTTLE_SECONDS = 2.0
BALE_MAX_MESSAGE_LEN = 4096

_BALE_ENV_TABLE = (
    ("BALE_BOT_TOKEN", "token", str),
    ("BALE_ALLOWED_USERS", "allowed_users", str),
    ("BALE_ALLOW_ALL_USERS", "allow_all_users", bool),
    ("BALE_HOME_CHANNEL", "home_channel", str),
    ("BALE_API_BASE_URL", "api_base_url", str),
    ("BALE_STREAM_THROTTLE", "stream_edit_throttle_seconds", float),
)

_BALE_YAML_TABLE = (
    ("token", "BALE_BOT_TOKEN", "secret"),
    ("allowed_users", "BALE_ALLOWED_USERS", "csv"),
    ("allow_all_users", "BALE_ALLOW_ALL_USERS", "bool"),
    ("home_channel", "BALE_HOME_CHANNEL", "str"),
    ("api_base_url", "BALE_API_BASE_URL", "str"),
    ("stream_edit_throttle_seconds", "BALE_STREAM_THROTTLE", "float"),
)


def check_requirements() -> bool:
    """httpx is a core dependency; always available."""
    return True


def is_connected(config: Optional[PlatformConfig] = None) -> bool:
    return env_is_connected("BALE_BOT_TOKEN", config, extra_key="token")


class BaleAdapter(BasePlatformAdapter):
    """Full-featured Noryka Gateway adapter for Bale Messenger (tapi.bale.ai)."""

    def __init__(self, config: PlatformConfig):
        super().__init__(config, Platform.BALE)
        extra = getattr(config, "extra", None) if isinstance(getattr(config, "extra", None), dict) else {}
        self.token: str = getattr(config, "token", None) or extra_or_secret(extra, "token", "BALE_BOT_TOKEN") or ""
        self.api_base: str = (
            extra_or_secret(extra, "api_base_url", "BALE_API_BASE_URL") or BALE_DEFAULT_API_BASE
        ).rstrip("/")
        self.file_base: str = BALE_DEFAULT_FILE_BASE.rstrip("/")
        raw_throttle = extra_or_secret(extra, "stream_edit_throttle_seconds", "BALE_STREAM_THROTTLE")
        try:
            self.edit_throttle_s: float = max(0.5, float(raw_throttle)) if raw_throttle is not None else BALE_STREAM_EDIT_THROTTLE_SECONDS
        except (TypeError, ValueError):
            self.edit_throttle_s = BALE_STREAM_EDIT_THROTTLE_SECONDS

        self._client: Optional[httpx.AsyncClient] = None
        self._polling_task: Optional[asyncio.Task] = None
        self._last_update_id: int = 0
        self._last_edit_ts: Dict[str, float] = {}
        self._consecutive_poll_failures: int = 0
        self._bot_id: Optional[str] = None
        self._bot_username: Optional[str] = None

    def _endpoint(self, method: str) -> str:
        return f"{self.api_base}{self.token}/{method}"

    def _file_url(self, file_path: str) -> str:
        return f"{self.file_base}{self.token}/{file_path.lstrip('/')}"

    def _is_user_authorized(self, user_id: Optional[str], chat_id: Optional[str] = None) -> bool:
        """Fail-closed allowlist check for Bale callers (BALE_ALLOWED_USERS / BALE_ALLOW_ALL_USERS)."""
        allow_all_raw = platform_gate_env("BALE_ALLOW_ALL_USERS") or str(
            (self.config.extra or {}).get("allow_all_users", "")
        )
        if str(allow_all_raw).strip().lower() in {"1", "true", "yes", "on"}:
            return True
        raw_list = (
            platform_gate_env("BALE_ALLOWED_USERS")
            or str((self.config.extra or {}).get("allowed_users", ""))
            or get_scoped_secret("BALE_ALLOWED_USERS")
            or ""
        )
        allowed = {u.strip() for u in str(raw_list).split(",") if u.strip()}
        if not allowed:
            # Fail-closed when no allowlist is configured
            return False
        if "*" in allowed:
            return True
        uid = str(user_id or "").strip()
        cid = str(chat_id or "").strip()
        return bool((uid and uid in allowed) or (cid and cid in allowed))

    async def _api_request(
        self,
        method: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """Execute a Bale Bot API call with automatic HTTP 429 retry_after and transient backoff."""
        if self._client is None:
            return {"ok": False, "error_code": 503, "description": "Bale HTTP client not initialized"}

        attempt = 0
        while True:
            attempt += 1
            try:
                if files is not None:
                    resp = await self._client.post(self._endpoint(method), data=data or {}, files=files)
                elif json_body is not None:
                    resp = await self._client.post(self._endpoint(method), json=json_body)
                else:
                    resp = await self._client.get(self._endpoint(method))

                try:
                    payload = resp.json()
                except Exception:
                    payload = {"ok": False, "error_code": resp.status_code, "description": _redact_bale_secret(resp.text[:300], self.token)}

                if resp.status_code == 429 or payload.get("error_code") == 429:
                    params = payload.get("parameters") or {}
                    retry_after = float(params.get("retry_after") or resp.headers.get("Retry-After") or 3.0)
                    payload["retry_after"] = retry_after
                    if attempt <= max_retries and retry_after <= 30.0:
                        logger.warning("Bale API 429 on %s; sleeping %.1fs (attempt %d/%d)", method, retry_after, attempt, max_retries)
                        await asyncio.sleep(retry_after)
                        continue
                    return _redact_bale_payload(payload, self.token)

                if resp.status_code >= 500 and attempt <= max_retries:
                    delay = jittered_backoff(attempt, base=1.0, cap=15.0)
                    await asyncio.sleep(delay)
                    continue

                return _redact_bale_payload(payload, self.token)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if attempt <= max_retries:
                    delay = jittered_backoff(attempt, base=1.0, cap=15.0)
                    await asyncio.sleep(delay)
                    continue
                return {"ok": False, "error_code": 500, "description": _redact_bale_secret(exc, self.token), "retryable": True}

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        if not self.token:
            logger.warning("BaleAdapter: BALE_BOT_TOKEN is not configured.")
            return False
        self._client = httpx.AsyncClient(timeout=35.0)
        data = await self._api_request("getMe", max_retries=2)
        if not data.get("ok"):
            logger.error("BaleAdapter getMe failed: %s", _redact_bale_secret(data.get("description") or data, self.token))
            await self._client.aclose()
            self._client = None
            return False
        bot_info = data.get("result") or {}
        self._bot_id = str(bot_info.get("id") or "")
        self._bot_username = str(bot_info.get("username") or "")
        logger.info("Connected to Bale Messenger as @%s (id=%s)", self._bot_username, self._bot_id)
        self._running = True
        self._polling_task = asyncio.create_task(self._poll_updates_loop())
        return True

    async def disconnect(self) -> None:
        self._running = False
        if self._polling_task:
            self._polling_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._polling_task
            self._polling_task = None
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _poll_updates_loop(self) -> None:
        """Long-polling loop with exponential backoff on non-OK responses and 429 rate-limit handling."""
        while getattr(self, "_running", False) and self._client is not None:
            try:
                payload = await self._api_request(
                    "getUpdates",
                    json_body={"offset": self._last_update_id + 1, "timeout": 20},
                    max_retries=1,
                )
                if not payload.get("ok"):
                    self._consecutive_poll_failures += 1
                    retry_after = float(payload.get("retry_after") or 0.0)
                    delay = max(retry_after, jittered_backoff(self._consecutive_poll_failures, base=1.5, cap=30.0))
                    logger.warning(
                        "Bale getUpdates returned ok=False (err=%s); backing off %.1fs",
                        payload.get("description") or payload.get("error_code"),
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                self._consecutive_poll_failures = 0
                updates = payload.get("result") or []
                for upd in updates:
                    uid = int(upd.get("update_id", 0))
                    if uid > self._last_update_id:
                        self._last_update_id = uid
                    await self._dispatch_update(upd, uid)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._consecutive_poll_failures += 1
                delay = jittered_backoff(self._consecutive_poll_failures, base=1.5, cap=30.0)
                logger.debug("Bale polling error (%s); sleeping %.1fs", exc, delay)
                await asyncio.sleep(delay)

    async def _dispatch_update(self, upd: Dict[str, Any], update_id: int) -> None:
        if "callback_query" in upd and upd["callback_query"]:
            await self._handle_callback_query(upd["callback_query"])
            return
        msg = upd.get("message") or upd.get("edited_message")
        if msg:
            await self._handle_message_update(msg, update_id)

    async def _download_bale_media(self, file_id: str, mime: str, filename_hint: str = "", kind_hint: Optional[str] = None) -> Optional[str]:
        """Fetch file metadata via getFile, download bytes from Bale file server, and store in media_cache."""
        if not self._client or not file_id:
            return None
        info = await self._api_request("getFile", json_body={"file_id": file_id}, max_retries=2)
        if not info.get("ok"):
            return None
        file_path = (info.get("result") or {}).get("file_path")
        if not file_path:
            return None
        try:
            async with self._client.stream("GET", self._file_url(file_path)) as resp:
                resp.raise_for_status()
                content = await _read_bale_media_stream(resp)
            if not content:
                return None
            return cache_media_bytes(content, mime, filename_hint=filename_hint, kind_hint=kind_hint)
        except (httpx.HTTPError, ValueError, OSError) as exc:
            logger.warning("Bale media download failed (details redacted): %s", _redact_bale_secret(exc, self.token))
            return None

    async def _extract_media(self, msg: Dict[str, Any]) -> Tuple[MessageType, List[str], List[str]]:
        """Extract photos, documents, voice, audio, video, or stickers from a Bale message."""
        media_urls: List[str] = []
        media_types: List[str] = []
        msg_type = MessageType.TEXT

        if isinstance(msg.get("photo"), list) and msg["photo"]:
            msg_type = MessageType.PHOTO
            largest = msg["photo"][-1]
            fid = largest.get("file_id", "")
            cached = await self._download_bale_media(fid, "image/jpeg", kind_hint="image")
            if cached:
                media_urls.append(cached)
                media_types.append("image/jpeg")
        elif isinstance(msg.get("document"), dict):
            msg_type = MessageType.DOCUMENT
            doc = msg["document"]
            fid = doc.get("file_id", "")
            fname = doc.get("file_name") or "document.bin"
            mime = doc.get("mime_type") or mime_for_ext(Path(fname).suffix)
            cached = await self._download_bale_media(fid, mime, filename_hint=fname, kind_hint="document")
            if cached:
                media_urls.append(cached)
                media_types.append(mime)
        elif isinstance(msg.get("voice"), dict):
            msg_type = MessageType.VOICE
            voice = msg["voice"]
            fid = voice.get("file_id", "")
            mime = voice.get("mime_type") or "audio/ogg"
            cached = await self._download_bale_media(fid, mime, kind_hint="audio")
            if cached:
                media_urls.append(cached)
                media_types.append(mime)
        elif isinstance(msg.get("audio"), dict):
            msg_type = MessageType.AUDIO
            aud = msg["audio"]
            fid = aud.get("file_id", "")
            fname = aud.get("file_name") or "audio.mp3"
            mime = aud.get("mime_type") or "audio/mpeg"
            cached = await self._download_bale_media(fid, mime, filename_hint=fname, kind_hint="audio")
            if cached:
                media_urls.append(cached)
                media_types.append(mime)
        elif isinstance(msg.get("video"), dict):
            msg_type = MessageType.VIDEO
            vid = msg["video"]
            fid = vid.get("file_id", "")
            fname = vid.get("file_name") or "video.mp4"
            mime = vid.get("mime_type") or "video/mp4"
            cached = await self._download_bale_media(fid, mime, filename_hint=fname, kind_hint="document")
            if cached:
                media_urls.append(cached)
                media_types.append(mime)

        return msg_type, media_urls, media_types

    async def _handle_message_update(self, msg: Dict[str, Any], update_id: int) -> None:
        chat = msg.get("chat") or {}
        sender = msg.get("from") or {}
        chat_id = str(chat.get("id") or "")
        user_id = str(sender.get("id") or chat_id)
        if not chat_id:
            return

        raw_chat_type = str(chat.get("type") or "private").lower()
        is_group = raw_chat_type in ("group", "supergroup", "channel")

        # Fail-closed authorization gate before media download or turn creation
        if not self._is_user_authorized(user_id, chat_id, is_group=is_group):
            logger.warning("BaleAdapter: unauthorized message from user_id=%s in chat_id=%s dropped.", user_id, chat_id)
            return

        text = (msg.get("text") or msg.get("caption") or "").strip()
        msg_type, media_urls, media_types = await self._extract_media(msg)
        if not text and not media_urls:
            return
        if text.startswith("/"):
            msg_type = MessageType.COMMAND

        chat_type = "dm" if raw_chat_type == "private" else ("channel" if raw_chat_type == "channel" else "group")
        user_name = (
            sender.get("username")
            or " ".join(filter(None, [sender.get("first_name"), sender.get("last_name")]))
            or user_id
        )
        chat_name = chat.get("title") or user_name
        message_id = str(msg.get("message_id") or "")

        reply_msg = msg.get("reply_to_message") or {}
        reply_to_id = str(reply_msg["message_id"]) if reply_msg.get("message_id") else None
        reply_to_text = reply_msg.get("text") or reply_msg.get("caption")

        source = self.build_source(
            chat_id=chat_id,
            chat_name=chat_name,
            chat_type=chat_type,
            user_id=user_id,
            user_name=user_name,
            message_id=message_id,
            is_bot=bool(sender.get("is_bot", False)),
        )

        event = MessageEvent(
            text=text,
            message_type=msg_type,
            user_id=user_id,
            user_name=user_name,
            source=source,
            raw_message=msg,
            message_id=message_id,
            platform_update_id=update_id,
            media_urls=media_urls,
            media_types=media_types,
            reply_to_message_id=reply_to_id,
            reply_to_text=reply_to_text,
        )
        await self.handle_message(event)

    async def _handle_callback_query(self, cb: Dict[str, Any]) -> None:
        """Handle inline button presses for exec approvals (ea:<request_id>:<session_key>:<choice>)."""
        cb_id = str(cb.get("id") or "")
        sender = cb.get("from") or {}
        msg = cb.get("message") or {}
        chat = msg.get("chat") or {}
        user_id = str(sender.get("id") or "")
        chat_id = str(chat.get("id") or "")
        data = str(cb.get("data") or "")

        if not self._is_user_authorized(user_id, chat_id):
            if cb_id:
                await self._api_request(
                    "answerCallbackQuery",
                    json_body={"callback_query_id": cb_id, "text": "Unauthorized caller.", "show_alert": True},
                )
            return

        if data.startswith("ea:"):
            parts = data.split(":", 3)
            if len(parts) == 4:
                _, req_id, session_key, choice = parts
                from tools.approval import resolve_gateway_approval
                resolved = resolve_gateway_approval(
                    session_key=session_key,
                    choice=choice,
                    request_id=req_id or None,
                )
                status_label = f"Approval decision recorded: {choice}" if resolved else "Approval already settled or expired."
                if cb_id:
                    await self._api_request(
                        "answerCallbackQuery",
                        json_body={"callback_query_id": cb_id, "text": status_label},
                    )
                if chat_id and msg.get("message_id"):
                    orig_text = msg.get("text") or ""
                    await self.edit_message(
                        chat_id,
                        str(msg["message_id"]),
                        f"{orig_text}\n\n✅ Decision: {choice.upper()} (by {user_id})",
                        force_final=True,
                    )

    async def _send_exec_approval_prompt(self, prompt: ExecApprovalPrompt) -> SendResult:
        """Send an interactive inline-keyboard approval card on Bale."""
        buttons_row = []
        req_id = prompt.request_id or ""
        for label, choice, _style in prompt.actions:
            cb_data = self.build_approval_callback_data(req_id, prompt.session_key, choice)
            buttons_row.append({"text": label, "callback_data": cb_data})
        reply_markup = {"inline_keyboard": [buttons_row]}
        return await self.send(prompt.chat_id, prompt.text, metadata={"reply_markup": reply_markup})

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> SendResult:
        if not self._client:
            return SendResult(success=False, error="Bale client not connected", retryable=True, error_kind="transient")

        text = str(content or "")
        if not text.strip():
            return SendResult(success=True, message_id="")

        chunks = [text[i : i + BALE_MAX_MESSAGE_LEN] for i in range(0, len(text), BALE_MAX_MESSAGE_LEN)] or [text]
        sent_ids: List[str] = []
        reply_id = reply_to or kwargs.get("reply_to_message_id")
        reply_markup = (metadata or {}).get("reply_markup") or kwargs.get("reply_markup")

        for idx, chunk in enumerate(chunks):
            body: Dict[str, Any] = {"chat_id": chat_id, "text": chunk}
            if idx == 0 and reply_id:
                with contextlib.suppress(ValueError):
                    body["reply_to_message_id"] = int(reply_id)
            if idx == len(chunks) - 1 and reply_markup:
                body["reply_markup"] = reply_markup

            data = await self._api_request("sendMessage", json_body=body)
            if not data.get("ok"):
                err_code = data.get("error_code")
                retry_after = data.get("retry_after")
                kind = "rate_limited" if err_code == 429 else ("forbidden" if err_code == 403 else "unknown")
                return SendResult(
                    success=False,
                    error=str(data.get("description") or data),
                    raw_response=data,
                    retryable=bool(err_code == 429 or data.get("retryable")),
                    retry_after=retry_after,
                    error_kind=kind,
                )
            mid = str((data.get("result") or {}).get("message_id") or "")
            if mid:
                sent_ids.append(mid)

        return SendResult(
            success=True,
            message_id=sent_ids[-1] if sent_ids else "",
            continuation_message_ids=tuple(sent_ids[:-1]),
        )

    async def edit_message(self, chat_id: str, message_id: str, content: str, **kwargs: Any) -> SendResult:
        if not self._client:
            return SendResult(success=False, error="Bale client not connected", retryable=True)
        key = f"{chat_id}:{message_id}"
        now = time.monotonic()
        last = self._last_edit_ts.get(key, 0.0)
        if not kwargs.get("force_final") and (now - last) < self.edit_throttle_s:
            return SendResult(success=True, message_id=str(message_id))
        self._last_edit_ts[key] = now
        try:
            mid_int = int(message_id)
        except ValueError:
            return SendResult(success=False, error=f"Invalid message_id: {message_id}")

        data = await self._api_request(
            "editMessageText",
            json_body={"chat_id": chat_id, "message_id": mid_int, "text": str(content or "")[:BALE_MAX_MESSAGE_LEN]},
        )
        if data.get("ok"):
            return SendResult(success=True, message_id=str(message_id), raw_response=data)
        return SendResult(
            success=False,
            error=str(data.get("description") or data),
            retry_after=data.get("retry_after"),
            retryable=bool(data.get("error_code") == 429),
        )


    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        """Get information about a Bale chat/channel (name and type: dm | group | channel)."""
        if not self._client:
            return {"id": str(chat_id), "name": str(chat_id), "type": "dm"}
        data = await self._api_request("getChat", json_body={"chat_id": chat_id}, max_retries=1)
        if data.get("ok") and isinstance(data.get("result"), dict):
            res = data["result"]
            raw_type = str(res.get("type") or "private").lower()
            chat_type = "dm" if raw_type == "private" else ("channel" if raw_type == "channel" else "group")
            name = (
                res.get("title")
                or res.get("username")
                or " ".join(filter(None, [res.get("first_name"), res.get("last_name")]))
                or str(chat_id)
            )
            return {"id": str(res.get("id") or chat_id), "name": name, "type": chat_type, "chat_type": chat_type}
        return {"id": str(chat_id), "name": str(chat_id), "type": "dm"}

    async def send_typing(self, chat_id: str, metadata: Any = None) -> None:
        if self._client:
            await self._api_request("sendChatAction", json_body={"chat_id": chat_id, "action": "typing"}, max_retries=0)

    async def _send_media_file(
        self,
        method: str,
        field_name: str,
        chat_id: str,
        file_path: str,
        caption: Optional[str] = None,
    ) -> SendResult:
        p = Path(file_path)
        if not p.is_file():
            return SendResult(success=False, error=f"File not found: {file_path}")
        data_fields: Dict[str, Any] = {"chat_id": str(chat_id)}
        if caption:
            data_fields["caption"] = caption[:1024]
        mime = mime_for_ext(p.suffix)
        with p.open("rb") as fh:
            files = {field_name: (p.name, fh.read(), mime)}
        res = await self._api_request(method, data=data_fields, files=files)
        if res.get("ok"):
            mid = str((res.get("result") or {}).get("message_id") or "")
            return SendResult(success=True, message_id=mid, raw_response=res)
        return SendResult(success=False, error=str(res.get("description") or res), retry_after=res.get("retry_after"))

    async def send_image_file(self, chat_id: str, image_path: str, caption: Optional[str] = None, **kwargs: Any) -> SendResult:
        return await self._send_media_file("sendPhoto", "photo", chat_id, image_path, caption)

    async def send_document(self, chat_id: str, file_path: str, caption: Optional[str] = None, **kwargs: Any) -> SendResult:
        return await self._send_media_file("sendDocument", "document", chat_id, file_path, caption)

    async def send_voice(self, chat_id: str, audio_path: str, caption: Optional[str] = None, **kwargs: Any) -> SendResult:
        return await self._send_media_file("sendVoice", "voice", chat_id, audio_path, caption)

    async def send_video(self, chat_id: str, video_path: str, caption: Optional[str] = None, **kwargs: Any) -> SendResult:
        return await self._send_media_file("sendVideo", "video", chat_id, video_path, caption)


async def _standalone_send(target: str, text: str, **kwargs: Any) -> Dict[str, Any]:
    """Out-of-process sender for cron jobs delivering to Bale when gateway is not running in-process."""
    token = get_scoped_secret("BALE_BOT_TOKEN") or os.getenv("BALE_BOT_TOKEN", "")
    if not token:
        return {"success": False, "error": "BALE_BOT_TOKEN is not set"}
    try:
        api_base = validate_bale_api_base(get_scoped_secret("BALE_API_BASE_URL") or os.getenv("BALE_API_BASE_URL"), BALE_DEFAULT_API_BASE)
    except ValueError:
        return {"success": False, "error": "Invalid Bale API endpoint configuration"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{api_base}{token}/sendMessage", json={"chat_id": target, "text": text[:BALE_MAX_MESSAGE_LEN]})
        data = resp.json()
        if data.get("ok"):
            mid = str((data.get("result") or {}).get("message_id") or "")
            return {"success": True, "message_id": mid}
        return {"success": False, "error": str(data.get("description") or data)}


def _env_enablement() -> Optional[dict]:
    return seed_extra_from_env(_BALE_ENV_TABLE, home_env="BALE_HOME_CHANNEL")


def _apply_yaml_config(yaml_cfg: dict, platform_cfg: dict) -> Optional[dict]:
    return apply_yaml_bridge(platform_cfg, _BALE_YAML_TABLE)


def register(ctx: Any) -> None:
    ctx.register_platform(
        name="bale",
        label="Bale Messenger (بله)",
        dashboard_description="Connect Noryka to Bale Messenger (پیام‌رسان بله) via tapi.bale.ai.",
        adapter_factory=BaleAdapter,
        check_fn=check_requirements,
        is_connected=is_connected,
        required_env=["BALE_BOT_TOKEN"],
        install_hint="Included in core (httpx)",
        env_enablement_fn=_env_enablement,
        apply_yaml_config_fn=_apply_yaml_config,
        cron_deliver_env_var="BALE_HOME_CHANNEL",
        standalone_sender_fn=_standalone_send,
        allowed_users_env="BALE_ALLOWED_USERS",
        allow_all_env="BALE_ALLOW_ALL_USERS",
        max_message_length=BALE_MAX_MESSAGE_LEN,
        emoji="🟢",
        allow_update_command=True,
        platform_hint=(
            "You are communicating with the user on Bale Messenger (پیام‌رسان بله). "
            "Keep formatting clean and concise; messages are capped at 4096 characters."
        ),
    )



# ============================================================================
# Security Audit Fixes (GW-01..GW-12) & Interactive Button Callback Handler
# ============================================================================
import re as _re
from urllib.parse import urlparse as _urlparse

_ALLOWED_BALE_HOSTS = {"tapi.bale.ai"}
_VALID_APPROVAL_CHOICES = {"once", "session", "always", "deny"}
_MAX_CB_BYTES = 64
_APPROVAL_CALLBACK_TTL_SECONDS = 600.0
_MAX_MEDIA_BYTES = 20 * 1024 * 1024


def _redact_bale_secret(value: Any, token: str = "") -> str:
    text = str(value)
    return text.replace(token, "[REDACTED]") if token else text


def _redact_bale_payload(payload: Dict[str, Any], token: str) -> Dict[str, Any]:
    """Redact the bot token recursively before API errors can reach logs or callers."""
    def clean(value):
        if isinstance(value, str):
            return _redact_bale_secret(value, token)
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        return value
    return clean(payload)


async def _read_bale_media_stream(response: httpx.Response) -> bytes:
    """Buffer Bale media only after enforcing the hard 20 MiB limit per streamed chunk."""
    declared = response.headers.get("content-length")
    if declared:
        try:
            if int(declared) > _MAX_MEDIA_BYTES:
                raise ValueError("Bale media exceeds configured maximum size")
        except ValueError as exc:
            if "exceeds" in str(exc):
                raise
    chunks: List[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes(chunk_size=65536):
        total += len(chunk)
        if total > _MAX_MEDIA_BYTES:
            raise ValueError("Bale media exceeds configured maximum size")
        chunks.append(chunk)
    return b"".join(chunks)
_NL = chr(10)


def validate_bale_api_base(url: Optional[str], default: str = "https://tapi.bale.ai/bot") -> str:
    """GW-10: Enforce HTTPS and official allowlisted Bale host."""
    raw = (url or "").strip() or default
    parsed = _urlparse(raw)
    if parsed.scheme != "https":
        raise ValueError(f"Insecure Bale API scheme '{parsed.scheme}'; only 'https' is allowed.")
    if not parsed.hostname or parsed.hostname.lower() not in _ALLOWED_BALE_HOSTS:
        raise ValueError(f"Untrusted Bale API host '{parsed.hostname}'; allowed: {_ALLOWED_BALE_HOSTS}")
    return raw.rstrip("/")


_orig_bale_init = BaleAdapter.__init__


def _audited_bale_init(self, config: Optional[PlatformConfig] = None, **kwargs: Any) -> None:
    if config is None:
        config = PlatformConfig(enabled=True, token=os.getenv("BALE_BOT_TOKEN", ""))
    _orig_bale_init(self, config, **kwargs)
    validate_bale_api_base(getattr(self, "api_base", "https://tapi.bale.ai/bot"))
    self._approval_token_map: Dict[str, Tuple[str, str, float]] = {}


BaleAdapter.__init__ = _audited_bale_init


def _audited_is_user_authorized(
    self,
    user_id: Any,
    chat_id: Any = None,
    *,
    is_group: bool = False,
    require_personal_auth: bool = False,
) -> bool:
    """GW-03 & GW-07: Fail-closed authorization separating individual user and group policies."""
    uid = str(user_id or "").strip()
    cid = str(chat_id or "").strip()
    if not uid:
        return False

    extra = getattr(self.config, "extra", None) or {}
    if (
        extra.get("allow_all_users") is True
        or os.getenv("BALE_ALLOW_ALL_USERS", "").strip().lower() in ("1", "true", "yes")
        or os.getenv("GATEWAY_ALLOW_ALL_USERS", "").strip().lower() in ("1", "true", "yes")
    ):
        return True

    raw_users = extra.get("allowed_users") or os.getenv("BALE_ALLOWED_USERS", "")
    if isinstance(raw_users, (list, tuple, set)):
        allowed_users = {str(x).strip() for x in raw_users if str(x).strip()}
    else:
        allowed_users = {x.strip() for x in str(raw_users).split(",") if x.strip()}

    raw_groups = extra.get("allowed_groups") or os.getenv("BALE_ALLOWED_GROUPS", "")
    if isinstance(raw_groups, (list, tuple, set)):
        allowed_groups = {str(x).strip() for x in raw_groups if str(x).strip()}
    else:
        allowed_groups = {x.strip() for x in str(raw_groups).split(",") if x.strip()}

    if require_personal_auth:
        return uid in allowed_users

    if uid in allowed_users:
        return True

    if is_group and cid and cid in allowed_groups:
        return True

    return False


BaleAdapter._is_user_authorized = _audited_is_user_authorized


def _build_approval_callback_data(self, request_id: str, session_key: str, choice: str) -> str:
    """GW-08 & GW-09: Compact validated callback payload <= 64 bytes."""
    if choice not in _VALID_APPROVAL_CHOICES:
        raise ValueError(f"Invalid approval choice: {choice}")
    req_clean = _re.sub(r"[^a-zA-Z0-9_-]", "", str(request_id))[:24]
    if not req_clean:
        raise ValueError("Empty request_id")
    if not hasattr(self, "_approval_token_map"):
        self._approval_token_map = {}
    req_token = secrets.token_urlsafe(9)
    self._approval_token_map[req_token] = (str(request_id), str(session_key), time.monotonic() + _APPROVAL_CALLBACK_TTL_SECONDS)
    data = f"ea:{req_token}:{choice}"
    if len(data.encode("utf-8")) > _MAX_CB_BYTES:
        raise ValueError("Callback data exceeds 64-byte limit")
    return data


BaleAdapter.build_approval_callback_data = _build_approval_callback_data


def _main_menu_markup(self) -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "📊 وضعیت نوریکا", "callback_data": "cmd:/status"}],
            [
                {"text": "🔄 سلامت و تعویض API (Fallback)", "callback_data": "cmd:/fallback"},
                {"text": "🧠 انتخاب مدل هوش مصنوعی", "callback_data": "cmd:/models"},
            ],
            [
                {"text": "💾 بک‌آپ‌گیری فوری", "callback_data": "cmd:/backup"},
                {"text": "📂 بازیابی بک‌آپ (Restore)", "callback_data": "cmd:/restore"},
            ],
            [
                {"text": "🆕 گفتگوی جدید", "callback_data": "cmd:/new"},
                {"text": "⏹️ توقف پردازش", "callback_data": "cmd:/stop"},
            ],
        ]
    }


BaleAdapter._main_menu_markup = _main_menu_markup


async def _safe_answer_cb(self, cb_id: str) -> None:
    if not cb_id or not getattr(self, "_client", None):
        return
    with contextlib.suppress(Exception):
        url = self._method_url("answerCallbackQuery") if hasattr(self, "_method_url") else f"{self.api_base}{self.token}/answerCallbackQuery"
        await self._client.post(url, json={"callback_query_id": str(cb_id)}, timeout=5.0)


BaleAdapter._safe_answer_cb = _safe_answer_cb


async def _dispatch_bale_panel_cmd(self, cmd: str, chat_id: str, user_id: str) -> bool:
    norm = cmd.strip()
    lower = norm.lower()

    try:
        from plugins.platforms.bale import backup_and_fallback as bf
        if lower.startswith("/fallback") and hasattr(bf, "handle_fallback_async"):
            return await bf.handle_fallback_async(self, chat_id, norm)
        if (lower.startswith("/backup") or lower.startswith("/restore")) and hasattr(bf, "handle_backup_async"):
            return await bf.handle_backup_async(self, chat_id, norm)
        if lower.startswith("/models") and hasattr(bf, "handle_models_async"):
            return await bf.handle_models_async(self, chat_id, norm)
    except Exception as exc:
        logger.debug("Optional bale suite handler skipped: %s", exc)

    orig_builtin = getattr(self, "_handle_builtin_bale_command", None)
    if callable(orig_builtin):
        with contextlib.suppress(Exception):
            res = orig_builtin(norm, chat_id)
            if asyncio.iscoroutine(res):
                res = await res
            if res:
                return True

    if lower in ("/start", "/help", "/menu", "منو", "شروع"):
        lines = [
            "🤖 **پنل هوشمند نوریکا (بله)**",
            "",
            "از طریق دکمه‌های شیشه‌ای زیر می‌توانید مدل‌ها، سلامت API و بک‌آپ سیستم را مدیریت کنید یا مستقیماً پیام خود را ارسال نمایید:",
        ]
        await self.send(chat_id, _NL.join(lines), metadata={"reply_markup": self._main_menu_markup()})
        return True

    if lower == "/status":
        lines = [
            "🟢 **وضعیت نوریکا:** متصل به هسته Agent و آماده پردازش.",
            "• پلتفرم: Bale (رسمی)",
            "• امنیت Allowlist: فعال",
        ]
        await self.send(chat_id, _NL.join(lines), metadata={"reply_markup": self._main_menu_markup()})
        return True

    if lower == "/new":
        await self.send(chat_id, "🔄 نشست گفتگو تازه شد. پیام جدید خود را ارسال کنید.", metadata={"reply_markup": self._main_menu_markup()})
        return True

    if lower == "/stop":
        await self.send(chat_id, "⏹️ پردازش جاری متوقف شد.", metadata={"reply_markup": self._main_menu_markup()})
        return True

    return False


BaleAdapter._dispatch_bale_panel_cmd = _dispatch_bale_panel_cmd


async def _audited_handle_callback_query(self, cb: Dict[str, Any]) -> None:
    """Validate callbacks and resolve approvals through the central synchronous queue."""
    cb_id = str(cb.get("id") or "")
    raw_data = str(cb.get("data") or "").strip()
    sender = cb.get("from") or {}
    user_id = str(sender.get("id") or "").strip()
    msg = cb.get("message") or {}
    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id") or user_id).strip()
    chat_type = str(chat.get("type") or "private").lower()
    is_group = chat_type in ("group", "supergroup", "channel")

    if not raw_data or len(raw_data.encode("utf-8")) > _MAX_CB_BYTES:
        logger.warning("Rejected invalid/oversized Bale callback data.")
        if cb_id:
            await self._api_request("answerCallbackQuery", json_body={"callback_query_id": cb_id, "text": "Invalid callback.", "show_alert": True})
        return

    if raw_data.startswith("ea:"):
        if not self._is_user_authorized(user_id, chat_id, is_group=is_group, require_personal_auth=True):
            logger.warning("Unauthorized Bale approval callback attempt by user_id=%s", user_id)
            if cb_id:
                await self._api_request("answerCallbackQuery", json_body={"callback_query_id": cb_id, "text": "Unauthorized caller.", "show_alert": True})
            return
        parts = raw_data.split(":")
        if len(parts) != 3:
            logger.warning("Malformed Bale approval callback.")
            return
        _, req_token, choice = parts
        if choice not in _VALID_APPROVAL_CHOICES:
            logger.warning("Rejected invalid Bale approval choice.")
            return
        token_map = getattr(self, "_approval_token_map", {})
        mapped = token_map.get(req_token)
        if not mapped:
            logger.warning("Unknown or already-used Bale approval token.")
            return
        request_id, session_key, expires_at = mapped
        if time.monotonic() >= expires_at:
            token_map.pop(req_token, None)
            logger.warning("Expired Bale approval token.")
            return

        # Consume the one-time token before resolving; no await occurs between lookup and pop.
        token_map.pop(req_token, None)
        from tools.approval import resolve_gateway_approval
        resolved = resolve_gateway_approval(
            session_key=session_key,
            choice=choice,
            request_id=request_id,
        )
        status = "Approval recorded." if resolved else "Approval is no longer pending."
        if cb_id:
            await self._api_request("answerCallbackQuery", json_body={"callback_query_id": cb_id, "text": status})
        if resolved and chat_id and msg.get("message_id"):
            await self.edit_message(
                chat_id, str(msg["message_id"]),
                f"{msg.get('text') or ''}\\n\\nDecision: {choice.upper()} (by {user_id})",
                force_final=True,
            )
        return

    if not self._is_user_authorized(user_id, chat_id, is_group=is_group):
        logger.warning("Unauthorized Bale callback from user_id=%s", user_id)
        if cb_id:
            await self._api_request("answerCallbackQuery", json_body={"callback_query_id": cb_id, "text": "Unauthorized caller.", "show_alert": True})
        return

    cmd = raw_data[4:].strip() if raw_data.startswith("cmd:") else raw_data
    if not cmd.startswith("/"):
        cmd = "/" + cmd
    if await self._dispatch_bale_panel_cmd(cmd, chat_id, user_id):
        return
    synthetic_msg = {
        "message_id": msg.get("message_id") or 0,
        "from": sender or {"id": user_id},
        "chat": {"id": chat_id, "type": chat_type},
        "text": cmd,
    }
    if hasattr(self, "_handle_message_update"):
        await self._handle_message_update(synthetic_msg, int(synthetic_msg["message_id"] or 0))


BaleAdapter._handle_callback_query = _audited_handle_callback_query
