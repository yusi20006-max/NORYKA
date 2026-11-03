from __future__ import annotations
import datetime, json, os, re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import httpx

PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
JALALI_MONTHS = ("فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند")
JALALI_WEEKDAYS = ("دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه", "شنبه", "یکشنبه")

def gregorian_to_jalali(gy: int, gm: int, gd: int) -> Tuple[int, int, int]:
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    jy = 979 if gy > 1600 else 0
    gy -= 1600 if gy > 1600 else 621
    gy2 = gy + 1 if gm > 2 else gy
    days = (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) - 80 + gd + g_d_m[gm - 1]
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    jm = (1 + (days // 31)) if days < 186 else (7 + ((days - 186) // 30))
    jd = (1 + (days % 31)) if days < 186 else (1 + ((days - 186) % 30))
    return jy, jm, jd

def now_jalali_str() -> Tuple[str, str, str]:
    tz_irst = datetime.timezone(datetime.timedelta(hours=3, minutes=30))
    now = datetime.datetime.now(tz_irst)
    jy, jm, jd = gregorian_to_jalali(now.year, now.month, now.day)
    return f"{JALALI_WEEKDAYS[now.weekday()]} {jd} {JALALI_MONTHS[jm - 1]} {jy}", f"{jy:04d}/{jm:02d}/{jd:02d}", now.strftime("%H:%M")

def _storage_path() -> Path:
    home = os.environ.get("NORYKA_HOME") or os.path.expanduser("~/.noryka")
    p = Path(home) / "personal_assistant.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def load_personal_store() -> Dict[str, Any]:
    p = _storage_path()
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return d
        except Exception:
            pass
    return {"todos": [], "expenses": []}

def save_personal_store(data: Dict[str, Any]) -> None:
    _storage_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def normalize_digits(text: str) -> str:
    return (text or "").translate(PERSIAN_DIGITS)

def parse_toman_amount(raw: str) -> Tuple[Optional[int], str]:
    s = normalize_digits(raw).strip()
    m = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(میلیون|ملیون|هزار|تومان|تومن|ت)?\s*(?:تومان|تومن|ت)?\s*(.*)$", s)
    if not m:
        return None, s
    val, unit, desc = float(m.group(1)), (m.group(2) or "").strip(), (m.group(3) or "").strip() or "هزینه عمومی"
    if unit in {"میلیون", "ملیون"}:
        val *= 1_000_000
    elif unit == "هزار" or val < 1000:
        val *= 1_000
    return int(round(val)), desc

def parse_duration_seconds(raw: str) -> Tuple[Optional[int], str, str]:
    s = normalize_digits(raw).strip()
    m = re.match(r"^\s*(\d+)\s*(s|sec|ثانیه|m|min|دقیقه|h|hr|hour|ساعت)\s+(.+)$", s, flags=re.I)
    if not m:
        return None, "", s
    num, unit, note = int(m.group(1)), m.group(2).lower(), m.group(3).strip()
    if unit in {"s", "sec", "ثانیه"}:
        return num, f"{num} ثانیه", note
    if unit in {"h", "hr", "hour", "ساعت"}:
        return num * 3600, f"{num} ساعت", note
    return num * 60, f"{num} دقیقه", note

async def fetch_live_market_data() -> Dict[str, Any]:
    res: Dict[str, Any] = {"usdt_toman": None, "btc_usd": None, "btc_toman": None, "eth_usd": None, "paxg_usd": None, "gold_18k_toman": None}
    async with httpx.AsyncClient(timeout=8.0) as client:
        try:
            r = await client.get("https://apiv2.nobitex.ir/market/stats", params={"srcCurrency": "usdt,btc,eth,paxg", "dstCurrency": "rls,usdt"})
            if r.status_code == 200:
                st = r.json().get("stats") or {}
                u_rls = float((st.get("usdt-rls") or {}).get("latest") or 0)
                if u_rls > 0: res["usdt_toman"] = int(round(u_rls / 10.0))
                b_rls = float((st.get("btc-rls") or {}).get("latest") or 0)
                if b_rls > 0: res["btc_toman"] = int(round(b_rls / 10.0))
                b_u = float((st.get("btc-usdt") or {}).get("latest") or 0)
                if b_u > 0: res["btc_usd"] = round(b_u, 2)
                e_u = float((st.get("eth-usdt") or {}).get("latest") or 0)
                if e_u > 0: res["eth_usd"] = round(e_u, 2)
                p_u = float((st.get("paxg-usdt") or {}).get("latest") or 0)
                if p_u > 0: res["paxg_usd"] = round(p_u, 2)
        except Exception:
            pass
    if res["paxg_usd"] and res["usdt_toman"]:
        res["gold_18k_toman"] = int(round((float(res["paxg_usd"]) * 0.75 / 31.1034768) * float(res["usdt_toman"])))
    return res

def format_today_card() -> str:
    full_fa, num_fa, time_str = now_jalali_str()
    store = load_personal_store()
    todos = [t for t in store.get("todos", []) if not t.get("done")]
    expenses = store.get("expenses", [])
    month_total = sum(int(e.get("amount", 0)) for e in expenses if str(e.get("date", "")).startswith(num_fa[:7]))
    lines = [
        "⟐ ✦ ⟐  *بریفینگ روزانه و تقویم شمسی نوریکا*",
        f"📅 *امروز:* {full_fa} (`{num_fa}`) | 🕒 ساعت `{time_str}`",
        "",
        f"✅ *کارهای باز شما ({len(todos)} مورد):*",
    ]
    if todos:
        for i, item in enumerate(todos[:6], 1):
            lines.append(f"  {i}. {item.get('title')}")
    else:
        lines.append("  • کار بازی ثبت نشده است (افزودن با: `کار: ...` یا `/todo ...`)")
    lines.extend([
        "",
        f"💳 *جمع مخارج این ماه:* `{month_total:,}` تومان",
        "💡 _ثبت هزینه جدید:_ `هزینه ۲۵۰ هزار تومن ناهار`",
        "💡 _ثبت یادآور:_ `یادآوری ۱۰ دقیقه تماس با شرکت`",
    ])
    return "\n".join(lines)

def format_todo_card(arg_text: str = "") -> Tuple[str, Optional[Dict[str, Any]]]:
    store = load_personal_store()
    todos: List[Dict[str, Any]] = store.setdefault("todos", [])
    arg = normalize_digits(arg_text).strip()
    _, num_fa, _ = now_jalali_str()
    if arg:
        if arg.lower() in {"clear", "پاک"}:
            store["todos"] = []
            save_personal_store(store)
            return "🗑️ لیست کارها پاک شد.", None
        m_done = re.match(r"^(?:done|انجام|تیک|حذف)\s*(\d+)$", arg.lower())
        if m_done:
            idx = int(m_done.group(1)) - 1
            if 0 <= idx < len(todos):
                rem = todos.pop(idx)
                save_personal_store(store)
                return f"✅ کار «*{rem.get('title')}*» انجام شد!", _build_todo_buttons(todos)
        clean = re.sub(r"^(?:add|افزودن|جدید)\s+", "", arg, flags=re.I).strip()
        if clean:
            todos.append({"title": clean, "date": num_fa, "done": False})
            save_personal_store(store)
    lines = ["✅ *لیست کارهای شخصی نوریکا:*", ""]
    if not todos:
        lines.append("📭 لیست کارهای شما خالی است.")
    else:
        for i, t in enumerate(todos, 1):
            lines.append(f"{i}. ⬜ *{t.get('title')}* ({t.get('date', '')})")
    lines.append("\n📌 برای افزودن کار بنویسید: `کار: خرید شارژر` یا `/todo خرید شارژر`")
    return "\n".join(lines), _build_todo_buttons(todos)

def _build_todo_buttons(todos: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows: List[List[Dict[str, str]]] = []
    cur: List[Dict[str, str]] = []
    for i, t in enumerate(todos[:6], 1):
        cur.append({"text": f"✓ انجام #{i} ({str(t.get('title',''))[:12]})", "callback_data": f"cmd:/todo done {i}"})
        if len(cur) == 2:
            rows.append(cur); cur = []
    if cur: rows.append(cur)
    rows.append([{"text": "📅 امروز (/today)", "callback_data": "cmd:/today"}, {"text": "🎛 پنل اصلی (/panel)", "callback_data": "cmd:/panel"}])
    return {"inline_keyboard": rows}

def format_expense_card(arg_text: str = "") -> str:
    store = load_personal_store()
    expenses: List[Dict[str, Any]] = store.setdefault("expenses", [])
    _, num_fa, time_str = now_jalali_str()
    arg = (arg_text or "").strip()
    hdr = ""
    if arg:
        if normalize_digits(arg).strip().lower() in {"clear", "پاک", "ریست"}:
            store["expenses"] = []
            save_personal_store(store)
            return "🗑️ دفتر مخارج ماهانه ریست شد."
        amt, title = parse_toman_amount(arg)
        if amt and amt > 0:
            expenses.append({"amount": amt, "title": title, "date": num_fa, "time": time_str})
            save_personal_store(store)
            hdr = f"✅ ثبت شد: *{amt:,} تومان* بابت «*{title}*»\n\n"
    cur_m = num_fa[:7]
    m_items = [e for e in expenses if str(e.get("date", "")).startswith(cur_m)]
    total = sum(int(e.get("amount", 0)) for e in m_items)
    lines = [hdr + "💳 *دفتر حسابداری شخصی نوریکا*", f"💰 *جمع مخارج ماه ({cur_m}):* `{total:,}` تومان", ""]
    for e in m_items[-7:]:
        lines.append(f"  • `{int(e.get('amount', 0)):,}` تومان — *{e.get('title')}* ({e.get('date')})")
    lines.append("\n📌 ثبت سریع هزینه: `هزینه ۲۵۰ هزار تومن ناهار`")
    return "\n".join(lines)

async def format_market_card() -> str:
    full_fa, _, time_str = now_jalali_str()
    m = await fetch_live_market_data()
    u = f"{m['usdt_toman']:,} تومان" if m.get("usdt_toman") else "نامشخص"
    g = f"{m['gold_18k_toman']:,} تومان" if m.get("gold_18k_toman") else "—"
    bu = f"${m['btc_usd']:,}" if m.get("btc_usd") else "—"
    bt = f"{m['btc_toman']:,} تومان" if m.get("btc_toman") else "—"
    eu = f"${m['eth_usd']:,}" if m.get("eth_usd") else "—"
    pu = f"${m['paxg_usd']:,}" if m.get("paxg_usd") else "—"
    return (
        "⟐ ✦ ⟐  *رادار لحظه‌ای بازار، طلا و رمزارز نوریکا*\n"
        f"📅 {full_fa} — ساعت `{time_str}`\n\n"
        f"💵 *تتر / دلار آزاد (USDT):* `{u}`\n"
        f"✨ *گرم طلای ۱۸ عیار:* `{g}`\n"
        f"🪙 *اونس جهانی طلا (PAXG):* `{pu}`\n"
        f"₿ *بیت‌کوین (BTC):* `{bu}` (`{bt}`)\n"
        f"💎 *اتریوم (ETH):* `{eu}`"
    )
