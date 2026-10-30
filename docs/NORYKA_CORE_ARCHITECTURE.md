# NORYKA Core Architecture

**Status:** Accepted baseline for implementation  
**Primary runtime:** Hermes Agent  
**Repository baseline:** `yusi20006-max/NORYKA` at `916ad9440f755c5fe3c6908c614666e8bde29ef6`  
**Hermes source baseline:** `NousResearch/hermes-agent` at `5057eaa3a4d0cbef0e30078418a5115faa62889e`

## 1. Product direction

NORYKA starts as a personal assistant for the owner's daily workflows and is designed to grow into a public Agent platform. The first implementation must optimize for a reliable single-user deployment on Android/Termux without blocking a later multi-user architecture.

Telegram and Bale are first-class channels. Both must use one shared Agent runtime, memory, session model, authorization policy and tool system. NORYKA owns its gateway/channel integration; it must not depend on an external gateway product.

## 2. Source strategy (binding)

1. **Hermes is the only primary Agent runtime.** Reuse/adapt its runtime, provider integration, memory, skills and tool execution boundaries. Do not maintain a second competing Agent loop.
2. **OpenClaw is a selective reference/source.** Adopt a capability only after a concrete gap is demonstrated in Hermes/NORYKA, with source/license/dependency review. Do not import its runtime or gateway wholesale.
3. **OMGA is a narrow specialist source.** Consider only useful terminal-oriented tools or workflows after the same gap and compatibility review. Do not import its Agent runtime.
4. Keep all three runtimes separate at source level; NORYKA's production process executes one Agent runtime: Hermes.
5. Existing YasinCoder/NORYKA project-intelligence and coding-agent capabilities are assets to preserve and adapt as tools/skills. Do not discard repository history or replace the existing product in-place on `master`.

## 3. Logical architecture

```text
Telegram Adapter ----+
                     |
Bale Adapter --------+--> NORYKA Channel/API Boundary
                     |          |
Future adapters -----+          v
                            Identity & Authorization
                                     |
                            Session / Conversation
                                     |
                            NORYKA Application Services
                                     |
                         Hermes Agent Runtime (single)
                          /          |           \
                   Providers     Memory       Tool/Skill registry
                                                |
                              +-----------------+----------------+
                              |                 |                |
                         NORYKA tools      MCP integrations   optional
                         (coding, files,    (explicit trust     specialist
                          projects, Git)     boundaries)       tools
```

Channel adapters translate platform events into a canonical inbound envelope and translate Agent responses back to the platform. They must not contain business logic, model routing, memory logic or independent Agent loops.

## 4. Core contracts

### Channel envelope
Every channel maps messages to a normalized event containing: `channel`, `external_user_id`, `conversation_id`, `message_id`, `text/content`, attachment metadata, timestamp and verified platform identity metadata. Raw platform payloads remain adapter-local and are not trusted as authorization claims.

### Identity and authorization
- Resolve each inbound event to a NORYKA principal before creating or resuming a session.
- Initial personal deployment: explicit owner allowlist/pairing; deny unknown senders by default.
- Public-platform phase: tenant-scoped principals, channel account links, roles and quotas. This is a later phase, not a reason to overbuild the first release.
- A platform user ID or session ID alone is not sufficient authorization.
- Channel adapters share one policy service; no per-channel bypass.

### Session and memory
- One canonical NORYKA conversation/session identity is shared across channels only when the same authenticated principal and explicit conversation-link policy permit it.
- Hermes is the primary Agent memory/runtime implementation. Avoid a second independent memory system.
- Existing NORYKA SQLite state store may initially retain product metadata (projects/tasks/channel mappings) while a documented adapter/migration boundary is established. Do not silently dual-write conversational memory.
- Secrets, API keys and raw authentication tokens never enter memory or shared Agent context.

### Tools and approvals
- Existing project/code analysis, file, Git and test features are adapted as NORYKA tools/skills.
- Tools declare required capabilities (read, write, execute, network, git, admin); default is deny for side effects.
- Approval is an authorization workflow, not a sandbox.
- Local terminal execution is a privileged host capability. Untrusted channel/web/MCP content must not reach host execution without process-level isolation and explicit policy.
- MCP servers, Plugins and Skills are independently trusted executable components; review before enabling.

### Provider and model selection
- Hermes owns the Agent's provider/model invocation path.
- NORYKA may expose user-facing configuration and policy, but must not create a second model-routing/fallback loop that competes with Hermes.
- Credentials stay in user-owned secure storage outside the repository and never appear in logs, UI, prompts or Git.

## 5. Runtime and deployment

- Initial target: native Android/Termux ARM64, with Linux compatibility retained.
- Start with one NORYKA application process and one Hermes runtime; channel adapters are modular components.
- Local-only control surfaces by default. Any remote listener requires authentication, origin/network policy and explicit opt-in.
- Durable state, credentials, caches and logs remain outside the Git checkout.
- Public multi-tenant hosting requires OS/process isolation per tenant or an equivalent strong boundary; the single-user local deployment is not a security model for hostile multi-tenant workloads.

## 6. Implementation sequence

### Phase 0 — foundation (current branch)
- Preserve `master` and its existing YasinCoder history.
- Record this architecture and the source-selection ADR.
- Create a dedicated implementation branch and use small reviewable changes.

### Phase 1 — Hermes runtime foundation
- Pin the Hermes source revision and record its license/dependency inventory.
- Establish a reproducible Termux install/run path against the selected revision.
- Integrate the Hermes runtime behind a NORYKA-owned application entry point without duplicating the Agent loop.
- Add a smoke test proving one user message reaches Hermes and returns one response.

### Phase 2 — shared channel and identity layer
- Define canonical inbound/outbound channel contracts.
- Implement Telegram and Bale adapters against the same contract.
- Add owner pairing/allowlist, sender verification, session binding and deny-by-default behavior.
- Verify cross-channel session continuity only for the same authorized principal.

### Phase 3 — NORYKA capabilities
- Adapt existing coding/project/Git/test capabilities into Hermes tools or Skills.
- Map permissions and approval requirements to each tool.
- Add bounded execution and process isolation for privileged tools.

### Phase 4 — reliability and expansion
- Add retries, idempotency, delivery tracking, restart recovery, health/diagnostics and backups.
- Evaluate OpenClaw/OMGA only against documented unmet requirements.
- Design tenant isolation, roles, quotas and public deployment only after the personal-assistant flow is stable.

## 7. Acceptance gates

A phase is not complete because code exists. It requires evidence:
- clean-clone install and dependency resolution on native Termux ARM64;
- Hermes runtime smoke test with a configured provider;
- Telegram and Bale messages use the same runtime/session/policy path;
- unauthorized sender is denied before Agent invocation;
- tool permission and approval tests cover allow and deny paths;
- restart preserves intended durable state without duplicate message execution;
- CI results correspond to the final tested commit.

## 8. Explicit non-goals for the first slice

- No parallel OpenClaw/OMGA runtime.
- No wholesale gateway replacement or external gateway dependency.
- No public multi-tenant release before isolation and authorization are proven.
- No blind copy of source code before license, dependency and platform compatibility review.
- No rewrite of existing NORYKA/YasinCoder coding capabilities before mapping and tests.
