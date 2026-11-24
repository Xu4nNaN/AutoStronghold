package com.autostronghold.app

import android.os.Handler
import android.os.Looper
import android.os.SystemClock

/**
 * Status and log of the current run, shared by the service and the window. Python reports
 * through [Sink]; listeners are called on the main thread.
 */
object RunState {
    class Line(val time: String, val level: String, val text: String)

    interface Listener {
        fun onLine(line: Line)
        fun onStatus()
    }

    const val MAX_LINES = 2000
    val status = linkedMapOf("state" to "待机", "screen" to "—", "stage" to "—", "round" to "—", "games" to "—")
    val lines = ArrayDeque<Line>()
    @Volatile var running = false
    var startedAt: Long? = null
    private val listeners = mutableSetOf<Listener>()
    private val main = Handler(Looper.getMainLooper())

    fun addListener(l: Listener) = main.post { listeners += l }
    fun removeListener(l: Listener) = main.post { listeners -= l }

    fun say(text: String, level: String = "info") = main.post {
        val line = Line(java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.ROOT).format(java.util.Date()), level, text)
        lines.addLast(line)
        while (lines.size > MAX_LINES) lines.removeFirst()
        listeners.forEach { it.onLine(line) }
    }

    fun set(key: String, value: String) = main.post {
        status[key] = value
        listeners.forEach { it.onStatus() }
    }

    fun begun(check: Boolean) = main.post {
        running = true
        startedAt = SystemClock.elapsedRealtime()
        for (key in listOf("screen", "stage", "round", "games")) status[key] = "—"
        status["state"] = if (check) "自检中" else "运行中"
        listeners.forEach { it.onStatus() }
    }

    fun ended(state: String) = main.post {
        running = false
        startedAt = null
        status["state"] = state
        listeners.forEach { it.onStatus() }
    }

    fun elapsed(): String {
        val start = startedAt ?: return ""
        val s = (SystemClock.elapsedRealtime() - start) / 1000
        return "%02d:%02d:%02d".format(s / 3600, s / 60 % 60, s % 60)
    }

    /** The `RunSink` that autostronghold/android_ui.py reports to. */
    class Sink {
        var finalState = "已停止"
            private set

        fun log(level: String, text: String) { RunState.say(text, level) }
        fun status(key: String, value: String) { RunState.set(key, value) }
        fun finished(state: String) { finalState = state }
    }
}
