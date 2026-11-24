package com.autostronghold.app

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.accessibilityservice.GestureDescription.StrokeDescription
import android.graphics.Path
import android.view.accessibility.AccessibilityEvent
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * Taps and drags as accessibility gestures. A drag is one stroke that is continued piece
 * by piece (down, moves, up), so the finger stays on the screen between the calls.
 */
class TouchService : AccessibilityService() {
    companion object {
        @Volatile var instance: TouchService? = null
            private set

        private const val STEP_MS = 8L
    }

    private var held: StrokeDescription? = null
    private var lastX = 0f
    private var lastY = 0f

    override fun onServiceConnected() { instance = this }

    override fun onDestroy() {
        instance = null
        super.onDestroy()
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {}

    override fun onInterrupt() {}

    private fun line(x1: Float, y1: Float, x2: Float, y2: Float) = Path().apply { moveTo(x1, y1); lineTo(x2, y2) }

    /** Dispatch one stroke and wait until the system has played it. */
    private fun play(stroke: StrokeDescription, timeoutMs: Long = 3000): Boolean {
        val done = CountDownLatch(1)
        var ok = false
        val callback = object : GestureResultCallback() {
            override fun onCompleted(gestureDescription: GestureDescription?) { ok = true; done.countDown() }
            override fun onCancelled(gestureDescription: GestureDescription?) { done.countDown() }
        }
        if (!dispatchGesture(GestureDescription.Builder().addStroke(stroke).build(), callback, null)) return false
        return done.await(timeoutMs, TimeUnit.MILLISECONDS) && ok
    }

    @Synchronized
    fun tap(x: Float, y: Float): Boolean {
        release()
        return play(StrokeDescription(line(x, y, x, y), 0, 50))
    }

    @Synchronized
    fun down(x: Float, y: Float): Boolean {
        release()
        val stroke = StrokeDescription(line(x, y, x, y), 0, STEP_MS, true)
        lastX = x; lastY = y
        return play(stroke).also { if (it) held = stroke }
    }

    @Synchronized
    fun move(x: Float, y: Float): Boolean {
        val stroke = held?.continueStroke(line(lastX, lastY, x, y), 0, STEP_MS, true) ?: return down(x, y)
        lastX = x; lastY = y
        return play(stroke).also { held = if (it) stroke else null }
    }

    @Synchronized
    fun up(x: Float, y: Float): Boolean {
        val prev = held ?: return false
        held = null
        val ok = play(prev.continueStroke(line(lastX, lastY, x, y), 0, STEP_MS, false))
        lastX = x; lastY = y
        return ok
    }

    /** Lift a finger that is still down (a drag that was not finished). */
    @Synchronized
    fun release() {
        if (held != null) up(lastX, lastY)
    }
}
