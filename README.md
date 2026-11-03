# Noryka (نوریکا) — دستیار هوشمند شخصی و پلتفرم کدنویسی چندکاناله

**Noryka** یک فورک مهندسی‌شده، مستقل و بهینه‌سازی‌شده بر پایه معماری MIT-licensed Upstream Agent Core است که به‌طور ویژه برای **عملکرد پایدار روی Android (Termux) و Linux، پشتیبانی بومی از پیام‌رسان بله (Bale) در کنار تلگرام، و کدنویسی پیشرفته از طریق پیام‌رسان‌ها** بازطراحی شده است.

## مشخصات فنی و آمار دقیق مخزن (تأییدشده)

* **تعداد فایل‌های پایتون:** `2694` ماژول پایتون (تأییدشده با `compileall` و `ast.parse` بدون خطای سینتکس)
* **پلتفرم‌های پیام‌رسان (`plugins/platforms/` و `gateway/`):** `28` پلاگین پلتفرم (شامل آداپتور کامل **Bale (`Platform.BALE`)** و **Telegram (`Platform.TELEGRAM`)**)
* **پلاگین‌های ارائه‌دهنده مدل (`plugins/model-providers/`):** `39` ارائه‌دهنده مدل به همراه ۴ ترنسپورت سیم (`chat_completions`, `anthropic_messages`, `codex_responses`, `bedrock_converse`) و چرخش خودکار کلید (`CredentialPool`)
* **ماژول‌های ابزار (`tools/`):** `367` ماژول شامل ابزار تحلیلگر استاتیک کد `ast_code_analyzer` در `tools/ast_code_analyzer_tool.py`

## ویژگی‌های کلیدی نسخه اصلاح‌شده

1. **آداپتور کامل و ایزوله پیام‌رسان بله (`plugins/platforms/bale/adapter.py`):**
   * عضو اختصاصی `Platform.BALE = "bale"` در `gateway/config.py` (بدون هیچ‌گونه تداخل نشست یا Allowlist با تلگرام).
   * بررسی دسترسی **Fail-Closed** از طریق `BALE_ALLOWED_USERS` و `BALE_ALLOW_ALL_USERS`.
   * مدیریت خودکار خطای `429 Too Many Requests` (`retry_after`) و الگوریتم Exponential Backoff (`jittered_backoff`) در حلقه Polling.
   * پشتیبانی کامل از دریافت و ارسال رسانه (عکس، سند، ویس، صدا و ویدیو) با استفاده از `gateway/platforms/media_cache.py`.
   * پشتیبانی از دکمه‌های شیشه‌ای تایید دستورات حساس (`inline_keyboard` و `callback_query` متصل به `resolve_gateway_approval`).
2. **رابط کاربری دوحالته Noryka Studio (`web/index.html` و `noryka_cli/web_dist/index.html`):**
   * متصل به اندپوینت‌های واقعی بک‌اند FastAPI (`/api/status`, `/api/config`, `/api/env`, `/api/messaging/platforms`, `/api/model/set`, `/api/cron/jobs`, `/api/ws`) هنگام اجرا با دستور `noryka web`، همراه با حالت پیش‌نمایش مستقل (Standalone Fallback) و استایل‌های CSS داخلی برای کارکرد در شبکه‌های ضعیف یا آفلاین.
3. **نصب‌کننده ایمن Termux و Linux (`install-noryka-termux.sh`):**
   * ساخت محیط مجازی ایزوله با `python3 -m venv --system-site-packages ~/.noryka/venv` (بدون دست‌کاری مخرب `pip` سیستم در Termux و بدون پنهان‌کاری خطا با `|| true`) و نصب کامل extras مربوط به `[termux]` (شامل `python-telegram-bot` و `mcp`).

## نصب و اجرای تست‌های سلامت (Smoke Tests)

```bash
bash install-noryka-termux.sh
pytest tests/test_noryka_smoke.py
```
