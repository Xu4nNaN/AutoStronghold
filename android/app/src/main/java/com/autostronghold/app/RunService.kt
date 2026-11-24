package com.autostronghold.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.IBinder
import android.util.Log

/**
 * One run in a foreground service, so it goes on while the game is in front. It holds the
 * screen recording, runs autostronghold/android_ui.py on a worker thread, and offers 停止
 * in its notification.
 */
class RunService : Service(), RunState.Listener {
    companion object {
        private const val CHANNEL = "run"
        private const val NOTIFICATION = 1
        private const val ACTION_STOP = "stop"

        fun start(context: Context, resultCode: Int, data: Intent, feature: String, maxGames: Int,
                  skipSpeed: Boolean, check: Boolean) {
            context.startForegroundService(Intent(context, RunService::class.java)
                .putExtra("code", resultCode).putExtra("data", data).putExtra("feature", feature)
                .putExtra("maxGames", maxGames).putExtra("skipSpeed", skipSpeed).putExtra("check", check))
        }

        fun stop(context: Context) {
            context.startService(Intent(context, RunService::class.java).setAction(ACTION_STOP))
        }
    }

    private var worker: Thread? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            if (worker?.isAlive == true) {
                RunState.set("state", "正在停止…")
                Thread { PythonHost.module().callAttr("stop") }.start()
            } else stopSelf()
            return START_NOT_STICKY
        }
        if (intent == null || worker?.isAlive == true) return START_NOT_STICKY
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NOTIFICATION, notification("准备中…"), ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
        } else startForeground(NOTIFICATION, notification("准备中…"))
        val check = intent.getBooleanExtra("check", false)
        RunState.begun(check)
        RunState.addListener(this)
        worker = Thread({
            try {
                @Suppress("DEPRECATION")
                val data = intent.getParcelableExtra<Intent>("data")!!
                val projection = getSystemService(MediaProjectionManager::class.java)
                    .getMediaProjection(intent.getIntExtra("code", 0), data)
                DeviceBridge.capture = ScreenCapture(this, projection)
                val info = PythonHost.setup(this)
                RunState.say("${info.title}：开始运行，请切换到游戏。")
                val sink = RunState.Sink()
                PythonHost.module().callAttr("run", intent.getStringExtra("feature"), intent.getIntExtra("maxGames", 0),
                    intent.getBooleanExtra("skipSpeed", false), check, sink)
                RunState.ended(sink.finalState)
            } catch (e: Throwable) {
                Log.e("AutoStronghold", "run failed", e)
                RunState.say("无法开始运行：${e.message ?: e}", "error")
                RunState.ended("已停止（出错）")
            } finally {
                DeviceBridge.capture?.close()
                DeviceBridge.capture = null
                DeviceBridge.release()
                RunState.removeListener(this)
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
        }, "autostronghold-run").apply { start() }
        return START_NOT_STICKY
    }

    override fun onLine(line: RunState.Line) {}

    override fun onStatus() {
        val s = RunState.status
        getSystemService(NotificationManager::class.java).notify(NOTIFICATION,
            notification("${s["state"]} · ${s["stage"]} · 回合 ${s["round"]} · 对局 ${s["games"]}"))
    }

    private fun notification(text: String): Notification {
        val manager = getSystemService(NotificationManager::class.java)
        if (manager.getNotificationChannel(CHANNEL) == null) {
            manager.createNotificationChannel(NotificationChannel(CHANNEL, "运行状态", NotificationManager.IMPORTANCE_LOW))
        }
        val flags = PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), flags)
        val stop = PendingIntent.getService(this, 1, Intent(this, RunService::class.java).setAction(ACTION_STOP), flags)
        return Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_notify)
            .setContentTitle("AutoStronghold")
            .setContentText(text)
            .setOngoing(true)
            .setContentIntent(open)
            .addAction(Notification.Action.Builder(null, "停止", stop).build())
            .apply { if (Build.VERSION.SDK_INT >= 31) setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE) }
            .build()
    }
}
