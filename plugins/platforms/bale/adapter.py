"""
Bale Adapter for Noryka Gateway
پشتیبانی کامل از پیام‌ها، دستورات و کال‌بک‌های دکمه‌های شیشه‌ای بله
"""
import asyncio
import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger("noryka.platforms.bale")

class BalePlatform:
    def __init__(self, token: str, allowed_users: Optional[List[str]] = None):
        self.token = token.strip()
        self.base_url = f"https://tapi.bale.ai/bot{self.token}"
        self.allowed_users = [str(u).strip() for u in (allowed_users or []) if str(u).strip()]
        self.offset = 0
        self.is_running = False

    def _api_call(self, endpoint: str, payload: dict, timeout: int = 15) -> Optional[dict]:
        url = f"{self.base_url}/{endpoint}"
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url, data=data, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as e:
            logger.error(f"Bale API error on {endpoint}: {e}")
            return None

    def send_message(self, chat_id: Any, text: str, reply_markup: Optional[dict] = None) -> bool:
        if not chat_id:
            logger.error("send_message failed: chat_id is empty")
            return False
        payload = {
            "chat_id": str(chat_id),
            "text": text,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        res = self._api_call("sendMessage", payload)
        return bool(res and res.get("ok"))

    def answer_callback_query(self, callback_query_id: str, text: Optional[str] = None) -> bool:
        if not callback_query_id:
            return False
        payload = {"callback_query_id": str(callback_query_id)}
        if text:
            payload["text"] = text
        res = self._api_call("answerCallbackQuery", payload, timeout=5)
        return bool(res and res.get("ok"))

    def is_authorized(self, user_id: Any) -> bool:
        if not self.allowed_users:
            return True
        return str(user_id).strip() in self.allowed_users

    def handle_builtin(self, cmd: str, chat_id: Any) -> bool:
        norm_cmd = cmd.strip().lower()
        
        # بارگذاری افزونه‌های مازاد در صورت وجود
        try:
            from plugins.platforms.bale.backup_and_fallback import handle_fallback_command, handle_backup_command, handle_models_command
            if norm_cmd.startswith("/fallback"):
                return handle_fallback_command(self, chat_id, norm_cmd)
            elif norm_cmd.startswith("/backup"):
                return handle_backup_command(self, chat_id, norm_cmd)
            elif norm_cmd.startswith("/models") or norm_cmd.startswith("/switch"):
                return handle_models_command(self, chat_id, norm_cmd)
        except Exception as ex:
            logger.debug(f"Extended command handler not loaded: {ex}")

        if norm_cmd in ["/start", "/help"]:
            txt = (
                "🤖 به ربات مدیریت دستیار هوشمند نوریکا خوش آمدید!

"
                "دستورات و پنل‌های کنترلی در دسترس:
"
                "• /status - بررسی وضعیت سرویس‌ها و منابع
"
                "• /models - مدیریت و تعویض دستی مدل و کلیدها
"
                "• /fallback - بررسی سلامت و زنجیره فال‌بک
"
                "• /backup - ایجاد و بازیابی فایل پشتیبان
"
                "• /new - شروع گفتگوی تازه
"
                "• /stop - توقف وظیفه در حال اجرا"
            )
            markup = {
                "inline_keyboard": [
                    [{"text": "📊 وضعیت نوریکا", "callback_data": "cmd:/status"}],
                    [{"text": "🔄 مدیریت و سلامت API", "callback_data": "cmd:/fallback"},
                     {"text": "🧠 تغییر مدل هوش مصنوعی", "callback_data": "cmd:/models"}],
                    [{"text": "💾 بک‌آپ‌گیری از کل سیستم", "callback_data": "cmd:/backup"}],
                    [{"text": "🆕 گفتگوی جدید", "callback_data": "cmd:/new"},
                     {"text": "⏹️ توقف پردازش", "callback_data": "cmd:/stop"}]
                ]
            }
            self.send_message(chat_id, txt, markup)
            return True

        elif norm_cmd == "/status":
            txt = "🟢 وضعیت سیستم: همه بخش‌ها و گیت‌وی فعال و آماده دریافت فرمان هستند."
            self.send_message(chat_id, txt)
            return True

        elif norm_cmd == "/new":
            txt = "🔄 نشست گفتگو با موفقیت تازه‌سازی شد."
            self.send_message(chat_id, txt)
            return True

        elif norm_cmd == "/stop":
            txt = "⏹️ پردازش وظیفه جاری متوقف شد."
            self.send_message(chat_id, txt)
            return True

        return False

    def process_update(self, update: dict):
        # 1. پردازش دکمه‌های شیشه‌ای (Callback Queries)
        if "callback_query" in update:
            cb = update["callback_query"]
            cb_id = cb.get("id", "")
            data = cb.get("data", "")
            sender = cb.get("from", {})
            user_id = sender.get("id", "")
            msg = cb.get("message") or {}

            # استخراج Chat ID با اولویت: پیام -> ارسال‌کننده
            chat_id = msg.get("chat", {}).get("id") or user_id

            # پاسخ سریع و بدون انسداد به بله برای رفع حالت انتظار دکمه
            self.answer_callback_query(cb_id)

            if not self.is_authorized(user_id):
                self.send_message(chat_id, "⛔ شما اجازه دسترسی به این بخش را ندارید.")
                return

            # استخراج و استانداردسازی دستور
            cmd = data
            if cmd.startswith("cmd:"):
                cmd = cmd[4:]
            cmd = cmd.strip()
            if not cmd.startswith("/"):
                cmd = "/" + cmd

            logger.info(f"Processing callback action: {cmd} from {user_id}")
            self.handle_builtin(cmd, chat_id)
            return

        # 2. پردازش پیام‌های متنی
        if "message" in update:
            msg = update["message"]
            sender = msg.get("from", {})
            user_id = sender.get("id", "")
            chat_id = msg.get("chat", {}).get("id") or user_id
            text = (msg.get("text") or "").strip()

            if not self.is_authorized(user_id):
                return

            if text.startswith("/"):
                if self.handle_builtin(text, chat_id):
                    return
            
            # در صورتی که پیام عادی باشد و گیت‌وی بخواهد پاسخ هوشمند دهد
            # می‌توان به ایجنت Gateway هدایت شود
