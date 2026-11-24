package com.autostronghold.app

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.text.InputType
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.method.ScrollingMovementMethod
import android.text.style.ForegroundColorSpan
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

/**
 * The program window on Android: device and feature on top, then options, the start
 * button, status and log. Visual language follows the Windows window (autostronghold/gui.py).
 */
class MainActivity : Activity(), RunState.Listener {
    companion object {
        private const val BG = 0xFF111316.toInt()
        private const val HEADER = 0xFF0B0D0F.toInt()
        private const val PANEL = 0xFF181B1F.toInt()
        private const val PANEL_HI = 0xFF20242A.toInt()
        private const val LINE = 0xFF2A2F36.toInt()
        private const val TEXT = 0xFFE4E8EB.toInt()
        private const val DIM = 0xFF8B949C.toInt()
        private const val FAINT = 0xFF5C656E.toInt()
        private const val ACCENT = 0xFF21D3A8.toInt()
        private const val ACCENT_INK = 0xFF06231C.toInt()
        private const val WARN = 0xFFF2B33D.toInt()
        private const val ERROR = 0xFFEF5B5B.toInt()
        private const val OK = 0xFF3DDC97.toInt()
        private val LEVEL_COLOURS = mapOf("info" to TEXT, "ok" to OK, "warn" to WARN, "error" to ERROR, "debug" to FAINT)
        private const val REQ_CAPTURE = 1
        private val GAME_PACKAGES = listOf("com.hypergryph.arknights", "com.hypergryph.arknights.bilibili")
        private val STATUS_LABELS = listOf("state" to "运行状态", "screen" to "当前画面", "stage" to "阶段",
            "round" to "回合", "games" to "对局（通关）", "elapsed" to "运行时长")
        private const val STARTUP_GUIDE = """运行前请确认：
1. 客户端为国服中文版，卫戍协议「更换主题」为默认主题。
2. 屏幕为 16:9（例如 1920×1080 的平板或模拟器）。屏幕比例不是 16:9 的手机（如 20:9）无法使用。
3. 首次使用时开启无障碍服务「AutoStronghold 触控」（用于点击和拖动）。安卓 13 起，从安装包安装的应用需先在「应用信息 → 右上角菜单」中「允许受限制的设置」。
4. 每次点「开始」都要允许「录制或投射屏幕」，请选择「整个屏幕」。之后程序自动切换到明日方舟。
5. 进入「卫戍协议」开始界面（右下角显示「个人模拟」/「联合模拟」）。运行期间不要触碰屏幕，也不要同时运行 MAA 等其他自动化程序；在通知栏点「停止」即可停止。"""
    }

    private val handler = Handler(Looper.getMainLooper())
    private val prefs by lazy { getSharedPreferences("settings", Context.MODE_PRIVATE) }
    private lateinit var featureBox: LinearLayout
    private lateinit var touchNote: TextView
    private lateinit var maxGames: EditText
    private lateinit var skipSpeed: CheckBox
    private lateinit var startButton: Button
    private lateinit var checkButton: Button
    private lateinit var logView: TextView
    private lateinit var titleView: TextView
    private val statusViews = mutableMapOf<String, TextView>()
    private val featureCards = mutableMapOf<String, LinearLayout>()
    private var feature: String = ""
    private var loaded = false
    private var pendingCheck = false
    private val tick = object : Runnable {
        override fun run() {
            statusViews["elapsed"]?.text = RunState.elapsed().ifEmpty { statusViews["elapsed"]?.text ?: "—" }
            handler.postDelayed(this, 1000)
        }
    }

