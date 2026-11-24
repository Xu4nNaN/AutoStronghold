package com.autostronghold.app

import android.content.Context
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import android.util.DisplayMetrics
import android.view.WindowManager

/** One screenshot: RGBA rows of [rowStride] bytes (read by autostronghold/device/android.py). */
class Frame(@JvmField val width: Int, @JvmField val height: Int, @JvmField val rowStride: Int,
            @JvmField val pixels: ByteArray)

/**
 * Screenshots of the whole screen from the recording the player allowed. The virtual display
 * follows rotations (the run starts in this app, in portrait, and continues in the game).
 */
class ScreenCapture(context: Context, private val projection: MediaProjection) {
    private val windows = context.getSystemService(WindowManager::class.java)
    private val thread = HandlerThread("capture").apply { start() }
    private val handler = Handler(thread.looper)
    private var reader: ImageReader
    private val display: VirtualDisplay
    private var last: Frame? = null
    @Volatile var stopped = false
        private set

    init {
        projection.registerCallback(object : MediaProjection.Callback() {
            override fun onStop() { stopped = true }
        }, handler)
        val m = metrics()
        reader = ImageReader.newInstance(m.widthPixels, m.heightPixels, PixelFormat.RGBA_8888, 2)
        display = projection.createVirtualDisplay("AutoStronghold", m.widthPixels, m.heightPixels, m.densityDpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, reader.surface, null, handler)
    }

    @Suppress("DEPRECATION")
    private fun metrics(): DisplayMetrics = DisplayMetrics().also { windows.defaultDisplay.getRealMetrics(it) }

    fun size(): IntArray = metrics().let { intArrayOf(it.widthPixels, it.heightPixels) }

    /** The newest frame; the previous one while the screen has not changed. */
    @Synchronized
    fun capture(): Frame? {
        if (stopped) return null
        val m = metrics()
        if (m.widthPixels != reader.width || m.heightPixels != reader.height) {
            val old = reader
            reader = ImageReader.newInstance(m.widthPixels, m.heightPixels, PixelFormat.RGBA_8888, 2)
            display.resize(m.widthPixels, m.heightPixels, m.densityDpi)
            display.surface = reader.surface
            old.close()
            last = null
        }
        val deadline = SystemClock.uptimeMillis() + 2000
        while (true) {
            reader.acquireLatestImage()?.use { image ->
                val plane = image.planes[0]
                val buffer = plane.buffer
                val pixels = ByteArray(plane.rowStride * image.height)
                buffer.get(pixels, 0, minOf(buffer.remaining(), pixels.size))
                last = Frame(image.width, image.height, plane.rowStride, pixels)
                return last
            }
            last?.let { return it }
            if (SystemClock.uptimeMillis() > deadline || stopped) return null
            Thread.sleep(30)
        }
    }

    fun close() {
        stopped = true
        display.release()
        reader.close()
        projection.stop()
        thread.quitSafely()
    }
}
