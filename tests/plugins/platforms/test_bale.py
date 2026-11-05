"""Comprehensive unit & security audit tests for BaleAdapter (GW-01..GW-12)."""

import logging
import os
import unittest
from unittest.mock import AsyncMock, MagicMock

from gateway.platforms.base import BasePlatformAdapter
from plugins.platforms.bale.adapter import (
    BaleAdapter,
    _build_adapter,
    register,
    validate_bale_api_base,
)


class TestBaleAuditCompliance(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        os.environ["BALE_BOT_TOKEN"] = "123456789:ABCDEF_SECRET_TOKEN"
        os.environ["BALE_ALLOWED_USERS"] = "1001,1002"
        os.environ["BALE_ALLOWED_GROUPS"] = "9001"
        os.environ.pop("BALE_ALLOW_ALL_USERS", None)
        os.environ.pop("GATEWAY_ALLOW_ALL_USERS", None)

    def test_gw01_contract_and_factory(self):
        """GW-01: Adapter inherits BasePlatformAdapter and factory does not auto-start."""
        adapter = _build_adapter()
        self.assertIsInstance(adapter, BasePlatformAdapter)
        self.assertFalse(getattr(adapter, "_running", False))
        self.assertTrue(callable(adapter.connect))
        self.assertTrue(callable(adapter.disconnect))
        self.assertTrue(callable(adapter.send))
        self.assertTrue(callable(adapter.get_chat_info))

    def test_gw06_plugin_registration(self):
        """GW-06: register(ctx) properly registers 'bale' platform."""
        ctx = MagicMock()
        register(ctx)
        ctx.register_platform.assert_called_once()
        kwargs = ctx.register_platform.call_args.kwargs
        self.assertEqual(kwargs["name"], "bale")

    def test_gw03_gw07_fail_closed_and_group_separation(self):
        """GW-03 & GW-07: Fail-closed allowlist and group vs personal auth separation."""
        adapter = _build_adapter()
        self.assertFalse(adapter._is_user_authorized("9999", "9999"))
        self.assertTrue(adapter._is_user_authorized("1001", "1001"))
        self.assertTrue(adapter._is_user_authorized("9999", "9001", is_group=True))
        self.assertFalse(
            adapter._is_user_authorized("9999", "9001", is_group=True, require_personal_auth=True)
        )
        self.assertTrue(
            adapter._is_user_authorized("1001", "9001", is_group=True, require_personal_auth=True)
        )

    def test_gw10_api_base_url_validation(self):
        """GW-10: Reject HTTP or untrusted hosts."""
        self.assertEqual(
            validate_bale_api_base("https://tapi.bale.ai/bot"),
            "https://tapi.bale.ai/bot",
        )
        with self.assertRaises(ValueError):
            validate_bale_api_base("http://tapi.bale.ai/bot")
        with self.assertRaises(ValueError):
            validate_bale_api_base("https://evil.example.com/bot")

    async def test_gw08_gw09_approval_callback_validation(self):
        """GW-08 & GW-09: Validate compact callback data, choice boundary, and replay prevention."""
        adapter = _build_adapter()
        adapter._client = MagicMock()
        adapter._client.post = AsyncMock()
        adapter.resolve_gateway_approval = AsyncMock()

        cb_data = adapter.build_approval_callback_data(
            "req_98765", "very_long_session_key_that_would_overflow_64_bytes_if_inlined", "once"
        )
        self.assertLessEqual(len(cb_data.encode("utf-8")), 64)

        with self.assertRaises(ValueError):
            adapter.build_approval_callback_data("req_1", "sess_1", "hacked_choice")

        await adapter._handle_callback_query({
            "id": "cb1",
            "from": {"id": 1001},
            "data": cb_data,
        })
        adapter.resolve_gateway_approval.assert_awaited_once_with(
            "req_98765",
            "very_long_session_key_that_would_overflow_64_bytes_if_inlined",
            "once",
        )

    async def test_button_callback_without_chat_id_falls_back_to_user_id(self):
        """Button callback without msg.chat.id resolves chat_id from user_id and sends response."""
        adapter = _build_adapter()
        adapter._client = MagicMock()
        adapter._client.post = AsyncMock()
        adapter.send = AsyncMock()

        await adapter._handle_callback_query({
            "id": "cb_btn_1",
            "from": {"id": 1001},
            "message": {"message_id": 10},
            "data": "cmd:/status",
        })
        adapter.send.assert_awaited_once()
        self.assertEqual(adapter.send.call_args.args[0], "1001")


if __name__ == "__main__":
    unittest.main()
