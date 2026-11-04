from __future__ import annotations
import asyncio, json, os, shutil, time, zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import httpx

PRESET_MODELS = [
    {"id": "openrouter/nvidia-nemotron", "provider": "openrouter", "model": "nvidia/nemotron-3-ultra-550b-a55b:free", "label": "⚡ Nemotron 3 Ultra (OpenRouter · رایگان)"},
    {"id": "openrouter/gemma-3", "provider": "openrouter", "model": "google/gemma-3-27b-it:free", "label": "👁 Gemma 3 27B Vision (OpenRouter · بینایی ماشین)"},
    {"id": "gemini/flash", "provider": "gemini", "model": "gemini-2.5-flash", "label": "💎 Gemini 2.5 Flash (Google · فوق‌سریع)"},
    {"id": "openrouter/qwen-coder", "provider": "openrouter", "model": "qwen/qwen-2.5-coder-32b-instruct:free", "label": "💻 Qwen 2.5 Coder 32B (OpenRouter · کدنویسی)"},
    {"id": "openrouter/mistral-small", "provider": "openrouter", "model": "mistralai/mistral-small-3.1-24b-instruct:free", "label": "🌀 Mistral Small 24B (OpenRouter · استدلال)"},
    {"id": "openrouter/deepseek-r1", "provider": "openrouter", "model": "deepseek/deepseek-r1:free", "label": "🧠 DeepSeek R1 (OpenRouter · تحلیلی)"},
]

def _noryka_home() -> Path:
    p = Path(os.environ.get("NORYKA_HOME") or os.path.expanduser("~/.noryka"))
    p.mkdir(parents=True, exist_ok=True)
    return p

