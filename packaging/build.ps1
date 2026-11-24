<#
Builds the release packages in one step:
  dist\AutoStronghold-CPU.zip       (onnxruntime, no GPU needed)
  dist\AutoStronghold-GPU.zip       (onnxruntime-directml)
  dist\AutoStronghold-Android.apk   (the same package on Chaquopy's Python, see android\)

Missing build environments (.venv-cpu / .venv-gpu, Python 3.11) are created automatically.
Usage:  powershell -ExecutionPolicy Bypass -File packaging\build.ps1 [-Variant cpu|gpu|android|all]

The APK needs JDK 17+ and the Android SDK (platform 34; ANDROID_HOME or the Android Studio
default folder). Gradle and the Python 3.10 that Chaquopy installs packages with are
downloaded into build\android\ (pinned versions, SHA-256 checked) when missing. The release
key is created on first use in private\android\ (never published); keep it, or later
APKs cannot be installed over earlier ones.

Each archive is meant for a GitHub release and holds only what is needed to run:
  AutoStronghold-XXX.exe (the program window) and _internal\ (the runtime, the bundled
  resources, and in _internal\licenses\ this project's LICENSE, THIRD_PARTY_NOTICES.md and
  the third-party license texts, which must travel with the binaries).
  README, source and the editable settings live in the repository; a tactics\ or layout\
  folder placed next to the exe still overrides the bundled defaults (paths.user_file).
#>
param([ValidateSet("cpu", "gpu", "android", "all")][string]$Variant = "all")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Ensure-Venv([string]$v) {
    $python = Join-Path $root ".venv-$v\Scripts\python.exe"
    if (Test-Path $python) { return $python }
    Write-Host "Creating .venv-$v ..."
    & py -3.11 -m venv ".venv-$v"
    if ($LASTEXITCODE -ne 0) { throw "Python 3.11 is required (py -3.11)." }
    & $python -m pip install --quiet -r "requirements-$v.txt"
    if ($v -eq "gpu") {
        # rapidocr-onnxruntime depends on the CPU onnxruntime; the GPU build uses onnxruntime-directml.
        & $python -m pip install --quiet --no-deps rapidocr-onnxruntime==1.4.4
    }
    if ($LASTEXITCODE -ne 0) { throw "Installing requirements-$v.txt failed." }
    return $python
}

function Build-Variant([string]$v) {
    $python = Ensure-Venv $v
    $name = "AutoStronghold-$($v.ToUpper())"
    $marker = Join-Path $root "autostronghold\_build_variant.py"
    Set-Content -Path $marker -Value "VARIANT = `"$v`"" -Encoding utf8
    try {
        $env:AUTOSTRONGHOLD_BUILD_VARIANT = $v
        & $python -m PyInstaller --noconfirm --clean --log-level WARN --distpath dist --workpath "build\$v" packaging\autostronghold.spec
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed for $v" }
    } finally {
        Remove-Item $marker -ErrorAction SilentlyContinue
        Remove-Item Env:\AUTOSTRONGHOLD_BUILD_VARIANT -ErrorAction SilentlyContinue
    }
    $out = Join-Path $root "dist\$name"
    $internal = Join-Path $out "_internal"
    & $python packaging\collect_licenses.py $internal | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Collecting third-party licenses failed for $v" }
    Copy-Item -Force LICENSE, THIRD_PARTY_NOTICES.md (Join-Path $internal "licenses")
    $zip = "$out.zip"
    # A virus scanner may still hold the files PyInstaller just wrote: wait and try again.
    for ($try = 1; ; $try++) {
        if (Test-Path $zip) { Remove-Item $zip }
        try { Compress-Archive -Path $out -DestinationPath $zip -ErrorAction Stop; break }
        catch { if ($try -ge 5) { throw }; Write-Host "Zipping $name failed ($($_.Exception.Message)), retrying"; Start-Sleep -Seconds 5 }
    }
    Write-Host "Built $zip"
}

$tools = Join-Path $root "build\android"
$GradleVersion = "8.7"
$GradleSha256 = "544c35d6bd849ae8a5ed0bcea39ba677dc40f49df7d1835561582da2009b961d"
$PythonVersion = "3.10.11"   # nuget "python" package: a full interpreter with pip
$PythonSha256 = "7c6f99b160a36a7e09492dfcff2b0a3a60bb5229ca44cdcc3ecb32871a6144d0"

function Get-Checked([string]$url, [string]$file, [string]$sha256) {
    if (-not (Test-Path $file)) {
        Write-Host "Downloading $url ..."
        New-Item -ItemType Directory -Force (Split-Path $file) | Out-Null
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile "$file.part"
        Move-Item -Force "$file.part" $file
    }
    $actual = (Get-FileHash -Algorithm SHA256 $file).Hash.ToLower()
    if ($actual -ne $sha256) { Remove-Item $file; throw "Checksum mismatch for $url" }
}

function Ensure-Gradle {
    $gradle = Join-Path $tools "gradle-$GradleVersion\bin\gradle.bat"
    if (Test-Path $gradle) { return $gradle }
    $zip = Join-Path $tools "dl\gradle-$GradleVersion-bin.zip"
    Get-Checked "https://services.gradle.org/distributions/gradle-$GradleVersion-bin.zip" $zip $GradleSha256
    Expand-Archive -Force $zip $tools
    return $gradle
}

function Ensure-Python310 {
    # Chaquopy runs pip with a Python of the app's version (3.10).
    # PowerShell 5.1 turns py's "No suitable Python runtime" on stderr into an error under "Stop".
    $found = try { & cmd /c "py -3.10 -c ""import sys; print(sys.executable)"" 2>nul" } catch { $null }
    if ($LASTEXITCODE -eq 0 -and $found) { return "$found".Trim() }
    $python = Join-Path $tools "python310\tools\python.exe"
    if (Test-Path $python) { return $python }
    $pkg = Join-Path $tools "dl\python.$PythonVersion.nupkg"
    Get-Checked "https://api.nuget.org/v3-flatcontainer/python/$PythonVersion/python.$PythonVersion.nupkg" $pkg $PythonSha256
    $zip = [IO.Path]::ChangeExtension($pkg, ".zip")
    Copy-Item -Force $pkg $zip
    Expand-Archive -Force $zip (Join-Path $tools "python310")
    return $python
}

function Find-Jdk {
    $candidates = @($env:JAVA_HOME) + (Get-ChildItem "$env:ProgramFiles\Java\jdk-*", "$env:ProgramFiles\Eclipse Adoptium\jdk-*",
        "$env:ProgramFiles\Android\Android Studio\jbr" -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending | ForEach-Object FullName)
    foreach ($jdk in $candidates) {
        if (-not $jdk -or -not (Test-Path "$jdk\bin\javac.exe")) { continue }
        $line = (& "$jdk\bin\javac.exe" -version 2>&1 | Out-String).Trim()
        if ($line -match "javac (\d+)" -and [int]$Matches[1] -ge 17) { return $jdk }
    }
    throw "JDK 17 or newer is required for the Android build (set JAVA_HOME)."
}

function Find-AndroidSdk {
    foreach ($sdk in @($env:ANDROID_HOME, $env:ANDROID_SDK_ROOT, "$env:LOCALAPPDATA\Android\Sdk")) {
        if ($sdk -and (Test-Path "$sdk\platforms")) { return $sdk }
    }
    throw "Android SDK not found (set ANDROID_HOME, or install it with Android Studio)."
}

function Ensure-Signing([string]$jdk) {
    $dir = Join-Path $root "private\android"
    $props = Join-Path $dir "signing.properties"
    if (Test-Path $props) { return $props }
    New-Item -ItemType Directory -Force $dir | Out-Null
    $password = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ })
    & "$jdk\bin\keytool.exe" -genkeypair -noprompt -keystore (Join-Path $dir "release.jks") -storetype PKCS12 `
        -alias autostronghold -keyalg RSA -keysize 4096 -validity 36500 -storepass $password -keypass $password `
        -dname "CN=AutoStronghold"
    if ($LASTEXITCODE -ne 0) { throw "Creating the release key failed." }
    Set-Content -Path $props -Encoding ascii -Value @(
        "storeFile=release.jks", "storePassword=$password", "keyAlias=autostronghold", "keyPassword=$password")
    Write-Host "Created the release key in $dir (keep it: later APKs must be signed with the same key)."
    return $props
}

function Build-Android {
    $jdk = Find-Jdk
    $sdk = Find-AndroidSdk
    $python = Ensure-Python310
    $gradle = Ensure-Gradle
    $signing = Ensure-Signing $jdk
    Set-Content -Path (Join-Path $root "android\local.properties") -Encoding ascii -Value ("sdk.dir=" + $sdk.Replace("\", "/"))
    $env:JAVA_HOME = $jdk
    & $gradle -p android --no-daemon --console=plain assembleRelease "-PbuildPython=$python" "-PsigningProps=$signing"
    if ($LASTEXITCODE -ne 0) { throw "Gradle failed for the Android app" }
    $apk = Join-Path $root "dist\AutoStronghold-Android.apk"
    New-Item -ItemType Directory -Force (Split-Path $apk) | Out-Null
    Copy-Item -Force (Join-Path $root "android\app\build\outputs\apk\release\app-release.apk") $apk
    Write-Host "Built $apk"
}

switch ($Variant) {
    "all" { Build-Variant "cpu"; Build-Variant "gpu"; Build-Android }
    "android" { Build-Android }
    default { Build-Variant $Variant }
}
