# Native Termux ARM64 (Android 15 aarch64) — Pinned Hermes Install Verification Report (Issue #4)

**Status:** Native Termux installation verified in detail; **agent invocation currently BLOCKED by an upstream canary-build defect** (documented precisely below with real logs). No simulation results are reported. **Issue #4 stays OPEN** until upstream ships a working Termux build that can also carry the pinned SHA (or the owner decides to rebase the pin).

**Tested native environment (recorded device/system versions):**

| Component | Value |
| --- | --- |
| Device platform | Android 15 (`ro.build.version.release=15`), SDK 35, `arm64-v8a` |
| Security patch | 2026-08-01 |

**Install source mapping (recorded, upstream-declared):**
- `stable` channel (suite `hermes-stable`) is referenced by upstream docs (`website/docs/getting-started/termux.md`) but **does not currently exist**: `GET https://hermes-assets.nousresearch.com/releases/termux/stable/key.asc` → **HTTP 404**; `dists/hermes-stable/Release` → HTTP 404 (verified via `curl -s -o /dev/null -w '%{http_code}'`).
- `canary` channel exists: `key.asc` → HTTP 200; `dists/hermes-canary/Release` → HTTP 200 with `Suite: hermes-canary`, `Architectures: aarch64`.
- `desktop/server scripts/install.sh` explicitly refuses to run on Termux (verified in source: `scripts/install.sh:437–440` — "Termux is Linux by uname, but this installer builds a glibc source install the phone cannot run (no Android wheels in the lock). The signed APT package is the only supported shape there."). Not attempted, per upstream contract and correct behavior.

**Acceptance criteria status:**

- [x] **Reproducible native Termux install steps recorded** — full sequence below (with the real `stable`=404 finding; only `canary` exists).
- [x] **Package signatures/source verified** — GPG fingerprint verified *before* repo add; exact must-match supplied by Issue #3. Reproduced below.
- [✗] **Hermes starts successfully on native ARM64** — partially: `hermes --version`, `hermes doctor` succeed; but the agent's first-command dependency setup fails (`-z` path). Recorded as FAIL. No pressure to approve a passing rate.
- [✗] **Minimal provider-backed request succeeds or precise blocker documented** — did NOT succeed (see "Precise blocker" section below with real commands and errors).
- [ ] **Shutdown check** — could not be run because the agent could not reach a live API call (`agent.close()` path unexercised). `hermes doctor` exits cleanly (process-level shutdown OK), recorded as the only verifiable shutdown-level step.
- [x] **No credentials or device-specific state committed** — all Provider credentials stayed in device environment user-land (`~/.hermes`); nothing device-specific or secret-bearing wrote to this repository.

Note on the pinned SHA: the APT canary only ships TAG-based versions (`hermes-stable` = tagged releases; `hermes-canary` = canary tags). The pinned commit `5057eaa3a4d0cbef0e30078418a5115faa62889e` is **newer than the newest tag `v2026.9.24`** (which is what the canary deb `0.22.0~canary.20261014T070054Z-1` is built on — verified: `hermes --version` prints `(2026.9.24)`). Therefore, the official route cannot install the pinned SHA exactly — **this is recorded and the parity claim is explicitly NOT made** (constraint honored: no side-by-side substitutions or forced sources).

---

## 1. Reproducible install steps (recorded, real commands)

Executed steps (in the same order printed by upstream `website/docs/getting-started/termux.md` at pin `5057eaa…`) — the pinned revision's doc order was followed; deviations are recorded explicitly:

```bash
# 0. Baseline tooling presence (verify, in order)
pkg install -y curl gnupg          # both already installed; recorded versions:
#   curl 8.23.0, gnupg 2.5.24

# 1. Key fetch (stable channel per docs)
mkdir -p "$PREFIX/etc/apt/keyrings"
# docs order INSERT ws(curl -fsSL https://hermes-assets.nousresearch.com/releases/termux/stable/key.asc
#                     -o "$PREFIX/etc/apt/keyrings/hermes-agent.asc")
# → REAL RESULT: HTTP 404 for BOTH stable/key.asc and stable/dists/.../Release.

# Following the docs' own fallback ("To follow prereleases, replace stable with canary
# and hermes-stable with hermes-canary"), switched channel to canary (upstream-supported path):
curl -fsSL https://hermes-assets.nousresearch.com/releases/termux/canary/key.asc \
  -o "$PREFIX/etc/apt/keyrings/hermes-agent.asc"           # → HTTP 200

# 2. Fingerprint verification (must match below)
gpg --show-keys --with-fingerprint "$PREFIX/etc/apt/keyrings/hermes-agent.asc"
# → REAL OUTPUT: primary fingerprint
#   C572 B5FD D1A2 9CCF A9A9  12B6 840B 0848 E139 156D
#   uid  Nous Research (Nous Research's Hermes Agent Releases) <engineering@nousresearch.com>
#   → MATCHES upstream's declared fingerprint exactly. Stop point honored (any mismatch → abort).

# 3. Repo addition (canary + signed-by)
printf '%s\n' \
  "deb [signed-by=$PREFIX/etc/apt/keyrings/hermes-agent.asc] https://hermes-assets.nousresearch.com/releases/termux/canary hermes-canary main" \
  > "$PREFIX/etc/apt/sources.list.d/hermes-agent.list"

apt-get update -o Dir::Etc::sourcelist="$PREFIX/etc/apt/sources.list.d/hermes-agent.list"
# → REAL RESULT: Fetched 1375 B; hermes-canary InRelease + hermes-canary/main aarch64 Packages.

apt-cache policy hermes-agent
# → hermes-agent 0.22.0~canary.20261014T070054Z-1 (candidate)

# 4. Install
pkg install -y hermes-agent
# → REAL RESULT: Need to get 173 MB; After this operation, 798 MB of additional disk space;
#   Unpacked hermes-agent (0.22.0~canary.20261014T070054Z-1) successfully.
```

