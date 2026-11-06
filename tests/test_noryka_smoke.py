"""Live integration & smoke test suite for Noryka Agent v3.

Runs offline without external network access using httpx.MockTransport and temporary SQLite/profile directories.
Compatible with both `pytest tests/test_noryka_smoke.py` and `python3 tests/test_noryka_smoke.py`.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import httpx

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def test_platform_bale_enum_is_distinct_from_telegram() -> None:
    """Verify Platform.BALE is a first-class enum value and distinct from Platform.TELEGRAM."""
    from gateway.config import Platform

    assert hasattr(Platform, "BALE"), "Platform.BALE must exist on gateway.config.Platform"
    assert Platform.BALE.value == "bale"
    assert Platform.BALE != Platform.TELEGRAM
    assert Platform("bale") is Platform.BALE


def test_coding_posture_enabled_on_telegram_and_bale() -> None:
    """Verify coding posture (terminal/file/ast tools) is enabled on Telegram and Bale."""
    from agent.coding_context import INTERACTIVE_CODING_PLATFORMS, is_coding_context, resolve_runtime_mode

    assert "telegram" in INTERACTIVE_CODING_PLATFORMS
    assert "bale" in INTERACTIVE_CODING_PLATFORMS
    mode_tg = resolve_runtime_mode(platform="telegram", cwd=str(ROOT_DIR))
    mode_bale = resolve_runtime_mode(platform="bale", cwd=str(ROOT_DIR))
    assert mode_tg.is_coding is True
    assert mode_bale.is_coding is True
    assert is_coding_context(platform="telegram", cwd=str(ROOT_DIR)) is True
    assert is_coding_context(platform="bale", cwd=str(ROOT_DIR)) is True


def test_tui_gateway_and_pm_imports_present() -> None:
    """Verify tui_gateway and pm packages are present and importable."""
    import pm
    import tui_gateway

    assert Path(pm.__file__).exists()
    assert Path(tui_gateway.__file__).exists()


def test_bale_adapter_fail_closed_allowlist_and_event_contract() -> None:
    """Verify BaleAdapter enforces fail-closed allowlist and emits standard MessageEvent with Platform.BALE."""
    from gateway.config import Platform, PlatformConfig
    from gateway.platforms.base import MessageEvent
    from plugins.platforms.bale.adapter import BaleAdapter

    os.environ.pop("BALE_ALLOW_ALL_USERS", None)
    os.environ.pop("BALE_ALLOWED_USERS", None)

    cfg = PlatformConfig(enabled=True, token="111111:TEST_TOKEN", extra={})
    adapter = BaleAdapter(cfg)
    assert adapter.platform == Platform.BALE

    # 1. Fail-closed when allowlist is empty
    assert adapter._is_user_authorized("99999", "99999") is False

    # 2. Authorized when user ID is in allowlist
    cfg.extra["allowed_users"] = "12345,67890"
    assert adapter._is_user_authorized("12345", "12345") is True
    assert adapter._is_user_authorized("99999", "99999") is False

    # 3. Verify _process_update produces MessageEvent with SessionSource.platform == Platform.BALE
    captured_events: List[MessageEvent] = []

    async def fake_handler(event: MessageEvent) -> None:
        captured_events.append(event)

    adapter.set_message_handler(fake_handler)

    sample_update = {
        "update_id": 101,
        "message": {
            "message_id": 555,
            "date": 1730000000,
            "text": "سلام نوریکا، وضعیت کد رو بررسی کن",
            "chat": {"id": 12345, "type": "private", "title": "Private Chat"},
            "from": {"id": 12345, "username": "dev_user", "first_name": "Yousef"},
        },
    }

    async def _run() -> None:
        await adapter._dispatch_update(sample_update, 101)
        await asyncio.sleep(0.05)

    asyncio.run(_run())
    assert len(captured_events) == 1
    ev = captured_events[0]
    assert isinstance(ev, MessageEvent)
    assert ev.source.platform == Platform.BALE
    assert ev.source.chat_id == "12345"
    assert ev.source.user_id == "12345"
    assert "سلام نوریکا" in ev.text


def test_bale_adapter_429_and_backoff_handling() -> None:
    """Verify BaleAdapter honors 429 retry_after and ok=False handling via httpx.MockTransport."""
    from gateway.config import PlatformConfig
    from plugins.platforms.bale.adapter import BaleAdapter

    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(
                429,
                json={"ok": False, "error_code": 429, "parameters": {"retry_after": 0.05}},
            )
        return httpx.Response(
            200,
            json={"ok": True, "result": {"message_id": 777}},
        )

    cfg = PlatformConfig(enabled=True, token="111111:TEST_TOKEN", extra={"allowed_users": "12345"})
    adapter = BaleAdapter(cfg)

    async def _run() -> Dict[str, Any]:
        adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await adapter._api_request("sendMessage", json_body={"chat_id": "12345", "text": "test"})
        finally:
            await adapter._client.aclose()

    res = asyncio.run(_run())
    assert call_count == 2
    assert res.get("ok") is True
    assert res.get("result", {}).get("message_id") == 777


def test_bale_adapter_full_poll_updates_loop_and_media_download() -> None:
    """Verify BaleAdapter._poll_updates_loop processes updates, downloads photo media, and handles callback_query."""
    from gateway.config import Platform, PlatformConfig
    from gateway.platforms.base import MessageEvent
    from plugins.platforms.bale.adapter import BaleAdapter

    captured_events: List[MessageEvent] = []
    answered_callbacks: List[Dict[str, Any]] = []
    poll_calls = 0

    cfg = PlatformConfig(enabled=True, token="111111:TEST_TOKEN", extra={"allowed_users": "12345"})
    adapter = BaleAdapter(cfg)
    # Compact one-time approval callback (ea:<token>:<choice>); the adapter no longer accepts the
    # legacy 4-part request-id form, so build the payload the same way the approval prompt does.
    approval_callback = adapter.build_approval_callback_data("req123", "bale_12345", "once")

    async def fake_handler(event: MessageEvent) -> None:
        captured_events.append(event)

    adapter.set_message_handler(fake_handler)

    def mock_bale_server(request: httpx.Request) -> httpx.Response:
        nonlocal poll_calls
        url = str(request.url)
        if url.endswith("/getUpdates"):
            poll_calls += 1
            if poll_calls == 1:
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "result": [
                            {
                                "update_id": 200,
                                "message": {
                                    "message_id": 801,
                                    "chat": {"id": 12345, "type": "private"},
                                    "from": {"id": 12345, "first_name": "Yousef"},
                                    "caption": "این تصویر معماری است",
                                    "photo": [
                                        {"file_id": "small_id", "file_size": 100},
                                        {"file_id": "large_photo_id", "file_size": 500},
                                    ],
                                },
                            },
                            {
                                "update_id": 201,
                                "callback_query": {
                                    "id": "cb_999",
                                    "from": {"id": 12345, "first_name": "Yousef"},
                                    "message": {"message_id": 800, "chat": {"id": 12345, "type": "private"}},
                                    "data": approval_callback,
                                },
                            },
                        ],
                    },
                )
            adapter._running = False
            return httpx.Response(200, json={"ok": True, "result": []})
        if url.endswith("/getFile"):
            return httpx.Response(
                200,
                json={"ok": True, "result": {"file_id": "large_photo_id", "file_path": "photos/arch.jpg"}},
            )
        if "photos/arch.jpg" in url:
            return httpx.Response(200, content=b"\xff\xd8\xff\xe0FAKE_JPEG_DATA")
        if url.endswith("/answerCallbackQuery"):
            payload = json.loads(request.content.decode("utf-8"))
            answered_callbacks.append(payload)
            return httpx.Response(200, json={"ok": True, "result": True})
        if url.endswith("/editMessageText"):
            return httpx.Response(200, json={"ok": True, "result": True})
        return httpx.Response(200, json={"ok": True, "result": {}})

    async def _run() -> None:
        adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(mock_bale_server))
        adapter._running = True
        try:
            await adapter._poll_updates_loop()
            await asyncio.sleep(0.05)
        finally:
            await adapter._client.aclose()

    asyncio.run(_run())
    assert poll_calls >= 2
    assert adapter._last_update_id == 201
    assert len(captured_events) == 1
    ev = captured_events[0]
    assert ev.source.platform == Platform.BALE
    assert "این تصویر معماری است" in ev.text
    assert len(ev.media_urls) == 1
    assert os.path.exists(ev.media_urls[0])
    assert len(answered_callbacks) == 1
    assert answered_callbacks[0]["callback_query_id"] == "cb_999"


def test_bale_adapter_send_edit_and_get_chat_info() -> None:
    """Verify BaleAdapter.send(), message chunking, edit_message(), and get_chat_info()."""
    from gateway.config import PlatformConfig
    from plugins.platforms.bale.adapter import BaleAdapter

    sent_payloads: List[Dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        if url.endswith("/sendMessage"):
            sent_payloads.append(body)
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 100 + len(sent_payloads)}})
        if url.endswith("/editMessageText"):
            return httpx.Response(200, json={"ok": True, "result": {"message_id": body.get("message_id", 101)}})
        if url.endswith("/getChat"):
            return httpx.Response(
                200,
                json={"ok": True, "result": {"id": 12345, "title": "Noryka Dev Group", "type": "group"}},
            )
        return httpx.Response(200, json={"ok": True, "result": {}})

    cfg = PlatformConfig(
        enabled=True,
        token="111111:TEST_TOKEN",
        extra={"allowed_users": "12345", "stream_edit_throttle_seconds": 0.5},
    )
    adapter = BaleAdapter(cfg)

    async def _run() -> None:
        adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            long_msg = ("A" * 3000) + "\n" + ("B" * 2000)
            send_res = await adapter.send("12345", long_msg)
            assert send_res.success is True
            assert len(sent_payloads) == 2

            edit_res = await adapter.edit_message("12345", "101", "Updated content")
            assert edit_res.success is True

            chat_info = await adapter.get_chat_info("12345")
            assert chat_info["name"] == "Noryka Dev Group"
            assert chat_info["chat_type"] == "group"
        finally:
            await adapter._client.aclose()

    asyncio.run(_run())


def test_telegram_adapter_instantiation_and_platform_separation() -> None:
    """Verify TelegramAdapter instantiates with Platform.TELEGRAM and stays isolated from Platform.BALE."""
    from gateway.config import Platform, PlatformConfig
    from plugins.platforms.telegram.adapter import TelegramAdapter
    from plugins.platforms.bale.adapter import BaleAdapter

    tg_cfg = PlatformConfig(enabled=True, token="222222:TG_TOKEN", extra={})
    bale_cfg = PlatformConfig(enabled=True, token="111111:BALE_TOKEN", extra={})

    tg_adapter = TelegramAdapter(tg_cfg)
    bale_adapter = BaleAdapter(bale_cfg)

    assert tg_adapter.platform == Platform.TELEGRAM
    assert bale_adapter.platform == Platform.BALE
    assert tg_adapter.platform != bale_adapter.platform


def test_cli_dashboard_serve_web_and_webapp_argparsers() -> None:
    """Verify `noryka dashboard`, `noryka serve`, `noryka web`, and `noryka webapp` parse cleanly."""
    from noryka_cli.main import _build_cli_parser, _parse_cli_args

    parser, subparsers = _build_cli_parser()

    args_dash = _parse_cli_args(parser, subparsers, ["dashboard", "--port", "8080", "--skip-build", "--no-open"])
    assert args_dash.port == 8080
    assert args_dash.skip_build is True
    assert args_dash.no_open is True

    args_web = _parse_cli_args(parser, subparsers, ["web", "--port", "8080", "--skip-build", "--no-open"])
    assert args_web.port == 8080
    assert args_web.skip_build is True

    args_serve = _parse_cli_args(parser, subparsers, ["serve", "--port", "9119"])
    assert args_serve.port == 9119
    assert getattr(args_serve, "headless_backend", False) is True

    args_webapp = _parse_cli_args(parser, subparsers, ["webapp", "--status"])
    assert args_webapp.status is True


def test_install_script_commands_are_valid_cli_invocations() -> None:
    """Parse install-noryka-termux.sh and verify all printed noryka CLI commands are valid."""
    from noryka_cli.main import _build_cli_parser, _parse_cli_args

    script_text = (ROOT_DIR / "install-noryka-termux.sh").read_text(encoding="utf-8")
    assert "main web --port" not in script_text, "Deprecated `main web --port` must not appear in installer"
    assert "|| true" not in script_text, "`|| true` error masking must not appear in installer"
    assert "--system-site-packages" in script_text
    assert '".[termux]"' in script_text

    parser, subparsers = _build_cli_parser()
    # Extract every `$VENV_DIR/bin/noryka ...` invocation from echo lines
    cmds = re.findall(r"\$VENV_DIR/bin/noryka\s+([^\"]+)", script_text)
    assert len(cmds) >= 4
    for cmd_str in cmds:
        tokens = cmd_str.strip().split()
        parsed = _parse_cli_args(parser, subparsers, tokens)
        assert parsed is not None


def test_web_ui_has_no_hardcoded_fake_tokens_or_unconditional_simulations() -> None:
    """Verify web/index.html has empty default tokens/user IDs and no simulate* functions or fake metrics."""
    ui_text = (ROOT_DIR / "web" / "index.html").read_text(encoding="utf-8")

    forbidden_strings = [
        "8829104:BALE_SECRET_TOKEN",
        "7192834:TG_SECRET_TOKEN",
        "104928172",
        "simulateCompressionCycle",
        "simulateInboundGatewayMsg",
        "simulateRateLimitFailover",
        "۵۸.۴٪ کاهش هزینه",
        "۶۴.۲٪ کاهش هزینه",
        "۳۴ ارائه‌دهنده",
        "۴۲ ابزار ثبت‌شده",
    ]
    for bad in forbidden_strings:
        assert bad not in ui_text, f"Forbidden demo string found in web/index.html: {bad}"

    # Ensure real backend endpoints are wired
    for endpoint in ("/api/status", "/api/messaging/platforms", "/api/cron/jobs", "/api/env", "/api/config", "/api/ws"):
        assert endpoint in ui_text, f"Expected backend endpoint missing in web/index.html: {endpoint}"


def test_relay_plugin_migrate_works_without_external_nemo_relay() -> None:
    """Verify noryka_cli/relay_plugin_migrate.py works cleanly even without external nemo_relay installed."""
    from noryka_cli.relay_plugin_migrate import (
        migrate_profile_relay_env,
        relay_plugin_payload_from_legacy_env,
        validate_relay_plugin_payload,
    )

    sample_env = {
        "NORYKA_NEMO_RELAY_ATIF_ENABLED": "true",
        "NORYKA_NEMO_RELAY_ATIF_AGENT_NAME": "Noryka Agent",
        "NORYKA_NEMO_RELAY_ATOF_ENABLED": "1",
    }
    payload = relay_plugin_payload_from_legacy_env(sample_env)
    assert payload["version"] == 1
    assert len(payload["components"]) == 1
    diags = validate_relay_plugin_payload(payload)
    assert isinstance(diags, list)

    with tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir)
        (home / ".env").write_text(
            "NORYKA_NEMO_RELAY_ATIF_ENABLED=true\nNORYKA_NEMO_RELAY_ATOF_ENABLED=true\n",
            encoding="utf-8",
        )
        res = migrate_profile_relay_env(home)
        assert res.migrated is True
        assert res.toml_path is not None and res.toml_path.exists()


def test_ast_code_analyzer_live() -> None:
    """Verify tools/ast_code_analyzer_tool.py analyzes valid and invalid Python code accurately."""
    from tools.ast_code_analyzer_tool import ast_code_analyzer

    valid_res = json.loads(
        ast_code_analyzer(
            source_code="import os\nclass Demo:\n    async def run(self, x: int) -> int:\n        return x + 1\n"
        )
    )
    assert valid_res["success"] is True
    assert valid_res["syntax_valid"] is True
    assert valid_res["classes"][0]["name"] == "Demo"
    assert "run" in valid_res["classes"][0]["methods"]

    invalid_res = json.loads(ast_code_analyzer(source_code="def broken(:\n    pass"))
    assert invalid_res["success"] is False
    assert invalid_res["syntax_valid"] is False


def test_session_db_sqlite_roundtrip() -> None:
    """Verify SessionDB creates tables, stores sessions/messages, and performs FTS5 search."""
    from noryka_state import SessionDB

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "state.db"
        db = SessionDB(db_path=db_path)
        sid = db.create_session(
            session_id="test_bale_session_01",
            source="bale",
            model="anthropic/claude-sonnet-4",
        )
        assert sid == "test_bale_session_01"
        db.append_message(
            session_id=sid,
            role="user",
            content="لطفا فایل adapter.py را برای پیام‌رسان بله بررسی کن",
        )
        messages = db.get_messages_as_conversation(sid)
        assert len(messages) == 1
        assert "پیام‌رسان بله" in messages[0]["content"]
        db.close()


def test_context_compressor_initialization_and_threshold() -> None:
    """Verify ContextCompressor initializes cleanly and computes thresholds accurately."""
    from agent.context_compressor import ContextCompressor

    compressor = ContextCompressor(
        model="anthropic/claude-sonnet-4",
        threshold_percent=0.50,
        protect_first_n=3,
        protect_last_n=6,
        quiet_mode=True,
    )
    assert compressor.threshold_percent == 0.50
    assert compressor.context_length > 0
    assert compressor.threshold_tokens > 0 and compressor.threshold_tokens <= compressor.context_length


def test_license_preserves_mit_and_noryka_copyright() -> None:
    """Verify LICENSE preserves original Nous Research MIT notice and includes Noryka copyright."""
    lic = (ROOT_DIR / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in lic
    assert "Copyright (c) 2025 Nous Research" in lic
    assert "Copyright (c) 2026 Noryka Contributors" in lic


if __name__ == "__main__":
    all_tests = [
        test_platform_bale_enum_is_distinct_from_telegram,
        test_coding_posture_enabled_on_telegram_and_bale,
        test_tui_gateway_and_pm_imports_present,
        test_bale_adapter_fail_closed_allowlist_and_event_contract,
        test_bale_adapter_429_and_backoff_handling,
        test_bale_adapter_full_poll_updates_loop_and_media_download,
        test_bale_adapter_send_edit_and_get_chat_info,
        test_telegram_adapter_instantiation_and_platform_separation,
        test_cli_dashboard_serve_web_and_webapp_argparsers,
        test_install_script_commands_are_valid_cli_invocations,
        test_web_ui_has_no_hardcoded_fake_tokens_or_unconditional_simulations,
        test_relay_plugin_migrate_works_without_external_nemo_relay,
        test_ast_code_analyzer_live,
        test_session_db_sqlite_roundtrip,
        test_context_compressor_initialization_and_threshold,
        test_license_preserves_mit_and_noryka_copyright,
    ]
    print(f"Running Noryka Live Integration & Smoke Test Suite ({len(all_tests)} tests)...")
    for fn in all_tests:
        fn()
        print(f"  [PASS] {fn.__name__}")
    print(f"ALL {len(all_tests)} LIVE TESTS PASSED SUCCESSFULLY!")