    private fun dp(n: Int) = (n * resources.displayMetrics.density).toInt()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = HEADER
        window.navigationBarColor = BG
        feature = prefs.getString("feature", "") ?: ""
        setContentView(build())
        RunState.lines.forEach { onLine(it) }
        onStatus()
        RunState.addListener(this)
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 2)
        }
        Thread {
            val result = runCatching { PythonHost.setup(applicationContext) }
            handler.post { result.fold(::showFeatures) { RunState.say("程序初始化失败：${it.message ?: it}", "error") } }
        }.start()
        if (RunState.lines.isEmpty()) RunState.say("运行前请先阅读右上角的「运行前须知」。", "warn")
        handler.post(tick)
    }

    override fun onResume() {
        super.onResume()
        refreshTouchNote()
    }

    override fun onDestroy() {
        RunState.removeListener(this)
        handler.removeCallbacks(tick)
        super.onDestroy()
    }

    // --- layout ------------------------------------------------------------------
    private fun build(): View {
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setBackgroundColor(BG) }
        val header = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setBackgroundColor(HEADER)
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(16), dp(12), dp(12), dp(12))
        }
        val titles = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        titleView = text("AutoStronghold", 20, TEXT, bold = true)
        titles.addView(titleView)
        titles.addView(text("卫戍协议自动刷角标 · 安卓版", 11, DIM, bold = true))
        header.addView(titles, LinearLayout.LayoutParams(0, -2, 1f))
        header.addView(button("⚠ 运行前须知", WARN, 0xFF2B1D00.toInt(), 13) { showGuide() })
        root.addView(header)

        val body = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(12), dp(12), dp(12), dp(12)) }
        val scroll = ScrollView(this).apply { addView(body) }
        root.addView(scroll, LinearLayout.LayoutParams(-1, 0, 1f))

        section(body, "设备", "Device").apply {
            addView(card("本机（安卓）", "录屏截图 + 无障碍服务点击和拖动；屏幕需为 16:9", selected = true))
            touchNote = text("", 12, WARN, bold = true).apply { setPadding(0, dp(6), 0, 0); setOnClickListener { openAccessibility() } }
            addView(touchNote)
        }
        featureBox = section(body, "功能", "Feature")
        featureBox.addView(text("正在加载…", 12, DIM))

        section(body, "选项", "Options").apply {
            val row = LinearLayout(this@MainActivity).apply { gravity = Gravity.CENTER_VERTICAL }
            row.addView(text("最多进行", 13, DIM))
            maxGames = EditText(this@MainActivity).apply {
                inputType = InputType.TYPE_CLASS_NUMBER
                setText(prefs.getInt("maxGames", 0).toString())
                setTextColor(TEXT)
                textSize = 13f
                gravity = Gravity.CENTER
                background = box(PANEL_HI, LINE)
                setPadding(dp(8), dp(4), dp(8), dp(4))
            }
            row.addView(maxGames, LinearLayout.LayoutParams(dp(64), -2).apply { setMargins(dp(8), 0, dp(8), 0) })
            row.addView(text("局（0 = 不限）", 13, DIM))
            addView(row)
            skipSpeed = CheckBox(this@MainActivity).apply {
                text = "全角标功能直接从「独立模拟·规程等级1」开始"
                setTextColor(TEXT)
                textSize = 13f
                buttonTintList = android.content.res.ColorStateList.valueOf(ACCENT)
                isChecked = prefs.getBoolean("skipSpeed", false)
            }
            addView(skipSpeed)
        }

        checkButton = button("连接自检", PANEL, TEXT, 14) { start(check = true) }.apply { background = box(PANEL, LINE) }
        body.addView(checkButton, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(12) })
        startButton = button("开  始", ACCENT, ACCENT_INK, 17) { start(check = false) }
        body.addView(startButton, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(8) })

        section(body, "状态", "Status").apply {
            STATUS_LABELS.chunked(2).forEach { pair ->
                val row = LinearLayout(this@MainActivity)
                pair.forEach { (key, label) ->
                    val cell = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.VERTICAL; setPadding(0, dp(4), 0, dp(4)) }
                    cell.addView(text(label, 11, FAINT))
                    val value = text("—", 15, TEXT, bold = true)
                    statusViews[key] = value
                    cell.addView(value)
                    row.addView(cell, LinearLayout.LayoutParams(0, -2, 1f))
                }
                addView(row)
            }
        }

        section(body, "日志", "Log").apply {
            logView = text("", 12, TEXT).apply {
                setBackgroundColor(0xFF0D0F12.toInt())
                setPadding(dp(10), dp(8), dp(10), dp(8))
                movementMethod = ScrollingMovementMethod()
                isVerticalScrollBarEnabled = true
                setTextIsSelectable(false)
                setOnTouchListener { v, e ->
                    v.parent.requestDisallowInterceptTouchEvent(e.action != MotionEvent.ACTION_UP)
                    false
                }
            }
            addView(logView, LinearLayout.LayoutParams(-1, dp(360)))
        }
        body.addView(text("许可证", 12, FAINT).apply {
            gravity = Gravity.CENTER
            setPadding(0, dp(14), 0, dp(4))
            setOnClickListener { showLicenses() }
        })
        return root
    }

    private fun text(s: String, size: Int, colour: Int, bold: Boolean = false) = TextView(this).apply {
        text = s
        textSize = size.toFloat()
        setTextColor(colour)
        if (bold) typeface = Typeface.DEFAULT_BOLD
    }

    private fun box(fill: Int, stroke: Int) = GradientDrawable().apply {
        setColor(fill)
        setStroke(dp(1), stroke)
        cornerRadius = dp(2).toFloat()
    }

    private fun button(label: String, fill: Int, ink: Int, size: Int, onClick: () -> Unit) = Button(this).apply {
        text = label
        textSize = size.toFloat()
        setTextColor(ink)
        typeface = Typeface.DEFAULT_BOLD
        isAllCaps = false
        background = box(fill, fill)
        setPadding(dp(14), dp(10), dp(14), dp(10))
        stateListAnimator = null
        setOnClickListener { onClick() }
    }

    /** Card with a Chinese title, a small English caption and a thin teal rule; returns its body. */
    private fun section(parent: LinearLayout, title: String, caption: String): LinearLayout {
        val card = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            background = box(PANEL, LINE)
            setPadding(dp(14), dp(12), dp(14), dp(12))
        }
        val head = LinearLayout(this).apply { gravity = Gravity.BOTTOM }
        head.addView(text(title, 16, TEXT, bold = true))
        head.addView(text(caption.uppercase(), 10, ACCENT, bold = true).apply { setPadding(dp(8), 0, 0, dp(2)) })
        card.addView(head)
        card.addView(View(this).apply { setBackgroundColor(ACCENT) },
            LinearLayout.LayoutParams(dp(36), dp(2)).apply { setMargins(0, dp(6), 0, dp(8)) })
        val body = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        card.addView(body)
        parent.addView(card, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(12) })
        return body
    }

    /** Selectable card styled like the window's chips (teal bar and title when selected). */
    private fun card(title: String, detail: String, selected: Boolean = false) = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(12), dp(8), dp(12), dp(8))
        addView(text(title, 14, TEXT, bold = true))
        if (detail.isNotEmpty()) addView(text(detail, 11, DIM))
        paint(this, selected)
        layoutParams = LinearLayout.LayoutParams(-1, -2).apply { setMargins(0, dp(3), 0, dp(3)) }
    }

    private fun paint(card: LinearLayout, on: Boolean) {
        card.background = box(if (on) PANEL_HI else PANEL, if (on) ACCENT else LINE)
        (card.getChildAt(0) as TextView).setTextColor(if (on) ACCENT else TEXT)
    }

    private fun showFeatures(info: PythonHost.Info) {
        titleView.text = info.title
        featureBox.removeAllViews()
        if (info.features.none { it.first == feature }) feature = info.features.first().first
        for ((key, title, summary) in info.features) {
            val card = card(title, summary, key == feature)
            card.setOnClickListener {
                feature = key
                featureCards.forEach { (k, c) -> paint(c, k == key) }
            }
            featureCards[key] = card
            featureBox.addView(card)
        }
        loaded = true
    }

    private fun refreshTouchNote() {
        val on = TouchService.instance != null
        touchNote.text = if (on) "✓ 无障碍服务已开启" else "⚠ 无障碍服务「AutoStronghold 触控」未开启（点此开启）"
        touchNote.setTextColor(if (on) OK else WARN)
    }

    // --- running -----------------------------------------------------------------
    private fun start(check: Boolean) {
        if (RunState.running) {
            RunService.stop(this)
            return
        }
        if (!loaded) return
        if (TouchService.instance == null) {
            AlertDialog.Builder(this).setTitle("需要开启无障碍服务")
                .setMessage("程序通过无障碍服务「AutoStronghold 触控」在游戏中点击和拖动，不读取界面内容。\n\n" +
                    "在接下来的设置页中找到「AutoStronghold 触控」并开启。若开关是灰色的，先在「应用信息 → 右上角菜单」中「允许受限制的设置」。")
                .setPositiveButton("去开启") { _, _ -> openAccessibility() }
                .setNegativeButton("取消", null).show()
            return
        }
        saveSettings()
        pendingCheck = check
        @Suppress("DEPRECATION")
        startActivityForResult(getSystemService(MediaProjectionManager::class.java).createScreenCaptureIntent(), REQ_CAPTURE)
    }

    @Deprecated("Activity result API needs AndroidX; this app has no dependencies besides ONNX Runtime.")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        @Suppress("DEPRECATION")
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != REQ_CAPTURE) return
        if (resultCode != RESULT_OK || data == null) {
            RunState.say("没有允许录屏，程序看不到屏幕，无法开始。", "warn")
            return
        }
        RunService.start(this, resultCode, data, feature, maxGamesValue(), skipSpeed.isChecked, pendingCheck)
        val game = GAME_PACKAGES.firstNotNullOfOrNull { packageManager.getLaunchIntentForPackage(it) }
        if (game != null) startActivity(game.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        else RunState.say("没有找到明日方舟，请手动切换到游戏。", "warn")
    }

    private fun openAccessibility() {
        startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
    }

    private fun maxGamesValue() = maxGames.text.toString().toIntOrNull()?.coerceIn(0, 999) ?: 0

    private fun saveSettings() {
        prefs.edit().putString("feature", feature).putInt("maxGames", maxGamesValue())
            .putBoolean("skipSpeed", skipSpeed.isChecked).apply()
    }

    // --- RunState.Listener -------------------------------------------------------
    override fun onLine(line: RunState.Line) {
        val out = SpannableStringBuilder()
        out.append(line.time + "  ", ForegroundColorSpan(FAINT), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        out.append(line.text + "\n", ForegroundColorSpan(LEVEL_COLOURS[line.level] ?: TEXT), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        if (logView.lineCount > RunState.MAX_LINES) {
            logView.text = ""
            RunState.lines.forEach { if (it !== line) onLine(it) }
        }
        logView.append(out)
        logView.post {
            val layout = logView.layout ?: return@post
            logView.scrollTo(0, maxOf(0, layout.height - logView.height + logView.paddingBottom + logView.paddingTop))
        }
    }

    override fun onStatus() {
        for ((key, view) in statusViews) RunState.status[key]?.let { view.text = it }
        val running = RunState.running
        startButton.text = if (running) "停  止" else "开  始"
        startButton.setTextColor(if (running) 0xFF2A0909.toInt() else ACCENT_INK)
        startButton.background = box(if (running) ERROR else ACCENT, if (running) ERROR else ACCENT)
        checkButton.isEnabled = !running
        checkButton.alpha = if (running) 0.4f else 1f
    }

    // --- dialogs -----------------------------------------------------------------
    private fun showGuide() {
        AlertDialog.Builder(this).setTitle("⚠  运行前须知").setMessage(STARTUP_GUIDE).setPositiveButton("知道了", null).show()
    }

    private fun showLicenses() {
        val files = licenseFiles("licenses").sorted()
        AlertDialog.Builder(this).setTitle("许可证")
            .setItems(files.toTypedArray()) { _, i ->
                val content = assets.open("licenses/${files[i]}").bufferedReader().use { it.readText() }
                val view = ScrollView(this).apply {
                    addView(text(content, 12, TEXT).apply { setPadding(dp(16), dp(12), dp(16), dp(12)); setTextIsSelectable(true) })
                }
                AlertDialog.Builder(this).setTitle(files[i]).setView(view).setPositiveButton("关闭", null).show()
            }
            .setPositiveButton("关闭", null).show()
    }

    /** Paths below assets/licenses (LICENSE, THIRD_PARTY_NOTICES.md, one folder per package). */
    private fun licenseFiles(path: String): List<String> {
        val children = assets.list(path).orEmpty()
        if (children.isEmpty()) return listOf(path.removePrefix("licenses/"))
        return children.flatMap { licenseFiles("$path/$it") }
    }
}
