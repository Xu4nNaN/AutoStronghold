// Android app: packaging\build.ps1 -Variant android runs this project (see app/build.gradle.kts).
plugins {
    id("com.android.application") version "8.5.2" apply false
    id("org.jetbrains.kotlin.android") version "1.9.24" apply false
    id("com.chaquo.python") version "16.1.0" apply false
}
