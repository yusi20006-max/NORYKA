"""Bale platform adapter for Noryka Gateway.
Compliant with BasePlatformAdapter contract and Security Audit GW-01..GW-12.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

import httpx

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import (
    BasePlatformAdapter,
    SendResult,
    cache_audio_from_bytes,
    cache_document_from_bytes,
    cache_image_from_bytes,
    validate_inbound_media_size,
)
from gateway.platforms.event import MessageEvent, MessageType, SourceInfo

try:
    from gateway.platforms.base import _read_httpx_body_with_limit
except ImportError:
    async def _read_httpx_body_with_limit(resp: httpx.Response, max_bytes: int) -> bytes:
        content_len = resp.headers.get("Content-Length")
        if content_len and int(content_len) > max_bytes:
            raise ValueError(f"Media exceeds maximum allowed size ({max_bytes} bytes)")
        chunks = []
        total = 0
        async for chunk in resp.aiter_bytes(chunk_size=65536):
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(f"Media stream exceeded maximum size ({max_bytes} bytes)")
            chunks.append(chunk)
        return b"".join(chunks)

logger = logging.getLogger(__name__)

# GW-10: Official allowlisted Bale API hosts (HTTPS only)
ALLOWED_BALE_HOSTS: Set[str] = {"tapi.bale.ai"}
DEFAULT_BALE_API_BASE = "https://tapi.bale.ai/bot"
DEFAULT_BALE_FILE_BASE = "https://tapi.bale.ai/file/bot"
MAX_CALLBACK_DATA_BYTES = 64
VALID_APPROVAL_CHOICES: Set[str] = {"once", "session", "always", "deny"}
MAX_MEDIA_BYTES = 20 * 1024 * 1024  # 20 MB ceiling
NL = chr(10)


def validate_bale_api_base(url: Optional[str], default: str = DEFAULT_BALE_API_BASE) -> str:
    """GW-10: Validate API base URL is HTTPS and targets an allowlisted Bale host."""
    raw = (url or "").strip() or default
    parsed = urlparse(raw)
    if parsed.scheme != "https":
        raise ValueError(f"Insecure Bale API scheme '{parsed.scheme}'; only 'https' is permitted.")
    if not parsed.hostname or parsed.hostname.lower() not in ALLOWED_BALE_HOSTS:
        raise ValueError(f"Untrusted Bale API host '{parsed.hostname}'; allowed: {ALLOWED_BALE_HOSTS}")
    return raw.rstrip("/")


def bale_deps_present() -> bool:
    return True


def check_bale_requirements() -> bool:
    return bool(os.getenv("BALE_BOT_TOKEN", "").strip())


class BaleAdapter(BasePlatformAdapter):
    """Official Noryka Gateway Adapter for Bale Messenger (GW-01..GW-12 compliant)."""

    platform = Platform.BALE if hasattr(Platform, "BALE") else "bale"
    name = "bale"

    def __init__(self, config: Optional[PlatformConfig] = None, **kwargs: Any) -> None:
        if config is None:
            config = PlatformConfig(enabled=True, token=os.getenv("BALE_BOT_TOKEN", ""))
        super().__init__(config, self.platform)

        extra = getattr(config, "extra", None) or {}
        self.token: str = (
            getattr(config, "token", None)
            or extra.get("token")
            or os.getenv("BALE_BOT_TOKEN")
            or ""
        ).strip()

        # GW-10: Strict validation of API base URLs
        custom_api_base = extra.get("api_base_url") or os.getenv("BALE_API_BASE_URL")
        custom_file_base = extra.get("file_base_url") or os.getenv("BALE_FILE_BASE_URL")
        self.api_base: str = validate_bale_api_base(custom_api_base, DEFAULT_BALE_API_BASE)
        self.file_base: str = validate_bale_api_base(custom_file_base, DEFAULT_BALE_FILE_BASE)

        self._client: Optional[httpx.AsyncClient] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._offset: int = 0
        self._seen_update_ids: Set[int] = set()
        self._bot_info: Dict[str, Any] = {}
        # GW-08: Ephemeral compact callback token map to avoid 64-byte truncation of session_key
        self._approval_token_map: Dict[str, Tuple[str, str]] = {}

    def _method_url(self, method: str) -> str:
        return f"{self.api_base}{self.token}/{method}"

    def _file_url(self, file_path: str) -> str:
        clean_path = file_path.lstrip("/")
        return f"{self.file_base}{self.token}/{clean_path}"

    def _get_allowed_users(self) -> Set[str]:
        extra = getattr(self.config, "extra", None) or {}
        raw = extra.get("allowed_users") or os.getenv("BALE_ALLOWED_USERS", "")
        if isinstance(raw, (list, tuple, set)):
            return {str(x).strip() for x in raw if str(x).strip()}
        return {x.strip() for x in str(raw).split(",") if x.strip()}

    def _get_allowed_groups(self) -> Set[str]:
        extra = getattr(self.config, "extra", None) or {}
        raw = extra.get("allowed_groups") or os.getenv("BALE_ALLOWED_GROUPS", "")
        if isinstance(raw, (list, tuple, set)):
            return {str(x).strip() for x in raw if str(x).strip()}
        return {x.strip() for x in str(raw).split(",") if x.strip()}

    def _is_allow_all_enabled(self) -> bool:
        extra = getattr(self.config, "extra", None) or {}
        if extra.get("allow_all_users") is True:
            return True
        return (
            os.getenv("BALE_ALLOW_ALL_USERS", "").strip().lower() in ("1", "true", "yes")
            or os.getenv("GATEWAY_ALLOW_ALL_USERS", "").strip().lower() in ("1", "true", "yes")
        )

    def _is_user_authorized(
        self,
        user_id: Optional[str],
        chat_id: Optional[str] = None,
        *,
        is_group: bool = False,
        require_personal_auth: bool = False,
    ) -> bool:
        """GW-03 & GW-07: Fail-closed authorization separating individual user and group policies."""
        uid = str(user_id or "").strip()
        cid = str(chat_id or "").strip()
        if not uid:
            return False

        if self._is_allow_all_enabled():
            return True

        allowed_users = self._get_allowed_users()
        allowed_groups = self._get_allowed_groups()

        if require_personal_auth:
            return uid in allowed_users

        if uid in allowed_users:
            return True

        if is_group and cid and cid in allowed_groups:
            return True

        return False

    async def connect(self) -> bool:
        """GW-01 & Section 4: Idempotent async connect, getMe check, and single polling task."""
        if not self.token:
            logger.warning("BaleAdapter: BALE_BOT_TOKEN is not configured.")
            return False

        if self._running and self._poll_task and not self._poll_task.done():
            return True

        if self._client is not None:
            with contextlib.suppress(Exception):
                await self._client.aclose()

        self._client = httpx.AsyncClient(timeout=httpx.Timeout(35.0, connect=10.0))
        try:
            resp = await self._client.get(self._method_url("getMe"))
            data = resp.json() if resp.status_code == 200 else {}
            if not data.get("ok"):
                logger.error("BaleAdapter: getMe authentication failed (HTTP %s).", resp.status_code)
                await self._client.aclose()
                self._client = None
                return False
            self._bot_info = data.get("result") or {}
            bot_username = self._bot_info.get("username", "bale_bot")
            logger.info("BaleAdapter connected successfully as @%s", bot_username)
        except Exception as exc:
            logger.error("BaleAdapter connection failed: %s", type(exc).__name__)
            if self._client:
                await self._client.aclose()
                self._client = None
            return False

        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop(), name="bale-polling")
        return True

    async def disconnect(self) -> None:
        """GW-01 & Section 4: Cleanly cancel polling task and close HTTP client."""
        self._running = False
        if self._poll_task is not None:
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._poll_task
            self._poll_task = None

        if self._client is not None:
            with contextlib.suppress(Exception):
                await self._client.aclose()
            self._client = None
        logger.info("BaleAdapter disconnected cleanly.")

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> SendResult:
        """GW-01: Standard Gateway outbound send method."""
        target_chat = str(chat_id or "").strip()
        if not target_chat or not self._client:
            return SendResult(success=False, error="Missing chat_id or client not connected")

        payload: Dict[str, Any] = {
            "chat_id": target_chat,
            "text": content or "",
        }
        if reply_to:
            payload["reply_to_message_id"] = reply_to

        reply_markup = (metadata or {}).get("reply_markup") or kwargs.get("reply_markup")
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            resp = await self._client.post(self._method_url("sendMessage"), json=payload)
            data = resp.json() if resp.status_code == 200 else {}
            if data.get("ok"):
                msg_res = data.get("result") or {}
                msg_id = str(msg_res.get("message_id", ""))
                return SendResult(success=True, message_id=msg_id)
            return SendResult(success=False, error=f"Bale sendMessage failed: HTTP {resp.status_code}")
        except Exception as exc:
            logger.error("BaleAdapter send error: %s", type(exc).__name__)
            return SendResult(success=False, error=str(exc))

    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        """GW-01: Standard Gateway get_chat_info method."""
        if not self._client or not chat_id:
            return {"id": str(chat_id), "type": "unknown"}
        try:
            resp = await self._client.post(
                self._method_url("getChat"), json={"chat_id": str(chat_id)}
            )
            data = resp.json() if resp.status_code == 200 else {}
            if data.get("ok"):
                return data.get("result") or {"id": str(chat_id)}
        except Exception as exc:
            logger.debug("get_chat_info failed: %s", type(exc).__name__)
        return {"id": str(chat_id), "type": "private"}

    async def _safe_answer_callback(self, callback_query_id: str, text: Optional[str] = None) -> None:
        if not callback_query_id or not self._client:
            return
        payload: Dict[str, Any] = {"callback_query_id": str(callback_query_id)}
        if text:
            payload["text"] = text
        with contextlib.suppress(Exception):
            await self._client.post(self._method_url("answerCallbackQuery"), json=payload, timeout=5.0)

    async def _poll_loop(self) -> None:
        backoff = 1.0
        while self._running:
            try:
                if not self._client:
                    break
                payload = {"offset": self._offset, "limit": 25, "timeout": 20}
                resp = await self._client.post(self._method_url("getUpdates"), json=payload)

                if resp.status_code == 429:
                    retry_after = 5.0
                    with contextlib.suppress(Exception):
                        retry_after = float(resp.json().get("parameters", {}).get("retry_after", 5.0))
                    logger.warning("BaleAdapter rate limited (429); backing off for %.1fs", retry_after)
                    await asyncio.sleep(retry_after)
                    continue

                if resp.status_code >= 500:
                    logger.warning("Bale server error (%d); backing off %.1fs", resp.status_code, backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2.0, 30.0)
                    continue

                data = resp.json() if resp.status_code == 200 else {}
                if not data.get("ok"):
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2.0, 30.0)
                    continue

                backoff = 1.0
                updates = data.get("result") or []
                for upd in updates:
                    if not self._running:
                        break
                    upd_id = upd.get("update_id")
                    if isinstance(upd_id, int):
                        if upd_id in self._seen_update_ids:
                            self._offset = max(self._offset, upd_id + 1)
                            continue
                        self._seen_update_ids.add(upd_id)
                        if len(self._seen_update_ids) > 1000:
                            oldest = sorted(self._seen_update_ids)[:500]
                            self._seen_update_ids.difference_update(oldest)

                    await self._process_update(upd)

                    if isinstance(upd_id, int):
                        self._offset = max(self._offset, upd_id + 1)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Bale polling error (%s); retrying in %.1fs", type(exc).__name__, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 30.0)

    async def _download_media(self, file_id: str, media_kind: str, filename: str = "") -> Optional[str]:
        if not self._client or not file_id:
            return None
        try:
            info_resp = await self._client.post(self._method_url("getFile"), json={"file_id": file_id})
            info_data = info_resp.json() if info_resp.status_code == 200 else {}
            if not info_data.get("ok"):
                return None
            file_res = info_data.get("result") or {}
            file_size = file_res.get("file_size")
            if isinstance(file_size, int) and file_size > MAX_MEDIA_BYTES:
                logger.warning("Rejected inbound Bale media exceeding size limit (%d bytes)", file_size)
                return None
            file_path = file_res.get("file_path") or ""
            if not file_path:
                return None

            async with self._client.stream("GET", self._file_url(file_path)) as stream_resp:
                if stream_resp.status_code != 200:
                    return None
                raw_bytes = await _read_httpx_body_with_limit(stream_resp, MAX_MEDIA_BYTES)

            validate_inbound_media_size(len(raw_bytes), media_kind)

            raw_name = Path(filename or Path(file_path).name or "file.bin").name
            safe_name = "".join(ch if (ord(ch) >= 32 and ch not in ("/", chr(92))) else "_" for ch in raw_name) or "file.bin"

            if media_kind == "image":
                return cache_image_from_bytes(raw_bytes, safe_name)
            if media_kind == "audio":
                return cache_audio_from_bytes(raw_bytes, safe_name)
            return cache_document_from_bytes(raw_bytes, safe_name)
        except Exception as exc:
            logger.warning("Bale media download rejected/failed: %s", exc)
            return None

    def build_approval_callback_data(self, request_id: str, session_key: str, choice: str) -> str:
        """GW-08 & GW-09: Compact validated callback payload <= 64 bytes."""
        if choice not in VALID_APPROVAL_CHOICES:
            raise ValueError(f"Invalid approval choice: {choice}")
        req_clean = re.sub(r"[^a-zA-Z0-9_-]", "", str(request_id))[:24]
        if not req_clean:
            raise ValueError("Empty request_id")
        self._approval_token_map[req_clean] = (str(request_id), str(session_key))
        data = f"ea:{req_clean}:{choice}"
        if len(data.encode("utf-8")) > MAX_CALLBACK_DATA_BYTES:
            raise ValueError("Callback data exceeds 64-byte limit")
        return data

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

    async def _handle_builtin_bale_command(self, cmd: str, chat_id: str, user_id: str) -> bool:
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

        if lower in ("/start", "/help", "/menu", "منو", "شروع"):
            lines = [
                "🤖 **پنل هوشمند نوریکا (بله)**",
                "",
                "از طریق دکمه‌های شیشه‌ای زیر می‌توانید مدل‌ها، سلامت API و بک‌آپ سیستم را مدیریت کنید یا مستقیماً پیام خود را ارسال نمایید:",
            ]
            await self.send(chat_id, NL.join(lines), metadata={"reply_markup": self._main_menu_markup()})
            return True

        if lower == "/status":
            lines = [
                "🟢 **وضعیت نوریکا:** متصل به هسته Agent و آماده پردازش.",
                "• پلتفرم: Bale (رسمی)",
                "• امنیت Allowlist: فعال",
            ]
            await self.send(
                chat_id,
                NL.join(lines),
                metadata={"reply_markup": self._main_menu_markup()},
            )
            return True

        return False

    async def _process_update(self, update: Dict[str, Any]) -> None:
        if "callback_query" in update:
            await self._handle_callback_query(update["callback_query"])
            return

        msg = update.get("message") or update.get("edited_message")
        if isinstance(msg, dict):
            await self._handle_inbound_message(msg)

    async def _handle_callback_query(self, cb: Dict[str, Any]) -> None:
        cb_id = str(cb.get("id") or "")
        raw_data = str(cb.get("data") or "").strip()
        sender = cb.get("from") or {}
        user_id = str(sender.get("id") or "").strip()
        msg = cb.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id = str(chat.get("id") or user_id).strip()
        chat_type = str(chat.get("type") or "private").lower()
        is_group = chat_type in ("group", "supergroup", "channel")

        asyncio.create_task(self._safe_answer_callback(cb_id))

        if not raw_data or len(raw_data.encode("utf-8")) > MAX_CALLBACK_DATA_BYTES:
            logger.warning("Rejected invalid/oversized Bale callback data.")
            return

        if raw_data.startswith("ea:"):
            if not self._is_user_authorized(user_id, chat_id, is_group=is_group, require_personal_auth=True):
                logger.warning("Unauthorized Bale approval callback attempt by user_id=%s", user_id)
                return

            parts = raw_data.split(":")
            if len(parts) == 3:
                _, req_token, choice = parts
                mapped = self._approval_token_map.get(req_token)
                if not mapped:
                    logger.warning("Unknown or expired approval request token: %s", req_token)
                    return
                request_id, session_key = mapped
            elif len(parts) == 4:
                _, request_id, session_key, choice = parts
            else:
                logger.warning("Malformed approval callback format.")
                return

            if choice not in VALID_APPROVAL_CHOICES:
                logger.warning("Rejected invalid approval choice: %s", choice)
                return

            if not request_id or not session_key:
                return

            self._approval_token_map.pop(request_id, None)
            resolver = getattr(self, "resolve_gateway_approval", None)
            if callable(resolver):
                res = resolver(request_id, session_key, choice)
                if asyncio.iscoroutine(res):
                    await res
            return

        if not self._is_user_authorized(user_id, chat_id, is_group=is_group):
            logger.warning("Unauthorized Bale callback from user_id=%s", user_id)
            return

        cmd = raw_data
        if cmd.startswith("cmd:"):
            cmd = cmd[4:].strip()
        if not cmd.startswith("/"):
            cmd = "/" + cmd

        if await self._handle_builtin_bale_command(cmd, chat_id, user_id):
            return

        event = MessageEvent(
            text=cmd,
            message_type=MessageType.COMMAND if hasattr(MessageType, "COMMAND") else MessageType.TEXT,
            source=SourceInfo(
                platform=self.platform,
                chat_id=chat_id,
                user_id=user_id,
                user_name=sender.get("username") or sender.get("first_name") or user_id,
                is_group=is_group,
            ),
            raw_message=cb,
        )
        await self.handle_message(event)

    async def _handle_inbound_message(self, msg: Dict[str, Any]) -> None:
        sender = msg.get("from") or {}
        user_id = str(sender.get("id") or "").strip()
        chat = msg.get("chat") or {}
        chat_id = str(chat.get("id") or user_id).strip()
        chat_type = str(chat.get("type") or "private").lower()
        is_group = chat_type in ("group", "supergroup", "channel")

        if not self._is_user_authorized(user_id, chat_id, is_group=is_group):
            logger.warning("Denied unauthorized Bale message from user_id=%s chat_id=%s", user_id, chat_id)
            return

        text = str(msg.get("text") or msg.get("caption") or "").strip()
        msg_id = str(msg.get("message_id") or "")

        if text.startswith("/") or text in ("منو", "شروع"):
            if await self._handle_builtin_bale_command(text, chat_id, user_id):
                return

        media_urls: List[str] = []
        media_types: List[str] = []

        if "photo" in msg and isinstance(msg["photo"], list) and msg["photo"]:
            largest = msg["photo"][-1]
            cached = await self._download_media(largest.get("file_id", ""), "image", "photo.jpg")
            if cached:
                media_urls.append(cached)
                media_types.append("image/jpeg")

        for kind, mtype, default_name in (
            ("audio", "audio", "audio.mp3"),
            ("voice", "audio", "voice.ogg"),
            ("video", "document", "video.mp4"),
            ("document", "document", "document.bin"),
        ):
            if kind in msg and isinstance(msg[kind], dict):
                item = msg[kind]
                fname = item.get("file_name") or default_name
                cached = await self._download_media(item.get("file_id", ""), mtype, fname)
                if cached:
                    media_urls.append(cached)
                    media_types.append(item.get("mime_type") or mtype)

        is_cmd = text.startswith("/")
        m_type = (
            MessageType.COMMAND
            if (is_cmd and hasattr(MessageType, "COMMAND"))
            else MessageType.TEXT
        )
        event = MessageEvent(
            text=text,
            message_type=m_type,
            source=SourceInfo(
                platform=self.platform,
                chat_id=chat_id,
                user_id=user_id,
                user_name=sender.get("username") or sender.get("first_name") or user_id,
                is_group=is_group,
            ),
            raw_message=msg,
            message_id=msg_id,
            media_urls=media_urls,
            media_types=media_types,
        )
        await self.handle_message(event)


def _build_adapter(config: Optional[PlatformConfig] = None, **kwargs: Any) -> BaleAdapter:
    """GW-01: Factory returns unstarted BaleAdapter; Gateway manages connect() lifecycle."""
    return BaleAdapter(config=config, **kwargs)


def _standalone_send(target: str, text: str, **kwargs: Any) -> bool:
    """GW-10: Validated standalone sender for Bale."""
    token = os.getenv("BALE_BOT_TOKEN", "").strip()
    if not token or not target:
        return False
    api_base = validate_bale_api_base(os.getenv("BALE_API_BASE_URL"), DEFAULT_BALE_API_BASE)
    url = f"{api_base}{token}/sendMessage"
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, json={"chat_id": str(target), "text": text})
            return resp.status_code == 200 and bool(resp.json().get("ok"))
    except Exception:
        return False


def register(ctx: Any) -> None:
    """Official Noryka Plugin entry point for Bale."""
    ctx.register_platform(
        name="bale",
        label="Bale",
        adapter_factory=_build_adapter,
        check_fn=bale_deps_present,
        ensure_deps_fn=check_bale_requirements,
        required_env=["BALE_BOT_TOKEN"],
        standalone_sender_fn=_standalone_send,
        max_message_length=4096,
        emoji="💬",
        allow_update_command=True,
    )
