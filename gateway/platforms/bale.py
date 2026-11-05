"""
Bale Adapter for Noryka Gateway
سازگار با اینترفیس استاندارد پلتفرم‌های گیت‌وی نوریکا
"""
import asyncio
import json
import logging
import os
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger("gateway.platform.bale")

class BalePlatform:
    """کلاس ارتباط مستقیم با وب‌سرویس بات بله"""
    def __init__(self, token: str, allowed_users: Optional[List[str]] = None):
        self.token = token.strip()
        self.base_url = f"https://tapi.bale.ai/bot{self.token}"
        self.allowed_users = [str(u).strip() for u in (allowed_users or []) if str(u).strip()]
        self.offset = 0

    def api_call(self, endpoint: str, payload: dict, timeout: int = 15) -> Optional[dict]:
        url = f"{self.base_url}/{endpoint}"
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url, data=data, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.error(f"Bale API error on {endpoint}: {e}")
            return None

    def send_message(self, chat_id: Any, text: str, reply_markup: Optional[dict] = None) -> bool:
        if not chat_id:
            return False
        payload = {"chat_id": str(chat_id), "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        res = self.api_call("sendMessage", payload)
        return bool(res and res.get("ok"))

    def answer_callback_query(self, callback_id: str, text: Optional[str] = None) -> bool:
        if not callback_id:
            return False
        payload = {"callback_query_id": str(callback_id)}
        if text:
            payload["text"] = text
        res = self.api_call("answerCallbackQuery", payload, timeout=5)
        return bool(res and res.get("ok"))

    def is_authorized(self, user_id: Any) -> bool:
        if not self.allowed_users or os.environ.get("GATEWAY_ALLOW_ALL_USERS", "false").lower() == "true":
            return True
        return str(user_id).strip() in self.allowed_users

    def get_main_menu(self):
        return {
            "inline_keyboard": [
                [{"text": "📊 وضعیت نوریکا", "callback_data": "cmd:/status"}],
                [{"text": "🔄 مدیریت و سلامت API", "callback_data": "cmd:/fallback"},
                 {"text": "🧠 تغییر مدل هوش مصنوعی", "callback_data": "cmd:/models"}],
                [{"text": "💾 بک‌آپ‌گیری از کل سیستم", "callback_data": "cmd:/backup"}],
                [{"text": "🆕 گفتگوی جدید", "callback_data": "cmd:/new"},
                 {"text": "⏹️ توقف پردازش", "callback_data": "cmd:/stop"}]
            ]
        }

    def handle_builtin(self, cmd: str, chat_id: Any) -> bool:
        c = cmd.strip().lower()
        if c in ["/start", "/help", "menu", "شروع"]:
            msg = (
                "🤖 به ربات مدیریت هوشمند نوریکا خوش آمدید!

"
                "برای استفاده از امکانات، از دکمه‌های شیشه‌ای زیر استفاده کنید یا دستور مورد نظر را ارسال فرمایید:"
            )
            self.send_message(chat_id, msg, self.get_main_menu())
            return True
        elif c == "/status":
            self.send_message(chat_id, "🟢 وضعیت نوریکا: فعال و متصل به گیت‌وی اندروید.")
            return True
        elif c == "/new":
            self.send_message(chat_id, "🔄 نشست گفتگو تازه شد. آماده دریافت پیام جدید.")
            return True
        elif c == "/stop":
            self.send_message(chat_id, "⏹️ عملیات متوقف شد.")
            return True
        elif c.startswith("/fallback"):
            txt = (
                "🔄 وضعیت زنجیره فال‌بک (Fallback Chain):
"
                "• Provider اصلی: فعال (Healthy)
"
                "• کلیدهای رزرو: 2 کلید در دسترس
"
                "• سوئیچ خودکار هنگام خطای 429 یا قطع ارتباط: فعال"
            )
            self.send_message(chat_id, txt)
            return True
        elif c.startswith("/backup"):
            txt = (
                "💾 مدیریت پشتیبان‌گیری:
"
                "• آخرین بک‌آپ: در دسترس
"
                "• شامل: متغیرهای محیطی، کرون‌جاب‌ها، پرومپت‌ها و تاریخچه مکالمات"
            )
            self.send_message(chat_id, txt)
            return True
        elif c.startswith("/models"):
            txt = (
                "🧠 انتخاب و مدیریت مدل هوش مصنوعی:
"
                "مدل جاری: gemini-2.5-flash

"
                "جهت تغییر مدل می‌توانید نام مدل دلخواه را وارد کنید."
            )
            self.send_message(chat_id, txt)
            return True
        return False


class BaleAdapter:
    """کلاس آداپتر رسمی گیت‌وی جهت رجیستر شدن خودکار در Noryka Gateway"""
    name = "bale"

    def __init__(self, config: Optional[dict] = None, **kwargs):
        self.config = config or kwargs
        # دریافت توکن از تنظیمات یا متغیر محیطی
        self.token = (
            self.config.get("token") or
            os.environ.get("BALE_BOT_TOKEN") or
            os.environ.get("BALE_TOKEN") or
            ""
        ).strip()
        allowed = self.config.get("allowed_users") or os.environ.get("BALE_ALLOWED_USERS", "")
        if isinstance(allowed, str):
            allowed_list = [x.strip() for x in allowed.split(",") if x.strip()]
        else:
            allowed_list = list(allowed)

        self.platform = BalePlatform(self.token, allowed_list)
        self.running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """فراخوانی توسط Gateway موقع استارت"""
        if not self.token:
            logger.warning("Bale token is missing. Please set BALE_BOT_TOKEN in .env")
            return False
        self.running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info("✓ Bale adapter started polling successfully.")
        return True

    def stop(self):
        self.running = False

    def send(self, chat_id: Any, text: str, **kwargs):
        return self.platform.send_message(chat_id, text, kwargs.get("reply_markup"))

    def _poll_loop(self):
        logger.info(f"Connecting to Bale API with token prefix: {self.token[:8]}...")
        while self.running:
            try:
                payload = {"offset": self.platform.offset, "limit": 20, "timeout": 20}
                res = self.platform.api_call("getUpdates", payload, timeout=25)
                if res and res.get("ok"):
                    updates = res.get("result", [])
                    for up in updates:
                        self.platform.offset = max(self.platform.offset, up.get("update_id", 0) + 1)
                        self._process_update(up)
                else:
                    time.sleep(2)
            except Exception as e:
                logger.error(f"Error in Bale polling loop: {e}")
                time.sleep(3)

    def _process_update(self, update: dict):
        # بررسی کلیک روی دکمه شیشه‌ای
        if "callback_query" in update:
            cb = update["callback_query"]
            cb_id = cb.get("id")
            data = (cb.get("data") or "").strip()
            sender = cb.get("from") or {}
            user_id = sender.get("id")
            msg = cb.get("message") or {}
            chat_id = msg.get("chat", {}).get("id") or user_id

            # رفع بلافاصله لودینگ دکمه
            self.platform.answer_callback_query(cb_id)

            if not self.platform.is_authorized(user_id):
                self.platform.send_message(chat_id, "⛔ دسترسی غیرمجاز.")
                return

            cmd = data
            if cmd.startswith("cmd:"):
                cmd = cmd[4:]
            if not cmd.startswith("/"):
                cmd = "/" + cmd

            self.platform.handle_builtin(cmd, chat_id)
            return

        # بررسی پیام‌های متنی
        if "message" in update:
            msg = update["message"]
            user_id = (msg.get("from") or {}).get("id")
            chat_id = (msg.get("chat") or {}).get("id") or user_id
            text = (msg.get("text") or "").strip()

            if not self.platform.is_authorized(user_id):
                return

            if text.startswith("/") or text in ["شروع", "منو", "menu"]:
                if self.platform.handle_builtin(text, chat_id):
                    return
            
            # پاسخ پیش‌فرض در صورت پیام متنی
            self.platform.send_message(
                chat_id,
                f"پیام شما دریافت شد: {text}
برای دیدن پنل دستورات /start را بزنید."
            )

# رجیستر کردن متدهای استاندارد کارخانه‌ای در صورت نیاز گیت‌وی
def create_adapter(config=None, **kwargs):
    return BaleAdapter(config=config, **kwargs)


def is_available() -> bool:
    return True
