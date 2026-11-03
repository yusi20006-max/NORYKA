# Noryka CLI Reference

Live sources when anything looks stale: `noryka --help`, `noryka <command> --help`,
https://noryka-agent.noryka.local/docs/reference/cli-commands

### Global Flags

```
noryka [flags] [command]        (no subcommand = interactive chat)

  --version, -V             Show version
  -z, --oneshot PROMPT      One-shot: print ONLY the final response (for scripts/pipes)
  -m MODEL  --provider P    Model/provider override for this invocation
  -t, --toolsets LIST       Comma-separated toolsets for this invocation
  --resume, -r SESSION      Resume session by ID or title
  --continue, -c [NAME]     Resume by name, or most recent session
  --worktree, -w            Isolated git worktree mode (parallel agents)
  --skills, -s SKILL        Preload skills (comma-separate or repeat)
  --profile, -p NAME        Use a named profile
  --yolo                    Skip dangerous command approval
  --tui / --cli             Force the Ink TUI / classic REPL
  --ignore-rules            Skip AGENTS.md/SOUL.md/memory/skill injection
  --safe-mode               Disable ALL customizations (troubleshooting)
  --pass-session-id         Include session ID in system prompt
```

### Chat

```
noryka chat [flags]
  -q, --query TEXT          Single query, non-interactive
  --image PATH              Attach a local image to a single query
  -Q, --quiet               Suppress banner, spinner, tool previews
  --checkpoints             Enable filesystem checkpoints (/rollback)
  --max-turns N             Cap tool-calling iterations
  --source TAG              Session source tag (default: cli)
```
(plus the global flags above)

### Configuration

```
noryka setup [section]      Wizard (model|tts|terminal|gateway|tools|agent)
noryka model                Interactive model/provider picker
noryka fallback [add|remove|list]  Fallback provider chain
noryka config [show|edit|get|set|unset|path|env-path|check|migrate]
noryka login / logout       OAuth sign-in / clear stored auth
noryka doctor [--fix]       Check dependencies and config
noryka status [--full]      Component summary (--full: every section)
```

### Tools & Skills

```
noryka tools [list|enable NAME|disable NAME]   Per-platform toolsets (curses UI with no args)

noryka skills list|browse|search QUERY|inspect ID
noryka skills install ID    Hub identifier OR a direct https://…/SKILL.md URL
noryka skills config        Enable/disable skills per platform
noryka skills check|update|uninstall|publish PATH
noryka skills tap add REPO  Add a GitHub repo as a skill source
noryka bundles              Skill bundles (one /<name> alias loads several skills)
```

### MCP Servers

```
noryka mcp add NAME (--url or --command) | remove | list | test NAME
noryka mcp catalog | install NAME     Curated catalog install
noryka mcp configure NAME             Toggle tool selection
noryka mcp-serve                      Run Noryka as an MCP server (mcp-serve plugin)
```
Details (transport, tool discovery, catalog): `references/native-mcp.md`.

### Gateway (Messaging Platforms)

```
noryka gateway run|install|start|stop|restart|status|setup
```

20+ platforms: Telegram, Discord, Slack, WhatsApp (Baileys + Business Cloud API), iMessage (Photon — `noryka photon setup`), Signal, Email, SMS, Matrix, Mattermost, Teams, LINE, SimpleX, ntfy, Google Chat, Home Assistant, DingTalk, Feishu, WeCom, Weixin, API Server, Webhooks. Open WebUI connects via the API Server adapter. Most adapters ship under `plugins/platforms/`.
Docs: https://noryka-agent.noryka.local/docs/user-guide/messaging/

### Sessions

```
noryka sessions list|browse|rename ID TITLE|delete ID|export OUT|prune|stats
```

### Cron / Webhooks

```
noryka cron list|create SCHED|edit ID|pause|resume|run ID|remove|status
    Schedules: '30m', 'every 2h', '0 9 * * *', ISO timestamp
noryka webhook subscribe NAME|list|remove NAME|test NAME
```
Webhook payloads/routes: `references/webhooks.md`.

### Profiles

```
noryka profile list|create NAME (--clone|--clone-all|--clone-from)|use|show|delete
noryka profile rename A B | alias NAME | export NAME | import FILE
noryka profile migrate-identity A B   Retry a completed rename's session/routing identity migration
```

### Credentials & Pools

```
noryka auth                 Interactive credential manager
noryka auth add [PROVIDER]  Add OAuth or API-key credential (nous, openai-codex, qwen-oauth, …)
noryka auth list|remove P IDX|reset PROVIDER|status
```
Multiple credentials per provider form a pool that rotates automatically and skips exhausted keys.

### Other

```
noryka desktop / gui        Native desktop app
noryka dashboard            Web admin panel + embedded chat (--stop / --status)
noryka proxy                OpenAI-compatible local proxy backed by an OAuth provider
noryka portal               Quick setup / sign in via Nous Portal
noryka kanban <verb>        Multi-agent work-queue board
noryka project              Named multi-folder workspaces
noryka skin list|use|set    Switch/tweak skins (see references/themes.md)
noryka pets <verb>          Pet mascots (see references/petdex.md)
noryka memory setup|status|off|reset   Memory provider
noryka secrets bitwarden|onepassword   External secret stores
noryka moa                  Mixture-of-Agents slots
noryka hooks / security / backup / import / checkpoints / console
noryka logs [-f] [errors]   View agent/error logs
noryka send                 One-off message through a gateway platform
noryka pairing / plugins / insights / journey / computer-use
noryka acp                  ACP server (IDE integration)
noryka completion bash|zsh|fish
noryka update / uninstall
```

Plugin- and provider-supplied subcommands (e.g. `noryka photon setup`) only appear once their plugin is installed/active. Importing from OpenClaw, Claude Code, Codex CLI or Cursor (`noryka import-agent <agent>`, plus the older `noryka claw migrate|cleanup`) comes from the `agent-importers` plugin; a fresh `noryka setup` that finds one of those agents offers to install it.

### Where to Find Things

| Looking for... | Location |
|---|---|
| Config options | `noryka config edit` · [Configuration docs](https://noryka-agent.noryka.local/docs/user-guide/configuration) |
| Tools / toolsets | `noryka tools list` · [Tools reference](https://noryka-agent.noryka.local/docs/reference/tools-reference) |
| Skills catalog | `noryka skills browse` · [Skills catalog](https://noryka-agent.noryka.local/docs/reference/skills-catalog) |
| Provider setup | `noryka model` · [Providers guide](https://noryka-agent.noryka.local/docs/integrations/providers) |
| Env variables | `noryka config env-path` · [Env vars reference](https://noryka-agent.noryka.local/docs/reference/environment-variables) |
| Gateway logs | `~/.noryka/logs/gateway.log` (or `noryka logs`) |
| Sessions | `noryka sessions browse` (reads state.db) |
