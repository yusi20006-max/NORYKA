# Hermes Runtime Integration Contract — Technical Audit (Issue #3)

**Status:** Completed audit; integration pin accepted
**Hermes pinned commit:** `5057eaa3a4d0cbef0e30078418a5115faa62889e`
**Audit method:** Direct source inspection of `NousResearch/hermes-agent` checked out at the pinned SHA (shallow fetch of that exact commit; local `git log` printed the SHA and its commit date `2026-10-29T14:00:36Z` / "fix(config): the provider-env completion hook reads the process-wide source record"). Every claim below references real files, classes, and functions read from that checkout. Nothing is inferred from examples without reading the implementation.
**Audit date:** 2026-10-30
**Scope guard:** No runtime code was copied or integrated in this audit. No OpenClaw/OMGA runtimes considered. Only this file plus status notes were added to NORYKA.

---

## 1. Exact pin and license

- Pinned source: `github.com/NousResearch/hermes-agent` at `5057eaa3a4d0cbef0e30078418a5115faa62889e`.
- License: **MIT** (`LICENSE`, "Copyright (c) 2025 Nous Research"; also declared in `pyproject.toml` line 17: `license = "MIT"`). MIT permits adaptation inside NORYKA with license attribution preserved.
- Upstream parity caveat (recorded, blocking Issue #4 parity): the pinned commit is dated **2026-10-29**, newer than the newest published GitHub release tag (`v2026.9.24` = `f97608f`). Release channels (tagged APT `hermes-stable`, GitHub releases) therefore cannot serve this exact SHA today; only the upstream repository working tree contains `5057eaa`.

## 2. Upstream repository shape

Hermes is a large Python codebase with explicit "facade + siblings" layout (documented in upstream `AGENTS.md`: public entry points live in facade modules; `AGENTS.md` line 116 states internal paths are **not API** and get no re-export shims). Key facades:

| Facade | Role |
| --- | --- |
| `run_agent.py` | `AIAgent` — the runtime object (conversation loop, tool execution, session lifecycle) |
| `cli.py` | Interactive CLI (`HermesCLI`) |
| `hermes_state.py` | `SessionDB` — SQLite session storage |
| `gateway/run.py` | Messaging platform gateway (`start_gateway()`, `GatewayRunner`) |
| `acp_adapter/` | Agent Client Protocol JSON-RPC adapter (stdio) |

Console entry points (`pyproject.toml` lines 586–589, verified):

```toml
[project.scripts]
hermes = "hermes_cli.main:main"
hermes-agent = "agent.legacy_cli:main"
hermes-acp = "acp_adapter.entry:main"
```

## 3. Runtime creation and lifecycle

- The runtime object is `class AIAgent(...)` at `run_agent.py:214`, composed of mixins (`ClientLifecycleMixin`, `StreamDeliveryMixin`, `InterruptControlMixin`, `SessionPersistenceMixin`, `TurnFacadeMixin`, …). Its module docstring shows the intended embedding shape:
  ```python
  from run_agent import AIAgent
  agent = AIAgent(base_url="http://localhost:30000/v1", model="claude-opus-4-20250514")
  response = agent.run_conversation("Tell me about the latest Python updates")
  ```
- `AIAgent.__init__` (run_agent.py:236) is a pure forwarder into `agent/agent_init.py:init_agent(agent, **kwargs)` (line 2107), which applies parameter lists from `agent/agent_init_params.py` (`_PASSTHROUGH_PARAMS`, `_GATEWAY_IDENTITY_PARAMS` incl. `user_id`/`chat_id`/`gateway_session_key`, `stream_delta_callback` etc.) and then runs ordered phases: `_set_defaults` (`_CONTROL_STATE`, `_STREAM_STATE`), `_setup_logging`, `_init_turn_state`, `_build_client` (with per-mode builders `_init_openai_client`/`_init_anthropic_client`/`_init_bedrock_client` at lines 907/658/724), `_init_fallback_chain`, `_load_tools` (line 1011), `_init_session_state` (line 1096).
- `_init_session_state` assigns `agent.session_id` (or generates via `new_session_id(session_start)`) and sets `agent.logs_dir = get_hermes_home() / "sessions"`.
- Important consequences for NORYKA:
  - Runtime construction is **in-process and synchronous**; there is no daemon the NORYKA adapter must discover — embedding means importing the facade and instantiating `AIAgent`.
  - `import hermes_bootstrap` must come before other imports in embedded usage (module docstring of `hermes_bootstrap.py`: "Import this module first in every entry point"). On non-Windows platforms its import-time work is a no-op plus `harden_import_path`.

## 4. Message send / response (verified call chain)

1. Turn entry: `AIAgent.run_conversation(user_message)` → `agent/turn_facade.py:run_conversation` (line 22, acquires a durable cross-process turn lease) → `agent/conversation_loop.py:run_conversation(agent, user_message, ...)` (line 1789) → `_run_conversation_turn(...)` → `export_current_turn_boundary(agent, result, user_message)`.
2. API kwargs assembly: `build_api_kwargs(agent, api_messages, tools_for_api)` — `agent/chat_completion_helpers.py:1503` (per-mode builders `_build_anthropic_kwargs`, `_build_bedrock_kwargs`, `_build_codex_kwargs`, `_build_chat_completions_kwargs`).
3. Dispatch: `perform_api_call(agent, *, api_kwargs, ...)` — `agent/turn_api_call.py:72`; streaming decision via `_should_stream(agent)`; streaming path calls `agent._interruptible_streaming_api_call(...)`, non-streaming calls `relay_llm.execute(next_api_kwargs, agent._interruptible_api_call, ...)`.
4. Non-streaming receive: `interruptible_api_call(agent, api_kwargs)` — chat_completion_helpers.py:1260 ("Run the API call on a worker thread so the caller can detect interrupts") → `agent/chat_completion_nonstream.py: _NonStreamRequest(...).run()`.
5. Streaming receive: `interruptible_streaming_api_call(agent, api_kwargs, *, on_first_delta=None)` (line 3977) — returns a `SimpleNamespace` in the non-streaming response shape; final assembly `_finish_chat_stream(...)` (line 3348).
6. Assistant message materialization: `build_assistant_message(agent, assistant_message, finish_reason)` (line 1638).

Result: NORYKA does **not** implement any provider call, retry, or response normalization — all of that is upstream `interruptible_api_call` / `interruptible_streaming_api_call` plus `agent/transports/` (registry of `anthropic`, `codex`, `chat_completions`, `bedrock` transports).

## 5. Streaming

- State class: `_StreamingCall(StreamingWaitMonitor)` (`chat_completion_helpers.py:2699`) — shared worker/monitor state (heartbeat, stale kill, interrupt abort). Bedrock variant `_BedrockStream` (line 2530).
- Chunk loop (lines 3104–3208) emits:
  - text deltas via `self._emit_text(delta_content)` → `AIAgent._fire_stream_delta(text)` (`agent/stream_delivery.py:332`) → `agent.stream_delta_callback(text)`;
  - reasoning deltas (`delta.reasoning_content`/`delta.reasoning`/`delta.reasoning_details`) → `agent.reasoning_callback`;
  - incremental tool calls (`delta.tool_calls` fed into a tool-call accumulator, `tool_calls.feed(tc_delta)`; `_emit_tool_started(name)`;
  - usage frames (`stream_options={"include_usage": True}` at line 2947; choice-less frames via `_choiceless_chunk`, line 2919).
- NORYKA integration: receive deltas through the constructor-provided `stream_delta_callback` (and optional `thinking_callback`, `tool_gen_callback`); no custom stream parsing needed.
- Runaway detection exists (`agent/repetition_guard.py: RunawayStreamWatch`); partial-response stubs are built on mid-stream errors (`_build_partial_stream_stub`, line 2357).

## 6. Cancellation

- The core turn loop is **synchronous with worker threads**; there is **no `asyncio` agent loop** in `run_agent.py` / `agent/conversation_loop.py` / `chat_completion_helpers.py` (no `CancelledError` handling there). Cancellation is flag/event-based:
  - `AIAgent.interrupt(message=None, *, hard_cancel=False, tool_reason=None, require_generation=None)` — `agent/interrupt_control.py:163` ("Request the agent to interrupt its current tool-calling loop (call from another thread)"), sets `agent._interrupt_requested = True`. Reason taxonomy includes `_REASON_GATEWAY_SHUTDOWN`.
  - Reason taxonomy in the same file: `_REASON_HARD_STOP = "explicit stop requested"`, `_REASON_NEW_MESSAGE` (user sent a new message), `_REASON_USER_INTERRUPT = "user interrupt"`, `_REASON_GATEWAY_SHUTDOWN = "gateway shutdown"`.
  - Explicit hard-stop wrapper: `agent/interrupt_compat.py: request_hard_interrupt(agent, message=None, ...)`.
  - In-flight calls check the flag and raise `InterruptedError("Agent interrupted during streaming API call")` (line 3955); requests carry `Interrupt-control state` `self._request_cancelled` (`chat_completion_helpers.py` streaming monitor class `_StreamingCall`).
  - Tool-thread interrupts: `tools/interrupt.py: set_interrupt(active, thread_id=None, *, reason=None)` / `is_interrupted()` — thread-scoped so one session's interrupt does not kill other sessions' tools.
- NORYKA adapter maps its own "cancel conversation" events onto `agent.interrupt(...)`/`request_hard_interrupt(agent)` from the controlling thread; no direct thread killing.

## 7. Shutdown and resource release

Per-agent teardown on `AIAgent` (run_agent.py:867–1010):

- `release_clients(self)` (921) — light teardown (client retirement, `_memory_manager.release_soft`).
- `close(self)` (938) — full idempotent teardown; every step wrapped in `_quietly(...)` ("Run one teardown step, swallowing any exception"): memory provider shutdown → `_close_task_resources(session_id)` → `_close_active_children(soft=False)` → drop shared OpenAI client → `_close_request_clients("agent_close")` → `_close_codex_session` → clear `agent._session_messages` → `_finalize_owned_session_row`.
- HTTP client lifecycle lives in `agent/client_lifecycle.py:ClientLifecycleMixin` (`_close_openai_client`, `_retire_shared_openai_client` — cross-thread-safe retirement of pooled sockets, `_drain_transports_after_abandonment`).
- Process-level: `cli.py:_run_cleanup()` (line 471, "Run resource cleanup exactly once", atexit-registered) and `_arm_exit_watchdog`; first source-shape `hermes_bootstrap.py` exists for entry points.
- Session DB: shared-process acquisition registry `hermes_state_registry.py` — `acquire(db_path=None) -> SessionDB` (195), `release(db) -> bool` (276), `close_all() -> int` (346), `release_or_close(db) -> None` (474); WAL checkpointing every `_CHECKPOINT_EVERY_N_WRITES = 50` writes (`hermes_state.py:464`).

NORYKA adapter contract: call `agent.close()` after each agent instance ends; keep long-lived instances scoped per conversation; never call `os._exit`-style upstream shortcuts (`hermes_cli/oneshot.py` uses `os._exit` — that path is NOT for embedding).

## 8. Session and memory

- Canonical store: **SQLite, WAL, one writer / many pooled readers** — `hermes_state.py: class SessionDB(...)` (line 464), docstring "SQLite-backed session storage with FTS5 search; many reader threads, one writer (WAL)". Default DB path: `hermes_state.py:181` `DEFAULT_DB_PATH = get_hermes_home() / "state.db"` → `~/.hermes/state.db` (`get_hermes_home()` in `hermes_constants.py:64`; override via `HERMES_HOME` env). Degraded JSONL fallback exists (`divert_session_transcript_jsonl`, hermes_state.py:434) but SQLite is canonical.
- Main session API (verified signatures):
  - `hermes_state_sessions.py:416 create_session(self, session_id, source, **kwargs) -> str` (upsert); plus `ensure_session(...)` and `find_session_by_origin(*, platform, chat_id, thread_id=None, user_id=None)`.
  - `hermes_state_messages.py:396 append_message(self, session_id, role, content=None, tool_name=None, tool_calls=None, tool_call_id=None, token_count=None, finish_reason=None, reasoning=None, ..., message_uid=None) -> int`.
  - `hermes_state_messages.py:430 append_messages_batch(...)` (single write txn).
  - `hermes_state_messages.py:1363 get_messages(self, session_id, include_inactive=False, include_compacted=False, limit=None, offset=0, latest=False, after_id=None, include_ancestors=False) -> list[dict]` (+ `get_messages_around`, `get_messages_as_conversation`, and `hermes_state_timeline.py: get_session_timeline`).
- Agent-side persistence (`agent/session_persistence.py`): `_persist_session(messages, conversation_history=None)` ("Save to SQLite on any exit path"), dedup via per-message intrinsic marker; row created on first use by `AIAgent._ensure_db_session()` (run_agent.py:315) which acquires from `hermes_state_registry.acquire()`; `_persist_disabled` fence exists for persistence-isolated agents.
- Memory: built-in `MemoryStore` (`tools/memory_tool.py`) on `agent._memory_store`; external providers via `agent/memory_manager.py`; provider resolution `agent/agent_init_memory_provider.py: resolve_memory_provider(name, say=None)` (line 50) loads from `plugins/memory`; provider protocol in `agent/memory_provider.py` (`initialize`, `prefetch`, `sync_turn`, `shutdown`, `on_session_end`, `on_memory_write`, ...), wired in `_init_memory` (agent_init.py:1270–1278).
- Consequence for NORYKA: conversation persistence and compaction are owned by Hermes. NORYKA must NOT maintain a second conversation table; it maps provider/channel identity (e.g. Telegram chat_id) onto Hermes sessions via `find_session_by_origin` semantics and passes a `session_db`/`session_id` into `AIAgent`.

## 9. Providers and credential management

- Per-provider plugins: `providers/` contains only the registry (`providers/__init__.py`, `providers/base.py: ProviderProfile` dataclass); 39 bundled provider plugin dirs under `plugins/model-providers/<name>/` (verified by listing: `anthropic`, `openai-codex`, `ollama-cloud`, `lmstudio`, `openrouter`, `gemini`, `zai`, `deepseek`, `bedrock`, `vertex`, `nous`, ...). Registry public functions (verified): `register_provider(profile)` (providers/__init__.py:140), `get_provider_profile(name) -> ProviderProfile | None` (218), `list_providers()` (361), `bundled_profiles()` (829), `profile_for_host(url, ...)`, `unlisted_provider_names()`. Discovery sources: bundled plugins, `$HERMES_HOME/plugins/model-providers/`, and pip entry-point group `hermes_agent.plugins`.
- Provider *selection* lives in `hermes_cli/auth.py`: `PROVIDER_REGISTRY: dict[str, ProviderConfig]` (line 242) and `resolve_provider(requested=None, *, explicit_api_key=None, explicit_base_url=None, skip_free_tier=False)` (line 1609) with priority chain: CLI api_key/base_url → `config.yaml model.provider` → OpenRouter env → provider env keys → `auth.json active_provider` → Nous free tier → Bedrock chain → `AuthError(no_provider_configured)`.
- Auxiliary/programmatic client routing: `agent/auxiliary_client.py: resolve_provider_client(provider, model=None, async_mode=False, ..., explicit_base_url=None, explicit_api_key=None, api_mode=None, ...)` (line 5371) — supports `"auto"`, `"custom"` (`OPENAI_BASE_URL`+`OPENAI_API_KEY`), `custom:<name>`, api modes `codex_responses`/`chat_completions`/`anthropic_messages`.
- Credential locations (all outside Git):
  - Environment variables per provider, e.g. `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `ZAI_API_KEY` (`ProviderConfig.api_key_env_vars`).
  - `$HERMES_HOME/.env` — secrets only; upstream `.gitignore` ignores `.env`/`.env.local`.
  - `$HERMES_HOME/auth.json` — written via `atomic_json_write(target, data, mode=0o600, ...)` with parent tightened to `0o700` (hermes_cli/auth.py:776–784).
  - Extensible secret sources: `agent/secret_sources/{base,registry,onepassword,bitwarden,command}.py` with `register_source()`/`apply_all()`; the **`command` source** runs a user-configured helper that prints `KEY=VALUE` lines — the designated seam for a host app (NORYKA) to inject secrets from its own credential store.
- **No NORYKA-specific hook exists upstream** (grep for "NORYKA"/"noryka" across the tree: zero hits — verified). NORYKA injects credentials via env vars, `$HERMES_HOME`, or the `command` secret source; it must not write Hermes credential files into the Git repository (`Requirement 6`).
- **No `BACKEND` constant exists** (verified — the only "backend" concepts are `FailureScope`/`BackendIdentity` in `agent/backend_identity.py` for failover classification, and terminal backends).

## 10. Configuration

- Format/paths: YAML at `get_config_path()` → `get_hermes_home() / "config.yaml"` (`hermes_cli/config.py:433–435`); template `cli-config.yaml.example` (`_config_version: 52`); missing config is created by copying the template (`hermes_cli/config.py:512–517`).
- Loader: `load_config()` (hermes_cli/config.py:1978) — "Load the merged configuration (DEFAULT_CONFIG + config.yaml + managed scope, env-expanded). Cached on the file signature; returns a deepcopy". Also `save_config`, `atomic_config_replace()`, `read_raw_config()`, `--ignore-user-config` / `HERMES_IGNORE_USER_CONFIG=1` override.
- NORYKA adapter should treat `config.yaml` as user-owned runtime configuration (never committed) and may pin behavior via constructor kwargs on `AIAgent` instead.

## 11. Public vs internal API boundary

Public/supportable surfaces (verified):

1. Console entry points `hermes`, `hermes-agent`, `hermes-acp` (pyproject `[project.scripts]`).
2. Facade import surfaces: `run_agent.py` (`AIAgent`, embedding shape documented in its module docstring), `hermes_state.py` (`SessionDB` + session/message functions), `gateway/run.py` (`start_gateway()` / `GatewayRunner`).
3. ACP adapter (`acp_adapter/entry.py`): stdio JSON-RPC Agent Client Protocol; `stdout` reserved for JSON-RPC; designed for external editors/driver programs.
4. Gateway integrations: `gateway/platforms/api_server.py` — OpenAI-compatible HTTP surface at `http://localhost:8642/v1` (`/v1/chat/completions`, `/v1/responses`, `/v1/models`, `/health`; `DEFAULT_PORT = 8642`, auth via `API_SERVER_KEY`); local control socket `gateway/control_socket.py` (versioned JSON verbs `identify`/`status` over `$HERMES_HOME/gateway.sock`, `CONTROL_PROTOCOL_VERSION = 1`; never TCP).
5. Plugin extension contracts: `$HERMES_HOME/plugins/...` and the `hermes_agent.plugins` entry-point group; provider profile contract in `providers/README.md`.

Explicitly internal (do not consume from NORYKA): `agent/*` module internals under facades are **not API** (AGENTS.md: "No re-export shims for internal moves; internal paths are not API"); no documented "as a library" README API exists beyond the `AIAgent` facade docstring — the embedding contract therefore should be tracked against upstream changes at pin-bump time (test-based contract verification, per Issue #11 direction).

## 12. Dependencies and packaging policy

- `pyproject.toml`: `requires-python = ">=3.11,<3.15"`; comment states "we *only* support 3.14"; nearly every core dependency is exact-pinned `==X.Y.Z; python_version >= '3.14'` (supply-chain rationale in-tree: pins tightened 2026-05-12 after the Mini Shai-Hulud worm; "Do not introduce ranges without a written justification"). Sanctioned ranges: `urllib3>=2.8.0,<3`; `uvicorn>=0.31.0,<1`. Lockfile: `uv.lock` (1.2 MB); runtime dependency management via the bundled `pm/` package (`hermes pm lock`).
- **`pip` wheel/sdist builds are deliberately blocked** — `setup.py` line 34 `_IN_NIX_BUILD = os.environ.get("HERMES_NIX_BUILD") == "1"` and `_BLOCK_MESSAGE` ("Building wheels or sdists for hermes-agent is not supported. Hermes is distributed via the shell installer, Docker image, or Nix."); guards fire for `pip wheel`, `uv build`, `python -m build`, and direct `setup.py`.
- Android/Termux packaging is CI-built, not built on device: `scripts/termux/build_config.sh` pins `PLATFORM_TAG="android_24_arm64_v8a"`, `PYTHON_ABI="cp314"` ("Pure-python installs only: maturin is deliberately absent"). `pm/lock.json` resolves Termux CPython to the Termux apt package (`python_3.14.6-1_aarch64.deb`, i.e. **bionic CPython 3.14**, not Termux's own 3.13).
- Android-specific dependency guards (verified in pyproject): `psutil==7.2.2; sys_platform != 'android'` plus a git-pinned psutil for `sys_platform == 'android'`; `nemo-relay` excluded on Android (`platform_release`-based guard + comment about Android GKI kernel strings); `uvloop`, TTS extras, `playwright` excluded via `sys_platform != 'android'`.
- License obligations for NORYKA: keep MIT license attribution when shipping/adapting Hermes-derived code; no copyleft obligations.

## 13. Android / Termux constraints (verified)

- Termux detection: `hermes_platform/host/runtime.py:8–11` `is_termux()` → `TERMUX_VERSION` env or `com.termux/files/usr` prefix; `hermes_cli/main.py:917–923` similar cold-start check accepting `/data/data/com.termux/` prefixes. Official pyproject/PEP-738 note: on this target CPython 3.14 reports `sys.platform == "android"` (termux docs line ~140–157; pyproject markers above).
- **Official install path:** signed aarch64 APT repository — `website/docs/getting-started/termux.md` lines 15–22: channels at `https://hermes-assets.nousresearch.com/releases/termux/<channel>` with suites `hermes-stable` (tagged `vMAJOR.MINOR.PATCH`) and `hermes-canary`; repository signing key fingerprint `C572 B5FD D1A2 9CCF A9A9 12B6 840B 0848 E139 156D`; install via `pkg install curl gnupg`, key at `$PREFIX/etc/apt/keyrings/hermes-agent.asc`, then `pkg install hermes-agent`. Package bundles Python 3.14 (bionic interpreter pin), Node.js, npm, uv, ripgrep, ffmpeg and the TUI.
- **Upstream-declared current breakage (critical for #3/#4):** the same `termux.md` carries a danger banner, lines 9–13: *"Termux is currently broken. The Termux package does not work right now. A fix is in progress and will ship soon. Until then, the steps below may fail or install a package that does not run."* Any Termux acceptance testing (Issue #4) is therefore gated until upstream ships the fix; NORYKA must not work around it (constraint: "Do not modify upstream installation scripts to hide failures").
- `scripts/install.sh:437–440` *refuses* to run under Termux (`HERMES_INSTALL_PATH` style check `TERMUX_VERSION` → fail "unsupported_platform" with message that Termux installs come from the APT repository, not `install.sh`). Same for glibc archives ("no Android wheels in the lock").
- Standard prefix required: `/data/data/com.termux/files/usr`; other architectures and renamed Termux package variants unsupported; wheels target Android API 24 (`android_24_arm64_v8a`).
- Platform tiering: `website/docs/getting-started/platform-support.md:36` — Termux is **Tier 2** ("maintained in-tree only as a best effort"); non-aarch64 Android listed Unsupported.
- Documented Termux limits (termux.md "Limits"): no `nemo-relay`; no Electron/bundled Chromium/computer-use (browser tool only via system `chromium` on PATH); no local Docker daemon; no Termux:API adapters unless the Termux:API app is installed (`tools/voice_mode.py` probe); background processes may be suspended/killed by Android (`hermes_cli/gateway.py:5537` footnote; gateway must be run manually).
- In-code Termux branches (examples verified): gateway service supervisor map `hermes_cli/gateway_runtime_service.py:255–265` — `"android": _no_supervisor` ("Android/Termux has no service manager"); `hermes_cli/process_identity.py:846–847` — `# Android (Termux) has no /bin/sh` → falls back to `/system/bin/sh`; browser autodownload disabled under Termux (`tools/browser_launcher.py:163–164`); doctor prints "Docker backend is not available inside Termux (expected on Android)" (`hermes_cli/doctor_tools.py:210`); `hermes update` refuses APT-owned Termux installs (`STEWARD_APT_TERMUX`, `hermes_cli/update_contract.py:120–128` plus `hermes_cli/steward.py` message "Source installs are not supported on Termux — `hermes update` would build Python packages on the device").
- **Sandboxing:** normal tool execution uses the `local` subprocess backend (`tools/environments/local.py` — "Local execution environment — spawn-per-call with session snapshot") with child env scrubbing (`tools/code_execution_env.py::_scrub_child_env`). **No OS-level sandbox (no bwrap/proot/firejail/seccomp) wraps it**; bubblewrap exists upstream only as an optional plugin (`plugin-catalog/bubblewrap.yaml`) or in the e2e test harness (`tests/e2e/core/upgrade/_helpers.py`) — none of which is an Android-suitable sandbox. Consequence for NORYKA Requirement 5: on Termux, `local` backend execution has **no OS isolation proof**; until Issue #10's isolation work is proved on Android, tool-enabled agent runs must be restricted to approved workspaces and/or run with tools disabled or in a container-backed backend (`docker`/`modal`/`daytona`/`vercel_sandbox`, set in `tools/terminal_tool_config.py:120`).

## 14. NORYKA adapter surface (what the adapter must own)

Based on the verified contract, the NORYKA-owned adapter (Issue #5) needs exactly:

1. **Process import + embedding** — `import hermes_bootstrap` first, then `from run_agent import AIAgent`; constructor kwargs for `model`, `base_url`/provider selection, `session_db`, `session_id`, streaming callbacks (`stream_delta_callback`, `thinking_callback`, `tool_gen_callback`), and gateway-identity fields (`user_id`, `chat_id`, `gateway_session_key` via `_GATEWAY_IDENTITY_PARAMS`).
2. **Channel identity → Hermes session mapping** — use `hermes_state` (`acquire()`, `ensure_session`/`find_session_by_origin`) instead of a second conversation store.
3. **Turn execution & rendering** — call `agent.run_conversation(user_message)` per turn (or low-level `perform_api_call` path only if the facade proves insufficient; default to facade); render the returned dict to Telegram/Bale/show message formatting — no provider/network code in NORYKA.
4. **Streaming delivery** — implement a `stream_delta_callback` that forwards throttled deltas to the channel adapter; no stream parsing.
5. **Cancellation plumbing** — map "stop generation" to `agent.interrupt(message=...)` / `request_hard_interrupt(agent)` from the controlling thread; tool-thread interrupts stay upstream via `tools/interrupt.py`.
6. **Shutdown sequencing** — `agent.close()` per instance lifecycle; if using the gateway process model, integrate with `gateway/run.py: start_gateway()` / `GatewayRunner`; never replicate Hermes teardown.
7. **Credential injection** — env vars set by the NORYKA process, `$HERMES_HOME/.env`, `$HERMES_HOME/auth.json`, or `agent/secret_sources` `command` source; verify nothing lands in the repo.
8. **Provider pinning** — provider choice via `resolve_provider` semantics or explicit `--provider`-equivalent kwargs; do not re-implement provider auth.

Reuse vs. own classification (aligned with `docs/NORYKA_CORE_ARCHITECTURE.md` section 2): runtime loop, provider clients, conversation persistence/memory compaction, tool registry = reuse Hermes; channel adapters, identity/authorization, channel message formatting, NORYKA skill/tool registration = NORYKA-owned.

## 15. Pin & upgrade policy

- Pin is the exact SHA `5057eaa3a4d0cbef0e30078418a5115faa62889e`, recorded in this document and `docs/NORYKA_CORE_ARCHITECTURE.md` line 6.
- Integration surface risk: upstream `AGENTS.md` declares facades as the import surface but no formal stable library API contract exists beyond them. NORYKA therefore gates any pin bump on re-running this audit's verification steps (§4 call chain names, §8 signatures, §3 constructor kwargs) against the new commit — treat `agent/agent_init.py`/`agent/agent_init_params.py`/`chat_completion_helpers.py` names as regression-sensitive contract points, checked via import, not vendoring.
- Parity risk (recorded): the pinned SHA is unreleased upstream (newer than `v2026.9.24`); release-channel artifacts (APT stable/canary, Docker, Nix) can only provide *tag-based* parity. Issue #4 must document the version/source mapping and stop before claiming exact-SHA parity unless a channel artifact demonstrably contains this SHA (canary channel is the closest candidate once upstream shipping is fixed).

## 16. Risks (recorded)

1. **Upstream Termux channel currently broken** (termux.md banner) — blocks native install verification (Issue #4) and any Termux acceptance run until upstream ships the fix.
2. **Unreleased pinned SHA** — no published artifact contains it today; testing the pin requires either source checkout (which upstream expressly supports only for development, not end-user distribution) or waiting for a canary/stable release containing an equivalent or later commit and re-basing the pin (requires owner decision; recorded as a decision point, not silently resolved).
3. **No OS-level tool sandbox on Android** — Requirement 5 demands isolated tool execution before allowing general host execution; sandbox plugin options (bubblewrap plugin) are not Android-portable per upstream packaging notes. Mitigation: default terminal backend restrictions until Issue #10 provides proved isolation.
4. **Async model mismatch** — Hermes core loop is synchronous/thread-based while NORYKA channel adapters (Telegram/Bale) will be async; adapters must marshal agent turns onto worker threads and route interrupts explicitly (§6), avoiding shared-state races.
5. **Upstream internal-API churn** — names in §4/§14 live under facades but internal moves happen without shims (AGENTS.md line 116); upgrade checklist (§15) is mandatory on every pin bump.

## Acceptance criteria status

- [x] Exact Hermes commit and license recorded (§1, MIT).
- [x] Runtime lifecycle and supported invocation path documented with source references (§3–§4, §11).
- [x] Dependency/license inventory completed (§12, §9).
- [x] Termux/ARM64-specific dependencies and limitations identified (§13).
- [x] Integration decision and risks recorded (§14–§16); this document completes the in-source memory of Issue #3 acceptance.