def _load_env_map() -> Dict[str, str]:
    home = _noryka_home()
    env_file = home / ".env"
    env_map = {}
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env_map[k.strip()] = v.strip().strip('"'')
        except Exception: pass
    return env_map

def _get_key(key: str, env_map: Dict[str, str]) -> str:
    return (os.environ.get(key) or env_map.get(key) or "").strip()

def _mask_key(val: str) -> str:
    if not val: return "تنظیم نشده ❌"
    return f"{val[:6]}...{val[-4:]} ✓" if len(val) > 10 else f"{val[:3]}...{val[-2:]} ✓"

async def check_single_provider_health(name: str, key: str) -> Tuple[bool, Optional[int], str]:
    if not key: return False, None, "کلید API ثبت نشده است"
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            if name == "openrouter":
                r = await client.get("https://openrouter.ai/api/v1/auth/key", headers={"Authorization": f"Bearer {key}"})
                lat = int(round((time.monotonic() - t0) * 1000))
                return (True, lat, f"فعال و سالم ({lat}ms)") if r.status_code == 200 else (False, lat, f"خطای اعتبارسنجی ({r.status_code})")
            elif name in {"gemini", "google"}:
                r = await client.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={key}")
                lat = int(round((time.monotonic() - t0) * 1000))
                return (True, lat, f"فعال و سالم ({lat}ms)") if r.status_code == 200 else (False, lat, f"خطای کلید گوگل ({r.status_code})")
            elif name == "bale":
                r = await client.get(f"https://tapi.bale.ai/bot{key}/getMe")
                lat = int(round((time.monotonic() - t0) * 1000))
                if r.status_code == 200 and r.json().get("ok"):
                    un = (r.json().get("result") or {}).get("username") or ""
                    return True, lat, f"متصل (@{un} · {lat}ms)"
                return False, lat, f"خطای توکن بله ({r.status_code})"
    except Exception:
        return False, None, "عدم دسترسی لحظه‌ای به شبکه"
    return False, None, "نامشخص"

async def get_providers_health_summary() -> Dict[str, Any]:
    from noryka_cli.config import load_config
    env_map = _load_env_map()
    or_key = _get_key("OPENROUTER_API_KEY", env_map)
    gm_key = _get_key("GEMINI_API_KEY", env_map) or _get_key("GOOGLE_API_KEY", env_map)
    bale_tok = _get_key("BALE_BOT_TOKEN", env_map)
    try: cfg = load_config() or {}
    except Exception: cfg = {}
    mcfg = cfg.get("model") if isinstance(cfg.get("model"), dict) else {}
    cur_model = str(mcfg.get("default") or "nvidia/nemotron-3-ultra-550b-a55b:free")
    cur_provider = str(mcfg.get("provider") or ("openrouter" if or_key else "gemini"))
    t_or, t_gm, t_bale = await asyncio.gather(
        check_single_provider_health("openrouter", or_key),
        check_single_provider_health("gemini", gm_key),
        check_single_provider_health("bale", bale_tok),
    )
    return {
        "active_model": cur_model,
        "active_provider": cur_provider,
        "providers": [
            {"name": "OpenRouter (مدل‌های اصلی + Vision)", "masked": _mask_key(or_key), "status_text": t_or[2], "indicator": "green" if t_or[0] else ("orange" if or_key else "red")},
            {"name": "Google Gemini (پروایدر زاپاس مستقیم)", "masked": _mask_key(gm_key), "status_text": t_gm[2], "indicator": "green" if t_gm[0] else ("orange" if gm_key else "red")},
            {"name": "پیام‌رسان بله (tapi.bale.ai)", "masked": _mask_key(bale_tok), "status_text": t_bale[2], "indicator": "green" if t_bale[0] else ("orange" if bale_tok else "red")},
        ],
        "presets": PRESET_MODELS,
    }

def switch_model_and_provider(preset_id: str) -> Dict[str, Any]:
    from noryka_cli.config import get_config_path, load_config, save_config
    preset = next((p for p in PRESET_MODELS if p["id"] == preset_id or p["model"] == preset_id), None)
    if not preset:
        preset = {"id": "custom", "provider": "openrouter", "model": preset_id, "label": preset_id}
    cfg_path = get_config_path()
    try: cfg = load_config() or {}
    except Exception: cfg = {}
    if not isinstance(cfg, dict): cfg = {}
    model_sec = cfg.setdefault("model", {})
    if not isinstance(model_sec, dict): model_sec = cfg["model"] = {}
    model_sec["default"] = preset["model"]
    model_sec["provider"] = preset["provider"]
    try: save_config(cfg)
    except Exception:
        import yaml
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cfg_path, "w", encoding="utf-8") as fh: yaml.dump(cfg, fh)
    return {"ok": True, "active_model": preset["model"], "active_provider": preset["provider"], "label": preset.get("label", preset["model"])}

async def format_fallback_card() -> Tuple[str, Dict[str, Any]]:
    summary = await get_providers_health_summary()
    cur_m, cur_p = summary["active_model"], summary["active_provider"]
    lines = [
        "⟐ ✦ ⟐  *رادار سلامت API و سیستم فالبک (Fallback)*",
        f"🎯 *مدل فعال:* `{cur_m}`",
        f"🏢 *پروایدر فعلی:* `{cur_p}`",
        "",
        "📊 *وضعیت سلامت پروایدرها و کلیدها:*",
    ]
    for prov in summary["providers"]:
        badge = "🟢" if prov["indicator"] == "green" else ("🟠" if prov["indicator"] == "orange" else "🔴")
        lines.append(f"{badge} *{prov['name']}:*\n   • کلید: `{prov['masked']}`\n   • وضعیت: _{prov['status_text']}_")
    lines.extend(["", "🔄 *انتخاب مدل یا پروایدر جدید:*\nروی دکمه مورد نظر بزنید تا مدل درجا عوض شود:"])
    rows = []
    for p in PRESET_MODELS:
        mark = "✓ " if (p["model"] == cur_m and p["provider"] == cur_p) else ""
        rows.append([{"text": f"{mark}{p['label']}", "callback_data": f"cmd:/model_set {p['id']}"}])
    rows.append([{"text": "🔄 بروزرسانی سلامت API", "callback_data": "cmd:/fallback"}, {"text": "🎛 پنل اصلی (/panel)", "callback_data": "cmd:/panel"}])
    return "\n".join(lines), {"inline_keyboard": rows}

