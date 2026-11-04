from __future__ import annotations
import json, os, time
from pathlib import Path

PERSONAS = {
    "default": {"title": "✦ هسته پیش‌فرض نوریکا", "desc": "دستیار شخصی هوشمند همه‌منظوره"},
    "coder": {"title": "💻 مهندس نرم‌افزار ارشد", "desc": "تمرکز روی معماری و کدنویسی تمیز"},
    "financial": {"title": "📈 مشاور مالی و بازار", "desc": "تحلیل بازار طلا، ارز و رمزارزها"},
    "researcher": {"title": "🔬 پژوهشگر عمیق", "desc": "مطالعه و خلاصه‌سازی مقالات و اسناد"},
    "minimal": {"title": "⚡ پاسخ‌های فوق‌سریع", "desc": "پاسخ‌های تلگرافی در ۱-۲ جمله"},
}

def _store():
    p = Path(os.environ.get("NORYKA_HOME") or os.path.expanduser("~/.noryka")) / "super_suite.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        try: return json.loads(p.read_text(encoding="utf-8"))
        except Exception: pass
    return {"active_persona": "default", "docs": [], "inbox": []}

def _save(d):
    p = Path(os.environ.get("NORYKA_HOME") or os.path.expanduser("~/.noryka")) / "super_suite.json"
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

def format_persona_card(c=""):
    d = _store()
    c = c.strip().lower()
    if c in PERSONAS:
        d["active_persona"] = c; _save(d)
        p = PERSONAS[c]
        return f"🎭 *پرسونای فعال تغییر کرد:*\n*{p['title']}*\n_{p['desc']}_", _p_btns(c)
    act = d.get("active_persona", "default")
    lines = ["🎭 *پرسوناهای تخصصی نوریکا (v3.3.0):*", f"📍 *فعلی:* {PERSONAS.get(act, PERSONAS['default'])['title']}", "", "روی دکمه مورد نظر بزنید:"]
    return "\n".join(lines), _p_btns(act)

def _p_btns(act):
    rows = []
    for k, v in PERSONAS.items():
        m = "✓ " if k == act else ""
        rows.append([{"text": f"{m}{v['title']}", "callback_data": f"cmd:/persona {k}"}])
    rows.append([{"text": "🎛 بازگشت به پنل اصلی (/panel)", "callback_data": "cmd:/panel"}])
    return {"inline_keyboard": rows}

def format_inbox_card(arg=""):
    d = _store(); inbox = d.setdefault("inbox", [])
    arg = arg.strip()
    if arg:
        if arg in {"clear", "پاک"}: d["inbox"] = []; _save(d); return "🗑️ اینباکس پاکسازی شد.", None
        inbox.append({"text": arg, "time": time.strftime("%H:%M")}); _save(d)
        return f"📥 در اینباکس ثبت شد: «*{arg}*»", _inbox_btns()
    lines = [f"📥 *اینباکس پیام‌ها و وظایف ورودی ({len(inbox)} پیام):*", ""]
    if not inbox: lines.append("📭 اینباکس خالی است.")
    else:
        for i, item in enumerate(inbox[-5:], 1): lines.append(f"{i}. 🟢 *{item.get('text')}* _({item.get('time')})_")
    lines.append("\n💡 ثبت پیام جدید: `/inbox تماس از شرکت`")
    return "\n".join(lines), _inbox_btns()

def _inbox_btns():
    return {"inline_keyboard": [[{"text": "📅 امروز (/today)", "callback_data": "cmd:/today"}, {"text": "✅ کارها (/todo)", "callback_data": "cmd:/todo"}], [{"text": "🎛 پنل اصلی (/panel)", "callback_data": "cmd:/panel"}]]}

def search_document_vault(q=""):
    d = _store(); docs = d.get("docs", [])
    if not docs:
        return "📚 *مغز دوم و کتابخانه اسناد نوریکا (v3.3.0)*\n\n📭 هنوز فایلی ثبت نشده است.\n💡 _برای افزودن سند، فایل متنی یا PDF در بله ارسال کنید._"
    lines = [f"📚 *کتابخانه اسناد ({len(docs)} سند):*", ""]
    for i, item in enumerate(docs[:6], 1): lines.append(f"{i}. 📄 *{item.get('title', item.get('filename'))}*")
    return "\n".join(lines)
