"""Interactive Model Switcher, Fallback Health Monitor, and Lightweight System Backup for Bale."""

from __future__ import annotations

import os
import tarfile
import time
from pathlib import Path
from typing import Any, Dict, List

NORYKA_HOME = Path.home() / ".noryka"
BACKUP_DIR = NORYKA_HOME / "backups"
NL = chr(10)

AVAILABLE_MODELS: List[Dict[str, str]] = [
    {"id": "gemini-2.5-flash", "label": "⚡ Gemini 2.5 Flash (سریع و اقتصادی)", "env": "GEMINI_API_KEY"},
    {"id": "gemini-2.5-pro", "label": "🧠 Gemini 2.5 Pro (تحلیلی و پیشرفته)", "env": "GEMINI_API_KEY"},
    {"id": "gpt-4o-mini", "label": "🟢 GPT-4o Mini (سبک)", "env": "OPENAI_API_KEY"},
    {"id": "claude-3-5-sonnet", "label": "🟣 Claude 3.5 Sonnet", "env": "ANTHROPIC_API_KEY"},
    {"id": "deepseek-chat", "label": "🔵 DeepSeek V3", "env": "DEEPSEEK_API_KEY"},
]


def _check_provider_health() -> List[Dict[str, Any]]:
    results = []
    for item in AVAILABLE_MODELS:
        env_key = item["env"]
        val = os.getenv(env_key, "").strip()
        is_set = bool(val)
        results.append({
            "id": item["id"],
            "label": item["label"],
            "env": env_key,
            "healthy": is_set,
            "status": "🟢 آماده (Key Set)" if is_set else "⚪ بدون کلید",
        })
    return results


async def handle_models_async(adapter: Any, chat_id: str, cmd: str) -> bool:
    parts = cmd.split(":", 1)
    if len(parts) == 2 and parts[0].lower() == "/models":
        selected_model = parts[1].strip()
        os.environ["NORYKA_MODEL"] = selected_model
        await adapter.send(
            chat_id,
            f"✅ مدل فعال دستیار با موفقیت به `{selected_model}` تغییر یافت.",
            metadata={"reply_markup": adapter._main_menu_markup()},
        )
        return True

    current_model = os.getenv("NORYKA_MODEL", "gemini-2.5-flash")
    buttons = []
    for m in AVAILABLE_MODELS:
        prefix = "✅ " if m["id"] == current_model else "🔘 "
        buttons.append([{"text": f"{prefix}{m['label']}", "callback_data": f"cmd:/models:{m['id']}"}])
    buttons.append([{"text": "🔙 بازگشت به منوی اصلی", "callback_data": "cmd:/start"}])

    lines = [
        "🧠 **مدیریت و تعویض مدل هوش مصنوعی**",
        "",
        f"• مدل فعال کنونی: `{current_model}`",
        "برای تغییر فوری مدل، روی یکی از دکمه‌های شیشه‌ای زیر بزنید:",
    ]
    await adapter.send(chat_id, NL.join(lines), metadata={"reply_markup": {"inline_keyboard": buttons}})
    return True


async def handle_fallback_async(adapter: Any, chat_id: str, cmd: str) -> bool:
    parts = cmd.split(":", 1)
    if len(parts) == 2 and parts[0].lower() == "/fallback":
        target_model = parts[1].strip()
        os.environ["NORYKA_MODEL"] = target_model
        await adapter.send(
            chat_id,
            f"🔄 سوئیچ دستی انجام شد! پروایدر/مدل فعال اکنون: `{target_model}`",
            metadata={"reply_markup": adapter._main_menu_markup()},
        )
        return True

    statuses = _check_provider_health()
    current = os.getenv("NORYKA_MODEL", "gemini-2.5-flash")
    lines = [
        "🛡️ **وضعیت سلامت APIها و زنجیره فال‌بک (Fallback)**",
        "",
        f"• مدل در حال استفاده: `{current}`",
        "• عملکرد فال‌بک: در صورت خطای 429 یا قطعی، سیستم خودکار به کلید سالم بعدی سوئیچ می‌کند.",
        "",
        "**لیست پروایدرها و وضعیت سلامت:**",
    ]
    buttons = []
    for st in statuses:
        lines.append(f"• `{st['id']}` — {st['status']}")
        buttons.append([
            {"text": f"🔀 سوئیچ دستی به {st['id']}", "callback_data": f"cmd:/fallback:{st['id']}"}
        ])
    buttons.append([{"text": "🔙 بازگشت به منوی اصلی", "callback_data": "cmd:/start"}])

    await adapter.send(
        chat_id,
        NL.join(lines),
        metadata={"reply_markup": {"inline_keyboard": buttons}},
    )
    return True


async def handle_backup_async(adapter: Any, chat_id: str, cmd: str) -> bool:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    lower = cmd.strip().lower()

    if lower.startswith("/restore"):
        backups = sorted(BACKUP_DIR.glob("noryka_backup_*.tar.gz"), reverse=True)
        if not backups:
            await adapter.send(chat_id, "⚠️ هنوز هیچ فایل پشتیبانی در سیستم ثبت نشده است.")
            return True
        latest = backups[0]
        try:
            with tarfile.open(latest, "r:gz") as tar:
                tar.extractall(path=NORYKA_HOME)
            lines = [
                "♻️ **بازیابی با موفقیت انجام شد!**",
                f"• فایل: `{latest.name}`",
                "• تنظیمات، متغیرها و کرون‌جاب‌ها بازگردانی شدند.",
            ]
            await adapter.send(
                chat_id,
                NL.join(lines),
                metadata={"reply_markup": adapter._main_menu_markup()},
            )
        except Exception as exc:
            await adapter.send(chat_id, f"❌ خطا در بازیابی بک‌آپ: {exc}")
        return True

    ts = time.strftime("%Y%m%d_%H%M%S")
    archive_path = BACKUP_DIR / f"noryka_backup_{ts}.tar.gz"
    included = []
    try:
        with tarfile.open(archive_path, "w:gz") as tar:
            for item_name in ("config.yaml", "config.json", ".env", "cron", "profiles"):
                candidate = NORYKA_HOME / item_name
                if candidate.exists():
                    tar.add(candidate, arcname=item_name)
                    included.append(item_name)
        size_kb = archive_path.stat().st_size / 1024.0
        lines = [
            "💾 **بک‌آپ فشرده با موفقیت ساخته شد!**",
            f"• نام فایل: `{archive_path.name}`",
            f"• حجم: `{size_kb:.1f} KB`",
            f"• بخش‌های ذخیره شده: `{', '.join(included) or 'تنظیمات پایه'}`",
        ]
        await adapter.send(
            chat_id,
            NL.join(lines),
            metadata={"reply_markup": adapter._main_menu_markup()},
        )
    except Exception as exc:
        await adapter.send(chat_id, f"❌ خطا در ساخت بک‌آپ: {exc}")
    return True
