package com.autostronghold.app

/** What autostronghold/device/android.py calls: screenshots and touches, in screen pixels. */
object DeviceBridge {
    @Volatile var capture: ScreenCapture? = null

    /** Null when screenshots and touches are both available, else why not (shown to the player). */
    @JvmStatic
    fun problem(): String? = when {
        TouchService.instance == null -> "无障碍服务「AutoStronghold 触控」没有开启，程序无法点击和拖动。"
        capture == null || capture!!.stopped -> "没有录屏授权（或录屏已被系统停止），程序看不到屏幕。"
        else -> null
    }

    @JvmStatic
    fun displaySize(): IntArray = capture?.size() ?: intArrayOf(0, 0)

    @JvmStatic
    fun capture(): Frame? = capture?.capture()

    private fun touch(): TouchService = TouchService.instance
        ?: throw IllegalStateException("无障碍服务「AutoStronghold 触控」已被关闭。")

    @JvmStatic
    fun tap(x: Int, y: Int): Boolean = touch().tap(x.toFloat(), y.toFloat())

    @JvmStatic
    fun down(x: Int, y: Int): Boolean = touch().down(x.toFloat(), y.toFloat())

    @JvmStatic
    fun move(x: Int, y: Int): Boolean = touch().move(x.toFloat(), y.toFloat())

    @JvmStatic
    fun up(x: Int, y: Int): Boolean = touch().up(x.toFloat(), y.toFloat())

    @JvmStatic
    fun release() { TouchService.instance?.release() }
}
