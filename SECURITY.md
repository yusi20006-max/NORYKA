# Noryka Security Policy & Trust Model

Noryka is a personal and multi-channel autonomous AI assistant based on the MIT-licensed Upstream Agent Core architecture (see `LICENSE` for upstream attribution).

## 1. Security Boundary: OS-Level Isolation

**The only security boundary against an adversarial LLM or untrusted prompt is the operating system.**
In-process controls — including the approval gate (`tools/approval.py`), output redaction (`agent/redact.py`), threat pattern scanning (`tools/threat_patterns.py`), and `skills_guard.py` — are accident-prevention heuristics, not containment boundaries.

## 2. Channel Authorization & Fail-Closed Allowlists

- Every network-exposed adapter (`Telegram`, `Bale`, `Discord`, `Slack`, etc.) enforces a **Fail-Closed Allowlist** (`TELEGRAM_ALLOWED_USERS`, `BALE_ALLOWED_USERS`, etc.).
- Unauthenticated callers or public group members must never be granted host execution tools (`terminal`, `execute_code`, `write_file`, `patch`).
- All outbound HTTP fetches in `web_tools.py` pass through `tools/url_safety.py` to prevent SSRF and DNS rebinding against local/private networks.

## 3. Reporting Security Issues

Report security issues via [GitHub Issues / Security Advisories](https://github.com/yusi20006-max/NORYKA/security).
