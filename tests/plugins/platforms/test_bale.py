"""Focused regression and security tests for the Bale Gateway adapter."""

import logging
import os
import threading
import time
import tempfile
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from gateway.config import PlatformConfig
from gateway.platforms.base import BasePlatformAdapter, ExecApprovalPrompt, MessageType, SendResult
from plugins.platforms.bale.adapter import (
    BaleAdapter,
    _redact_bale_secret,
    register,
    validate_bale_api_base,
)


TEST_TOKEN = "123456789:ABCDEF_TEST_ONLY"


class TestBaleGateway(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "BALE_BOT_TOKEN": TEST_TOKEN,
            "BALE_ALLOWED_USERS": "1001,1002",
            "BALE_ALLOWED_GROUPS": "9001",
        }, clear=False)
        self.env.start()
        os.environ.pop("BALE_ALLOW_ALL_USERS", None)
        os.environ.pop("GATEWAY_ALLOW_ALL_USERS", None)
        self.adapter = BaleAdapter(PlatformConfig(enabled=True, token=TEST_TOKEN, extra={}))

    def tearDown(self):
        self.env.stop()

    def test_gw01_contract_and_gw06_registration(self):
        self.assertIsInstance(self.adapter, BasePlatformAdapter)
        self.assertTrue(callable(self.adapter.connect))
        self.assertTrue(callable(self.adapter.disconnect))
        self.assertTrue(callable(self.adapter.send))
        self.assertTrue(callable(self.adapter.get_chat_info))
        ctx = MagicMock()
        register(ctx)
        ctx.register_platform.assert_called_once()
        self.assertEqual(ctx.register_platform.call_args.kwargs["name"], "bale")

    def test_gw03_gw07_fail_closed_and_group_policy(self):
        self.assertFalse(self.adapter._is_user_authorized("9999", "9999"))
        self.assertTrue(self.adapter._is_user_authorized("1001", "private-1"))
        self.assertTrue(self.adapter._is_user_authorized("9999", "9001", is_group=True))
        self.assertFalse(self.adapter._is_user_authorized(
            "9999", "9001", is_group=True, require_personal_auth=True
        ))
        self.assertTrue(self.adapter._is_user_authorized(
            "1001", "9001", is_group=True, require_personal_auth=True
        ))

    async def test_group_message_path_uses_group_allowlist(self):
        self.adapter.handle_message = AsyncMock()
        self.adapter._extract_media = AsyncMock(return_value=(MessageType.TEXT, [], []))
        await self.adapter._handle_message_update({
            "chat": {"id": "9001", "type": "group", "title": "Allowed group"},
            "from": {"id": "9999", "first_name": "Member"},
            "message_id": 5,
            "text": "hello",
        }, 10)
        self.adapter.handle_message.assert_awaited_once()

    def test_adapter_rejects_untrusted_api_base_during_construction(self):
        config = PlatformConfig(
            enabled=True, token=TEST_TOKEN, extra={"api_base_url": "https://evil.example/bot"}
        )
        with self.assertRaises(ValueError):
            BaleAdapter(config)

    def test_allow_all_never_bypasses_personal_admin_allowlist(self):
        with patch.dict(os.environ, {"BALE_ALLOW_ALL_USERS": "true"}):
            self.assertTrue(self.adapter._is_user_authorized("9999", "9001", is_group=True))
            self.assertFalse(self.adapter._is_user_authorized(
                "9999", "9001", is_group=True, require_personal_auth=True
            ))

    async def test_group_allowlist_cannot_execute_admin_commands(self):
        self.adapter.handle_message = AsyncMock()
        self.adapter._extract_media = AsyncMock(return_value=(MessageType.TEXT, [], []))
        await self.adapter._handle_message_update({
            "chat": {"id": "9001", "type": "group", "title": "Allowed group"},
            "from": {"id": "9999", "first_name": "Member"},
            "message_id": 6,
            "text": "/backup",
        }, 11)
        self.adapter.handle_message.assert_not_awaited()
        self.adapter._extract_media.assert_not_awaited()

    def test_gw10_api_base_validation(self):
        self.assertEqual(
            validate_bale_api_base("https://tapi.bale.ai/bot"),
            "https://tapi.bale.ai/bot",
        )
        for url in ("http://tapi.bale.ai/bot", "https://evil.example/bot",
                    "https://tapi.bale.ai.evil.example/bot",
                    "https://user:pass@tapi.bale.ai/bot",
                    "https://tapi.bale.ai:8443/bot",
                    "https://tapi.bale.ai/bot?redirect=evil"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_bale_api_base(url)

    async def test_standalone_sender_rejects_untrusted_endpoint(self):
        from plugins.platforms.bale.adapter import _standalone_send
        with patch.dict(os.environ, {"BALE_API_BASE_URL": "https://evil.example/bot"}):
            result = await _standalone_send("1001", "hello")
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Invalid Bale API endpoint configuration")

    async def test_api_exception_payload_redacts_bot_token(self):
        self.adapter._client = MagicMock()
        self.adapter._client.get = AsyncMock(side_effect=RuntimeError(TEST_TOKEN))
        result = await self.adapter._api_request("getMe", max_retries=0)
        self.assertNotIn(TEST_TOKEN, result["description"])
        self.assertIn("[REDACTED]", result["description"])

    def test_gw04_secret_redaction(self):
        self.assertNotIn(TEST_TOKEN, _redact_bale_secret(
            f"request failed at https://tapi.bale.ai/bot{TEST_TOKEN}/sendMessage", TEST_TOKEN
        ))

    def test_gw08_callback_is_compact_random_and_expires(self):
        first = self.adapter.build_approval_callback_data(
            "request-123", "session-key-that-is-longer-than-the-platform-limit", "once"
        )
        second = self.adapter.build_approval_callback_data(
            "request-123", "session-key-that-is-longer-than-the-platform-limit", "once"
        )
        self.assertLessEqual(len(first.encode("utf-8")), 64)
        self.assertNotEqual(first, second)
        self.assertNotEqual(first.split(":")[1], second.split(":")[1])
        with self.assertRaises(ValueError):
            self.adapter.build_approval_callback_data("request-1", "session-1", "forged")

    async def test_button_callback_without_chat_id_falls_back_to_user_id(self):
        self.adapter.handle_message = AsyncMock()
        self.adapter._extract_media = AsyncMock(return_value=(MessageType.TEXT, [], []))
        self.adapter._dispatch_bale_panel_cmd = AsyncMock(return_value=False)
        self.adapter._api_request = AsyncMock(return_value={"ok": True})
        await self.adapter._handle_callback_query({
            "id": "callback-without-chat",
            "from": {"id": "1001"},
            "message": {"message_id": 10},
            "data": "cmd:/unknown-test-command",
        })
        self.adapter.handle_message.assert_awaited_once()
        event = self.adapter.handle_message.await_args.args[0]
        self.assertEqual(str(event.source.chat_id), "1001")

    async def test_approval_prompt_uses_compact_callback_builder(self):
        self.adapter.send = AsyncMock(return_value=SendResult(success=True))
        prompt = ExecApprovalPrompt(
            chat_id="1001",
            session_key="session-key-long-enough-to-overflow-if-inlined",
            text="Approve operation?",
            actions=[("Approve once", "once", "primary")],
            command="dangerous-command",
            description="test",
            smart_denied=False,
            request_id="request-prompt-1",
        )
        await self.adapter._send_exec_approval_prompt(prompt)
        markup = self.adapter.send.call_args.kwargs["metadata"]["reply_markup"]
        callback_data = markup["inline_keyboard"][0][0]["callback_data"]
        self.assertLessEqual(len(callback_data.encode("utf-8")), 64)
        self.assertIn(callback_data.split(":")[1], self.adapter._approval_token_map)

    async def test_group_allowlist_cannot_execute_admin_callback(self):
        self.adapter._api_request = AsyncMock(return_value={"ok": True})
        self.adapter._dispatch_bale_panel_cmd = AsyncMock(return_value=True)
        await self.adapter._handle_callback_query({
            "id": "group-admin-callback",
            "from": {"id": "9999"},
            "message": {
                "message_id": 7,
                "chat": {"id": "9001", "type": "group"},
            },
            "data": "cmd:/backup",
        })
        self.adapter._dispatch_bale_panel_cmd.assert_not_awaited()

    async def test_gw09_callback_resolves_real_central_queue_once(self):
        import tools.approval as approval

        request_id = "request-integration-1"
        session_key = "bale:test-session"
        event = threading.Event()
        entry = SimpleNamespace(data={"request_id": request_id}, event=event, result=None, reason=None)
        with approval._lock:
            approval._gateway_queues[session_key] = [entry]

        callback = self.adapter.build_approval_callback_data(request_id, session_key, "once")
        token = callback.split(":")[1]
        self.adapter._api_request = AsyncMock(return_value={"ok": True})
        await self.adapter._handle_callback_query({
            "id": "callback-1",
            "from": {"id": "1001"},
            "message": {"message_id": 20, "chat": {"id": "private-1", "type": "private"}},
            "data": callback,
        })
        self.assertTrue(event.is_set())
        self.assertEqual(entry.result, "once")
        self.assertNotIn(token, self.adapter._approval_token_map)

        await self.adapter._handle_callback_query({
            "id": "callback-replay",
            "from": {"id": "1001"},
            "message": {"message_id": 20, "chat": {"id": "private-1", "type": "private"}},
            "data": callback,
        })
        self.assertEqual(entry.result, "once")
        with approval._lock:
            approval._gateway_queues.pop(session_key, None)

    async def test_gw09_expired_callback_is_rejected(self):
        callback = self.adapter.build_approval_callback_data("request-expired", "session-expired", "deny")
        token = callback.split(":")[1]
        request_id, session_key, _ = self.adapter._approval_token_map[token]
        self.adapter._approval_token_map[token] = (request_id, session_key, time.monotonic() - 1)
        self.adapter._api_request = AsyncMock(return_value={"ok": True})
        await self.adapter._handle_callback_query({
            "id": "callback-expired",
            "from": {"id": "1001"},
            "message": {"chat": {"id": "private-1", "type": "private"}},
            "data": callback,
        })
        self.assertNotIn(token, self.adapter._approval_token_map)

    def test_gw12_document_cache_rejects_path_escape(self):
        import gateway.platforms.base as platform_base

        with tempfile.TemporaryDirectory() as cache_root:
            with patch.object(platform_base, "get_document_cache_dir", return_value=Path(cache_root)):
                stored = Path(platform_base.cache_document_from_bytes(b"safe", "../../outside.txt"))
            self.assertTrue(stored.resolve().is_relative_to(Path(cache_root).resolve()))
            self.assertTrue(stored.is_file())

    async def test_gw11_streamed_download_enforces_incremental_limit(self):
        class ChunkedBody(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b"123"
                yield b"456"

            async def aclose(self):
                return None

        def handler(request):
            if request.url.path.endswith("/getFile"):
                return httpx.Response(200, json={"ok": True, "result": {"file_path": "media.bin"}})
            return httpx.Response(200, stream=ChunkedBody())

        self.adapter._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://tapi.bale.ai"
        )
        try:
            with patch("plugins.platforms.bale.adapter._MAX_MEDIA_BYTES", 4):
                with patch("plugins.platforms.bale.adapter.cache_media_bytes") as cache:
                    result = await self.adapter._download_bale_media("file-id", "application/octet-stream")
            self.assertIsNone(result)
            cache.assert_not_called()
        finally:
            await self.adapter._client.aclose()
            self.adapter._client = None


if __name__ == "__main__":
    unittest.main()
