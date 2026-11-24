// The Android app runs the same autostronghold package as the Windows builds, on Chaquopy's
// Python 3.10. packaging\build.ps1 -Variant android passes:
//   -PbuildPython=<Python 3.10 used by Chaquopy for pip>   -PsigningProps=<keystore settings>
//   -Pabis=<comma-separated ABIs, default arm64-v8a>
import java.util.Properties
import javax.inject.Inject

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

val repo: File = rootDir.parentFile
val stage = layout.buildDirectory.dir("stage")
val appVersion: String = Regex("""__version__ = "([^"]+)"""")
    .find(repo.resolve("autostronghold/__init__.py").readText())!!.groupValues[1]
val abiList = (findProperty("abis") as String? ?: "arm64-v8a").split(",").map { it.trim() }.filter { it.isNotEmpty() }

// The package without the Windows-only modules (window, UAC, DirectML check, MaaFramework
// devices; all imported lazily), plus the build-variant marker build.ps1 writes for the exe builds.
val stagePython by tasks.registering(Sync::class) {
    from(repo.resolve("autostronghold")) {
        exclude("**/__pycache__/**", "_build_variant.py", "__main__.py", "gui.py", "elevate.py", "accel.py",
                "device/pc.py", "device/emulator.py", "device/maa_runtime.py")
        into("autostronghold")
    }
    into(stage.map { it.dir("python") })
    doLast { destinationDir.resolve("autostronghold/_build_variant.py").writeText("VARIANT = \"android\"\n") }
}

// Bundled resources (unpacked to the app's files folder on first start), this project's license.
val stageAssets by tasks.registering(Sync::class) {
    from(repo.resolve("resources")) { into("resources") }
    from(repo) { include("LICENSE", "THIRD_PARTY_NOTICES.md"); into("licenses") }
    into(stage.map { it.dir("assets") })
}

// Third-party license texts of the packages Chaquopy installed, as for the exe builds.
abstract class CollectLicenses : DefaultTask() {
    @get:Input abstract val python: Property<String>
    @get:InputFile abstract val script: RegularFileProperty
    @get:Internal abstract val site: DirectoryProperty
    @get:OutputDirectory abstract val outputDir: DirectoryProperty
    @get:Inject abstract val exec: ExecOperations

    @TaskAction
    fun collect() {
        val out = outputDir.get().asFile
        out.deleteRecursively()
        exec.exec { commandLine(python.get(), script.get().asFile, out, "--site", site.get().asFile) }
    }
}

android {
    namespace = "com.autostronghold.app"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.autostronghold.app"
        minSdk = 26          // accessibility gestures that keep the finger down (continueStroke)
        targetSdk = 34
        val (major, minor, patch) = (appVersion.split(".") + listOf("0", "0")).take(3).map { it.toInt() }
        versionCode = major * 10000 + minor * 100 + patch
        versionName = appVersion
        ndk { abiFilters += abiList }
    }

    val signing = (findProperty("signingProps") as String?)?.let { file(it) }?.takeIf { it.isFile }
    signingConfigs {
        if (signing != null) {
            create("release") {
                val p = Properties().apply { signing.inputStream().use { load(it) } }
                storeFile = signing.resolveSibling(p.getProperty("storeFile"))
                storePassword = p.getProperty("storePassword")
                keyAlias = p.getProperty("keyAlias")
                keyPassword = p.getProperty("keyPassword")
            }
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("release") ?: signingConfigs.getByName("debug")
        }
    }
    sourceSets["main"].assets.srcDir(stageAssets.map { it.destinationDir })
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

chaquopy {
    defaultConfig {
        version = "3.10"     // newest Python with Chaquopy builds of OpenCV
        (findProperty("buildPython") as String?)?.let { buildPython(it) }
        pip {
            // Every package is listed and pinned, so no dependency is resolved: RapidOCR's
            // onnxruntime and pyclipper are replaced by src/main/python (Java ONNX Runtime, Shapely).
            options("--no-deps")
            install("numpy==1.26.2")
            install("opencv-python-headless==4.5.1.48")
            install("shapely==1.8.5")
            install("pyyaml==6.0.3")
            install("pillow==11.0.0")
            install("rapidocr-onnxruntime==1.4.4")
            // Native libraries the Chaquopy builds above load (libjpeg_chaquopy.so, ...).
            for (lib in listOf("libcxx==180000", "openblas==0.2.20", "libgfortran==4.9", "libpng==1.6.34",
                               "libjpeg==1.5.3", "freetype==2.9.1", "geos==3.8.1", "libyaml==0.2.5")) {
                install("chaquopy-$lib")
            }
        }
        extractPackages("rapidocr_onnxruntime")   // its models are opened by file path
    }
    sourceSets {
        getByName("main") { srcDir(stagePython.map { it.destinationDir }) }
    }
}

dependencies {
    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.22.0")
}

tasks.named("preBuild") { dependsOn(stagePython, stageAssets) }

androidComponents {
    onVariants { variant ->
        val name = variant.name.replaceFirstChar { it.uppercase() }
        val licenses = tasks.register<CollectLicenses>("collect${name}Licenses") {
            dependsOn("generate${name}PythonRequirements")
            python.set(findProperty("buildPython") as String? ?: "python")
            script.set(repo.resolve("packaging/collect_licenses.py"))
            site.set(layout.buildDirectory.dir("python/pip/${variant.name}"))
        }
        variant.sources.assets?.addGeneratedSourceDirectory(licenses, CollectLicenses::outputDir)
    }
}
