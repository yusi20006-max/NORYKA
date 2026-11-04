# ⟐ ✦ ⟐ NORYKA — Autonomous Intelligence Core

<div align="center">

[docs/images/noryka-banner.jpg]

**An open-source, multi-platform autonomous AI agent and personal intelligence core.**  
*Native Bale Messenger (`tapi.bale.ai`) & Telegram gateways · Auto-Vision routing · Jalali Calendar & Market Radar · Android Termux Companion App*

[English](#-english) • [فارسی](#-فارسی) • [Quick Start](#-quick-start) • [Android App](#-android-companion-app) • [Bale Gateway](#-bale-messenger-integration) • [Features](#-key-features)

---

[[https://img.shields.io/badge/License-MIT-00F5FF.svg?style=for-the-badge]](LICENSE)
[[https://img.shields.io/badge/Release-v3.2.0-A855F7.svg?style=for-the-badge]](https://github.com/yusi20006-max/NORYKA/releases)
[[https://img.shields.io/badge/Python-3.10%2B-10B981.svg?style=for-the-badge&logo=python&logoColor=white]](https://python.org)
[[https://img.shields.io/badge/Platform-Android%20Termux%20%7C%20Linux-F59E0B.svg?style=for-the-badge&logo=android&logoColor=white]](https://termux.dev)
[[https://img.shields.io/badge/Gateway-Bale%20%26%20Telegram-38BDF8.svg?style=for-the-badge]](https://bale.ai)

</div>

---

<table align="center">
<tr>
<td width="50%" align="center">
<img src="docs/images/noryka-avatar.jpg" width="220" alt="Noryka Nova Star Avatar" style="border-radius: 24px; box-shadow: 0 8px 32px rgba(0,245,255,0.25);" />
<br />
<b>✦ Nova Star Emblem (نشان ستاره قطبی نُوا)</b>
<br />
<i>Official Bot Avatar & Android App Icon</i>
</td>
<td width="50%" align="center">
<img src="docs/images/noryka-splash.jpg" width="340" alt="Noryka Neon Cyberpunk Splash Screen" style="border-radius: 16px; box-shadow: 0 8px 32px rgba(168,85,247,0.25);" />
<br />
<b>🚀 Neon Cyberpunk Splash Screen</b>
<br />
<i>Terminal & Mobile Boot Animation</i>
</td>
</tr>
</table>

---

## 🌐 English

### ⚡ Overview
**Noryka** is an autonomous personal AI agent and software engineering core designed to run anywhere — from high-performance Linux servers to personal Android devices via **Termux**. It features out-of-the-box integration with Iranian native messenger **Bale (`tapi.bale.ai`)** alongside **Telegram**, **Discord**, and 45+ AI providers, equipped with automated Vision fallback, a Persian Personal Assistant Suite, and an Android Companion Controller app.

### 🌟 Key Features
* **Bale Messenger (`tapi.bale.ai`) & Telegram Native Gateways:**
  * Full channel post (`channel_post`) support with fail-closed authorization.
  * **Interactive Glass Panel (`Inline Keyboard`):** 10 instant buttons for commands (`/panel`, `/today`, `/market`, `/todo`, `/expense`, `/remind`, `/status`, `/model`, `/new`, `/stop`).
  * Automatic `setMyCommands` registration on connect.
* **Vision Auto-Routing:**
  * Automatically switches to multimodal vision models (`google/gemma-3-27b-it:free`, `qwen2.5-vl`, `gemini-2.5-flash`) when photos are sent, even if the primary model is text-only.
* **Persian Personal Assistant Suite (LifeOS):**
  * **Jalali / Shamsi Calendar (`/today`):** Exact date conversion, daily briefing, open task summary.
  * **Live Iranian & Global Market Radar (`/market`):** Real-time Tether (USDT), USD, 18K Gold, and Bitcoin prices in Toman via Nobitex.
  * **Personal Accounting (`/expense`):** Natural Persian expense logging (`/expense 250000 ناهار`).
  * **Smart Reminders (`/remind`):** Background timer alerts in chats/channels.
* **Gemini-Style Mobile Studio UI:**
  * Clean dark-mode web console with a slide-out navigation drawer (`☰`), horizontal scroll lock, and floating pill input.
* **Android Companion App (`Noryka.apk`):**
  * Native Kotlin controller that launches the background daemon inside Termux without opening the terminal window.

---

## 🇮🇷 فارسی

### ⚡ معرفی پروژه
**نوریکا (Noryka)** یک پلتفرم دستیار شخصی هوشمند و مهندس نرم‌افزار خودگردان است که برای اجرا روی سرورهای لینوکس و گوشی‌های هوشمند اندروید (از طریق **Termux**) بازطراحی شده است. نوریکا به‌صورت بومی از **پیام‌رسان بله (`tapi.bale.ai`)** و **تلگرام** پشتیبانی کرده و با اتصال به بیش از ۴۵ ارائه‌دهنده هوش مصنوعی، مسیریابی خودکار بینایی ماشین، دفتر حسابداری تومانی و تقویم شمسی را در قالب یک هسته قدرتمند در اختیارتان می‌گذارد.

### 🌟 قابلیت‌های برجسته
* **دروازه بومی پیام‌رسان بله و تلگرام:**
  * پشتیبانی کامل از چت خصوصی، گروه‌ها و **کانال‌های بله (`channel_post`)**.
  * **پنل دکمه‌های شیشه‌ای (`Inline Keyboard`):** دسترسی سریع با یک لمس به تمام دستورات کنترلی در چت و کانال بله.
  * ثبت خودکار منوی دستورات اسلش‌دار با `setMyCommands`.
* **مسیریابی هوشمند بینایی ماشین (`Vision Auto-Routing`):**
  * حتی در صورت استفاده از مدل‌های متنی رایگان (مثل Nemotron)، به محض ارسال عکس در بله یا تلگرام، نوریکا خودکار عکس را با مدل‌های بینایی ماشین پردازش می‌کند.
* **دستیار شخصی بومی (LifeOS):**
  * **📅 تقویم شمسی و بریفینگ (`/today`):** تبدیل دقیق تاریخ جلالی و خلاصه کارهای روزانه.
  * **💰 رادار زنده بازار و ارز (`/market`):** نمایش آنی قیمت تتر، دلار، طلای ۱۸ عیار و رمزارزها به تومان.
  * **💳 حسابداری شخصی (`/expense`):** ثبت مخارج به تومان با زبان محاوره‌ای فارسی.
  * **⏰ یادآور هوشمند (`/remind`):** هشدار دقیق سر ساعت در بله.
* **رابط استودیویی به سبک Google Gemini:**
  * طراحی موبایل‌محور با منوی کشویی بازشونده (`☰`)، قفل کامل تکان افقی و کادر پیام کپسولی شناور.
* **کنترلگر مستقل اندروید (`Noryka.apk`):**
  * اپلیکیشن نیتیو با زبان Kotlin که حتی در صورت بسته بودن برنامه ترموکس، موتور نوریکا را در پس‌زمینه بیدار می‌کند.

---

## 🚀 Quick Start

### Installation on Linux / Termux

```bash
# 1. Clone repository
git clone [https://github.com/yusi20006-max/NORYKA.git](https://github.com/yusi20006-max/NORYKA.git)
cd NORYKA

# 2. Install package in editable mode
pip install -e .

# 3. Configure API keys (interactive prompt)
noryka model

Essential CLI Commands
noryka                    # Start interactive agent console
noryka gateway            # Run Bale & Telegram messaging gateway
noryka app                # Background daemon launcher & open mobile studio
noryka app status         # Live health check of services, Bale latency & RAM
noryka app panel          # Send the 10-button Glass Panel directly to Bale
noryka about              # Display Noryka Nova Star identity card

📱 Android Companion App
The repository includes a complete native Kotlin Android app located in the android/ directory.
NORYKA/
├── android/
│   ├── app/
│   │   ├── src/main/java/ai/noryka/companion/MainActivity.kt
│   │   └── src/main/AndroidManifest.xml
│   └── build.gradle.kts
└── .github/workflows/android.yml

Automated APK Builds
Every push to the main branch automatically triggers the GitHub Actions Workflow which compiles and releases Noryka.apk in the Releases section.
Zero-Touch Background Termux Wake
Using Android's official com.termux.permission.RUN_COMMAND, the companion app wakes the Noryka engine and Bale Gateway in the background on launch — no need to manually keep Termux open!
💬 Bale Messenger Integration
To connect Noryka to Bale Messenger (tapi.bale.ai):
 * Get a bot token from @BotFather on Bale.
 * Add your token and numeric user ID to ~/.noryka/.env:
   BALE_BOT_TOKEN="123456789:YOUR_BALE_TOKEN"
BALE_ALLOWED_USERS="1041795208"
BALE_HOME_CHANNEL=""  # Optional channel ID

 * Run the gateway:
   noryka gateway

 * In your chat or channel on Bale, send پنل or /panel to reveal the interactive glass control board.
📄 License
This project is licensed under the MIT License — see the LICENSE file for details.
All legacy third-party notices and attribution are preserved in accordance with their respective open-source licenses.
