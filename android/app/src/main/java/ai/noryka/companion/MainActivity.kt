package ai.noryka.companion

import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.webkit.WebChromeClient
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

class MainActivity : AppCompatActivity() {
    private val studioUrl = "http://127.0.0.1:8080"
    private val healthUrl = "$studioUrl/api/health"
    private val controlUrl = "$studioUrl/api/app-control"
    private val termuxPermission = "com.termux.permission.RUN_COMMAND"

    private lateinit var statusDot: TextView
    private lateinit var statusLabel: TextView
    private lateinit var offlineContainer: LinearLayout
    private lateinit var webView: WebView

    private val handler = Handler(Looper.getMainLooper())
    private var isEngineOnline = false
    private var autoWakeTriggered = false

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = Color.parseColor("#020617")

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.parseColor("#020617"))
            layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
        }

        val topBar = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.parseColor("#0F172A"))
            setPadding(28, 20, 28, 20)
        }
        val headerRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        val brandTitle = TextView(this).apply {
            text = "✦ NORYKA"
            setTextColor(Color.parseColor("#00F5FF"))
            textSize = 15f
            typeface = Typeface.DEFAULT_BOLD
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        statusDot = TextView(this).apply { text = "🟠 "; textSize = 12f }
        statusLabel = TextView(this).apply {
            text = "بررسی موتور Termux..."
            setTextColor(Color.parseColor("#CBD5E1"))
            textSize = 12f
            typeface = Typeface.DEFAULT_BOLD
        }
        headerRow.addView(brandTitle); headerRow.addView(statusDot); headerRow.addView(statusLabel)

        val scroll = HorizontalScrollView(this).apply { isHorizontalScrollBarEnabled = false; setPadding(0, 16, 0, 0) }
        val btnRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }

        btnRow.addView(makeActionButton("🚀 روشن کردن موتور", "#059669") { runTermuxCommand("start", "در حال روشن کردن موتور نوریکا و گیت‌وی بله در پس‌زمینه...") })
        btnRow.addView(makeActionButton("📡 رادار سلامت", "#0284C7") {
            if (isEngineOnline) webView.evaluateJavascript("if(typeof switchTab==='function') switchTab('health');", null)
            else checkHealthNow(true)
        })
        btnRow.addView(makeActionButton("🎛 پنل شیشه‌ای بله", "#7C3AED") { postControlAction("panel", "پنل ۱۰ دکمه شیشه‌ای به بله ارسال شد!") })
        btnRow.addView(makeActionButton("🔄 ری‌استارت", "#4F46E5") { runTermuxCommand("restart", "در حال راه‌اندازی مجدد سرویس‌ها...") })
        btnRow.addView(makeActionButton("🧹 پاکسازی کش", "#475569") { postControlAction("clean", "کش و لاگ‌های موقت پاکسازی شدند.") })
        btnRow.addView(makeActionButton("⏹ توقف کامل", "#E11D48") { runTermuxCommand("stop", "سرویس‌های پس‌زمینه متوقف شدند.") })

        scroll.addView(btnRow)
        topBar.addView(headerRow); topBar.addView(scroll)
        root.addView(topBar)

        offlineContainer = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(64, 64, 64, 64)
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f)
        }
        val starLogo = TextView(this).apply {
            text = "⟐ ✦ ⟐"
            setTextColor(Color.parseColor("#00F5FF"))
            textSize = 36f
            typeface = Typeface.DEFAULT_BOLD
            gravity = Gravity.CENTER
        }
        val offlineTitle = TextView(this).apply {
            text = "NORYKA · Autonomous Intelligence Core"
            setTextColor(Color.WHITE)
            textSize = 17f
            typeface = Typeface.DEFAULT_BOLD
            gravity = Gravity.CENTER
            setPadding(0, 24, 0, 12)
        }
        val offlineDetail = TextView(this).apply {
            text = "در حال بیدارسازی خودکار موتور نوریکا در پس‌زمینه Termux...\n(نیازی به باز بودن برنامه Termux نیست)"
            setTextColor(Color.parseColor("#94A3B8"))
            textSize = 13f
            gravity = Gravity.CENTER
            setPadding(0, 0, 0, 40)
        }
        val wakeBtn = makeActionButton("⚡ بیدارسازی فوری موتور در پس‌زمینه Termux", "#0891B2") {
            runTermuxCommand("start", "فرمان بیدارسازی به هسته Termux ارسال شد...")
        }
        offlineContainer.addView(starLogo); offlineContainer.addView(offlineTitle); offlineContainer.addView(offlineDetail); offlineContainer.addView(wakeBtn)
        root.addView(offlineContainer)

        webView = WebView(this).apply {
            visibility = View.GONE
            setBackgroundColor(Color.parseColor("#020617"))
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f)
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.cacheMode = WebSettings.LOAD_DEFAULT
            webViewClient = WebViewClient()
            webChromeClient = WebChromeClient()
        }
        root.addView(webView)

        setContentView(root)
        if (ContextCompat.checkSelfPermission(this, termuxPermission) != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this, arrayOf(termuxPermission), 101)
        }
        startHealthLoop()
    }

    private fun makeActionButton(title: String, hexColor: String, onClick: () -> Unit): Button {
        val bg = GradientDrawable().apply { cornerRadius = 24f; setColor(Color.parseColor(hexColor)) }
        return Button(this).apply {
            text = title; setTextColor(Color.WHITE); textSize = 11.5f; isAllCaps = false; background = bg
            setPadding(32, 16, 32, 16)
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { setMargins(8, 0, 8, 0) }
            setOnClickListener { onClick() }
        }
    }

    private fun runTermuxCommand(subAction: String, toastMessage: String) {
        Toast.makeText(this, toastMessage, Toast.LENGTH_SHORT).show()
        try {
            val intent = Intent().apply {
                setClassName("com.termux", "com.termux.app.RunCommandService")
                action = "com.termux.RUN_COMMAND"
                putExtra("com.termux.RUN_COMMAND_PATH", "/data/data/com.termux/files/usr/bin/noryka")
                putExtra("com.termux.RUN_COMMAND_ARGUMENTS", arrayOf("app", subAction))
                putExtra("com.termux.RUN_COMMAND_WORKDIR", "/data/data/com.termux/files/home")
                putExtra("com.termux.RUN_COMMAND_BACKGROUND", true)
            }
            startService(intent)
        } catch (_: Exception) {
            Toast.makeText(this, "لطفاً مجوز Run commands in Termux را فعال کنید.", Toast.LENGTH_LONG).show()
        }
        handler.postDelayed({ checkHealthNow(false) }, 1800)
    }

    private fun postControlAction(actionName: String, successMsg: String) {
        thread {
            try {
                val conn = (URL(controlUrl).openConnection() as HttpURLConnection).apply {
                    requestMethod = "POST"; connectTimeout = 4000; readTimeout = 8000; doOutput = true
                    setRequestProperty("Content-Type", "application/json")
                }
                OutputStreamWriter(conn.outputStream).use { it.write("{\"action\":\"$actionName\"}") }
                val code = conn.responseCode
                handler.post { Toast.makeText(this, if (code in 200..299) "✦ $successMsg" else "خطا ($code)", Toast.LENGTH_SHORT).show() }
            } catch (_: Exception) {
                handler.post { Toast.makeText(this, "موتور خاموش است؛ ابتدا دکمه «🚀 روشن کردن موتور» را بزنید.", Toast.LENGTH_SHORT).show() }
            }
        }
    }

    private fun startHealthLoop() {
        checkHealthNow(true)
        handler.postDelayed(object : Runnable {
            override fun run() { checkHealthNow(false); handler.postDelayed(this, 4000) }
        }, 4000)
    }

    private fun checkHealthNow(allowAutoWake: Boolean) {
        thread {
            var reachable = false
            try {
                val conn = (URL(healthUrl).openConnection() as HttpURLConnection).apply { requestMethod = "GET"; connectTimeout = 1500; readTimeout = 1500 }
                reachable = (conn.responseCode in 200..299)
            } catch (_: Exception) { reachable = false }
            handler.post {
                if (reachable) {
                    statusDot.text = "🟢 "; statusLabel.text = "آنلاین (127.0.0.1:8080)"
                    if (!isEngineOnline) {
                        isEngineOnline = true; offlineContainer.visibility = View.GONE; webView.visibility = View.VISIBLE; webView.loadUrl(studioUrl)
                    }
                } else {
                    isEngineOnline = false; statusDot.text = "🔴 "; statusLabel.text = "موتور متوقف است"
                    webView.visibility = View.GONE; offlineContainer.visibility = View.VISIBLE
                    if (allowAutoWake && !autoWakeTriggered) {
                        autoWakeTriggered = true; statusDot.text = "🟠 "; statusLabel.text = "در حال بیدارسازی خودکار..."
                        runTermuxCommand("start", "بیدارسازی خودکار موتور نوریکا در پس‌زمینه...")
                    }
                }
            }
        }
    }
}
