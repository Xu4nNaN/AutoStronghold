package com.autostronghold.app

import android.app.Application
import android.content.Context
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File

class App : Application() {
    override fun onCreate() {
        super.onCreate()
        if (!Python.isStarted()) Python.start(AndroidPlatform(this))
    }
}

/** The Python side (autostronghold/android_ui.py), set up once per process. */
object PythonHost {
    class Info(val title: String, val features: List<Triple<String, String, String>>)

    private var info: Info? = null

    /** The app's files folder; logs and tactics/layout overrides live here (Android/data/…/files). */
    fun appDir(context: Context): File = context.getExternalFilesDir(null) ?: context.filesDir

    @Synchronized
    fun setup(context: Context): Info {
        info?.let { return it }
        val resources = unpackResources(context)
        val ui = module()
        val title = ui.callAttr("setup", appDir(context).absolutePath, resources.absolutePath).toString()
        val features = ui.callAttr("features").asList().map { f ->
            val (key, name, summary) = f.asList().map { it.toString() }
            Triple(key, name, summary)
        }
        return Info(title, features).also { info = it }
    }

    fun module(): PyObject = Python.getInstance().getModule("autostronghold.android_ui")

    /** Copy assets/resources to a real folder (the program opens them by path), once per install. */
    private fun unpackResources(context: Context): File {
        val target = File(context.filesDir, "resources")
        val stamp = File(context.filesDir, "resources.stamp")
        val installed = context.packageManager.getPackageInfo(context.packageName, 0).lastUpdateTime.toString()
        if (stamp.isFile && stamp.readText() == installed && target.isDirectory) return target
        target.deleteRecursively()
        copyAssets(context, "resources", target)
        stamp.writeText(installed)
        return target
    }

    private fun copyAssets(context: Context, path: String, target: File) {
        val children = context.assets.list(path).orEmpty()
        if (children.isEmpty()) {
            target.parentFile?.mkdirs()
            context.assets.open(path).use { input -> target.outputStream().use { input.copyTo(it) } }
            return
        }
        target.mkdirs()
        for (child in children) copyAssets(context, "$path/$child", File(target, child))
    }
}