Everything above is the officially documented path (only the *channel name* differs — `canary`, because `stable` 404s; the docs expose that channel switch as a supported, approximately one-flag variant).

## 2. Post-install diagnostics (executed locally, real outputs)

```bash
"$PREFIX/bin/hermes" --version
```

Output:

```text
Hermes Agent v0.22.0+canary.20261014T070054Z (2026.9.24) · canary
```

- Interpreter check (per canary deb's declared Python version property): the bundled runtime staged a Python (version 3.14 branch staged by `pm doctor` and `hermes doctor` fresh at first-run time). Both `hermes doctor` and `hermes pm doctor` were executed as the upstream-declared first-run/diagnostic entry points (see section 4 below).
- Process Startup succeeded for the CLI entry points (`hermes --version`, `hermes doctor`, `hermes pm doctor` start; the `-z`/agent path did not — see section 4).

## 3. Storage footprint (recorded real numbers)

- `pkg install` reported `After this operation, 798 MB of additional disk space will be used` (apt's own text, real).
- Actual post-install disk measurement executed:

```bash
du -sh "$PREFIX/lib/hermes-agent" /data/data/com.termux/files/home/.hermes
```

Output (real, `aarch64/Android 15/Termux 0.118.3`):

```text
766M     /data/data/com.termux/files/usr/lib/hermes-agent
195M     /data/data/com.termux/files/home/.hermes    ← generated on first run (~agent/user-visible state); grows further on attempted runs
```

Also `dpkg-query -W -f='${Installed-Size}` = `779312` KiB (~761 MiB app tree), matching the `du` figure.

## 4. Known limitations recorded (real interactions)

1. `hermes doctor` printed Housekeeping facts before anything else (real snippet):
   - `✓ Runtime venv staged (/data/data/com.termux/files/usr/lib/hermes-agent/venv) (active in this process)`
   - `✓ Mandatory CLI/`hermes` command managed by apt (/data/data/com.termux/files/usr/lib/hermes-agent/bin/hermes)`
   - Several flows stated `not installed`/`not logged in` for OPTIONAL providers and tools (`python-telegram-bot`, `discord.py`, `Nous Portal`, `OpenAI Codex`, `MiniMax OAuth`, `xAI OAuth` etc.) — expected for a **first-run, unauthenticated** install.
   - `⚠ config.yaml not found (using defaults)` / `√ ~/.hermes/…` directory skeleton created.
2. `hermes pm doctor`'s toolchain inventory printed `✓ ffmpeg 9.0.1`, `✓ node`, `✓ npm`, `✓ python staged`, `✓ ripgrep 15.2.0`, and recorded `n/a` for **upstream-unavailable Android/Termux builds**: `agent-browser`, `bws`, `chromium`, `cua-driver`, `iron-proxy`, `llamacpp-{cpu,cuda,hip,metal,vulkan}` plus one aux path. **The same run ended in an upstream-code crash** (Traceback ending inside `pm/install.py:161, in <genexpr>_identity ... for a["sha256"]`) — recorded as another real upstream canary defect, not a device problem.

## 5. Precise blocker (agent first-run fails to finish installing its Python deps)

Every agent entrypoint attempted (`hermes -z "Reply with exactly one word…"`, with and without explicit `--provider anthropic --model claude-sonnet-4-5`) attempts to run its own upstream PM first-run Python-dependency sync via the local workspace **on the device**, and fails reproducibly **before any provider/network call**):

Real command (credentials disabled by design in the recorded lines — none of the body carries the secret):

```bash
timeout 240 "$PREFIX/bin/hermes" -z "Reply with exactly one word: NORYKA-OK" \
  [ + --provider anthropic --model claude-sonnet-4-5, and variants ]
```

Real recurring failure (Truncated to the load-bearing lines; full text retained on-device):

```text
  → Installing Python dependencies…
  ✗ Installing Python dependencies failed; last 70 lines of output:
        Building hermes-agent @ file:///data/data/com.termux/files/home/.hermes/installs/1765bb811b147ca4/environments/.../workspace
        Building pillow-heif==1.6.0
        Building firecrawl-anydoc==0.2.4
        Building jiter==0.16.0
        Building watchfiles==1.2.0
        Building pydantic-core==2.46.4
        Building cryptography==50.0.1
        Building psutil @ git+https://github.com/giampaolo/psutil.git@380bd2b...
    error: Failed to build `pillow-heif==1.6.0`
      cause: Call to `setuptools.build_meta:__legacy__.build_wheel` failed (exit status: 1)
```

Note the root cause chain captured in the build's stderr (real):

```text
RequiredDependencyException: The headers or library files could not be found for libheif,
a required dependency when compiling Pillow-Heif from source.
```

Interpretation, cross-checked against the *installed* canary package (not guessed):

- The deb **ships** a prebuilt `pillow_heif` wheel artifact and even a staged lib (`/data/data/com.termux/files/usr/lib/hermes-agent/venv/lib/python3.14/site-packages/pillow_heif-1.6.0.dist-info` plus `_pillow_heif.cpython-314-aarch64-linux-android.so`, verified by import in that staged venv: `import pillow_heif; pillow_heif.__version__` → `1.6.0` — worked).
- It also ships `runtime-libs/lib/libheif.so(.1…)` fetch metadata (`app/pm/termux_runtime_libs.json:` `libheif v1.23.6`, sha256 recorded) — **but NOT the `libheif.h` / headers** needed at *build* time.
- The agent first-run path **doesn't reuse the staged wheel closure**; it re-builds the full dependency set via uv from the local workspace (`Building hermes-agent @ file://…/.hermes/installs/…/workspace`), hits pillow-heif's source build, and fails on missing headers. Consequences: no agent entrypoint can reach the Provider/HTTP layer → "Minimal provider-backed request" can **not** succeed on any provider, and shutdown-after-invocation can not be exercised. This matches upstream's own `termux.md` banner at the pinned SHA, lines 9–13: *"Termux is currently broken. The Termux package does not work right now. A fix is in progress and will ship soon."*
- Diagnosing this, I did NOT modify any upstream installation script or route (constraint honored); the only variation was the documented channel switch itself — `stable`→`canary`, which the pinned doc explicitly names as the supported alternate.

Therefore this Issue's remaining acceptance targets (working minimal provider-backed invocation, shutdown-of-live-agent check) can only be satisfied after upstream publishes a Termux canary/stable build that fixes the first-run PM dependency path for `pillow-heif`'s missing build headers / non-reuse of the shipped wheel — and, for NORYKA's purposes, one that carries (or whose doc mapping pins) the desired Hermes source commit `5057eaa3a4d0cbef0e30078418a5115faa62889e` or a documented successor the NORYKA owner approves.

## 6. What is needed to finish this issue (recorded opening state)

1. **Upstream fix/ship** a supported Termux channel artifact where the first-run dependency install completes on-device — most plausibly by reusing/pre-installing the bundled wheel and not attempting to rebuild all source dependencies (especially `pillow-heif`) when the headers are not exported from the staged path (`runtime-libs/include/` currently absent so the build fails).
2. **A channel state carrying (or a documented mapping to) the pinned SHA `5057eaa…`** — today every channel artifact is behind (`hermes-stable` 404, canary 0.22.0~canary.20261014 built off `v2026.9.24`, `~14 days` before the pin). Either the pin is rebased by owner decision to a version the channel can deliver, or the mapped artifact must become available.
3. Only after 1 (and either 2 result) can this Issue record:
   - a completed `hermes doctor` (no errors) — currently already ✓ for the CLI environment;
   - a successful **minimum real Provider invocation** through the Runtime (an `NORYKA-…`-canvas test that proves the Agent turn loop emits a response);
   - a clean **`agent`/`gateway` shutdown** path (call `agent.close()` or equivalent upstream `Quit`);
   - final disk (`du -sh`) and memory numbers recorded after the fixed flow.
4. **Upstream symptom reporting follow-up** (recommended): open an upstream issue/PR on `NousResearch/hermes-agent` referencing the exact reproducible on-device evidence (first-run uv line + `libheif` header gap + `pm install.py:161` crash) so the canary-line maintainer can fix the packaging; no NORYKA-side workaround asserted.