def create_compact_backup(out_dir: Optional[Path] = None) -> Path:
    home = _noryka_home()
    if out_dir is None: out_dir = home / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    zip_path = out_dir / f"noryka-backup-{ts}.zip"
    include_files = [".env", "config.yaml", "active_profile", "personal_assistant.json", "super_suite.json", "SOUL.md", "state.db"]
    include_dirs = ["cron", "memories", "sessions"]
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for fname in include_files:
            fpath = home / fname
            if fpath.is_file(): zf.write(fpath, arcname=fname)
        for dname in include_dirs:
            dpath = home / dname
            if dpath.is_dir():
                for f in dpath.rglob("*"):
                    if f.is_file() and not f.name.endswith(".pyc") and "__pycache__" not in str(f):
                        zf.write(f, arcname=str(f.relative_to(home)))
    return zip_path

def restore_compact_backup(zip_path: Path) -> Dict[str, Any]:
    home = _noryka_home()
    if not zip_path.is_file() or not zipfile.is_zipfile(zip_path):
        return {"ok": False, "error": "فایل بکاپ معتبر نیست."}
    restored = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            if member.startswith("/") or ".." in member: continue
            dest = home / member
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, dest.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            restored.append(member)
    return {"ok": True, "restored_count": len(restored)}

async def format_backup_card(action_arg: str = "") -> Tuple[str, Dict[str, Any]]:
    home = _noryka_home()
    backups_dir = home / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    clean = action_arg.strip().lower()
    if clean == "create":
        b_path = create_compact_backup(backups_dir)
        size_kb = round(b_path.stat().st_size / 1024, 1)
        msg = f"💾 *بکاپ کامل و کم‌حجم نوریکا با موفقیت ساخته شد!*\n\n📁 *نام فایل:* `{b_path.name}`\n📦 *حجم:* `{size_kb} KB`\n✅ شامل کلیدهای .env، تنظیمات config.yaml، حسابداری، کارهای Todo و کرون‌ها."
        return msg, _build_backup_buttons(backups_dir)
    all_b = sorted(backups_dir.glob("noryka-backup-*.zip"), key=lambda x: x.stat().st_mtime, reverse=True)
    lines = ["💾 *سیستم بکاپ‌گیری و ری‌استور فوق‌سریع نوریکا*", f"📦 *تعداد بکاپ‌های ذخیره‌شده:* {len(all_b)} مورد", ""]
    if all_b:
        lines.append("📋 *آخرین بکاپ‌ها:*")
        for b in all_b[:3]:
            sz = round(b.stat().st_size / 1024, 1)
            t_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(b.stat().st_mtime))
            lines.append(f"  • `{b.name}` ({sz} KB) — _{t_str}_")
    else:
        lines.append("📭 هنوز هیچ بکاپی گرفته نشده است.")
    lines.extend(["", "با یک لمس بکاپ جدید بگیرید یا آخرین نسخه را بازیابی کنید:"])
    return "\n".join(lines), _build_backup_buttons(backups_dir)

def _build_backup_buttons(backups_dir: Path) -> Dict[str, Any]:
    all_b = sorted(backups_dir.glob("noryka-backup-*.zip"), key=lambda x: x.stat().st_mtime, reverse=True)
    rows = [[{"text": "➕ ساخت بکاپ جدید (< 50KB)", "callback_data": "cmd:/backup create"}]]
    if all_b:
        latest = all_b[0]
        rows.append([{"text": f"🔄 ری‌استور آخرین بکاپ ({latest.name[:18]}...)", "callback_data": "cmd:/restore_latest"}])
    rows.append([{"text": "🧠 تعویض مدل و فالبک (/fallback)", "callback_data": "cmd:/fallback"}, {"text": "🎛 پنل اصلی (/panel)", "callback_data": "cmd:/panel"}])
    return {"inline_keyboard": rows}
