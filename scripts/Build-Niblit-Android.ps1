# Build a versioned debug APK from the installed, isolated Android toolchain on D:.
[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$project='C:\Users\Riyaad\Documents\GitHub\Niblit\android\NiblitMobile'
$tools='D:\NiblitAIOS\toolchains\android'
$jdk=Join-Path $tools 'jdk17'
$sdk=Join-Path $tools 'sdk'
$wrapper=Join-Path $project 'gradlew.bat'
foreach($path in @((Join-Path $jdk 'bin\java.exe'),(Join-Path $sdk 'platforms\android-35\android.jar'),$wrapper)) {
  if(-not (Test-Path -LiteralPath $path)) { throw "Android build prerequisite missing: $path" }
}
$env:JAVA_HOME=$jdk
$env:ANDROID_SDK_ROOT=$sdk
$env:ANDROID_HOME=$sdk
$env:GRADLE_USER_HOME=Join-Path $tools 'gradle-home'
$env:PATH=(Join-Path $jdk 'bin')+';'+$env:PATH
Push-Location $project
try {
  # Gradle emits harmless SDK XML compatibility warnings on stderr in PowerShell 5.
  $ErrorActionPreference='Continue'
  & $wrapper ':app:assembleDebug' '--no-daemon' '--console=plain'
  $buildCode=$LASTEXITCODE
  $ErrorActionPreference='Stop'
  if($buildCode -ne 0) { throw "Android Gradle compilation failed (exit $buildCode)" }
  $apk=Join-Path $project 'app\build\outputs\apk\debug\app-debug.apk'
  if(-not (Test-Path -LiteralPath $apk)) { throw 'Gradle succeeded but APK is missing' }
  $releaseDir='D:\NiblitAIOS\releases\mobile'
  New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
  $dest=Join-Path $releaseDir 'niblit-ai-v0.3.0-debug.apk'
  $digest=(Get-FileHash $apk -Algorithm SHA256).Hash
  if(Test-Path $dest) {
    if((Get-FileHash $dest -Algorithm SHA256).Hash -ne $digest) {
      throw "A differently signed/built APK already exists at $dest. Preserve it; choose a new release version."
    }
  } else {
    Copy-Item -LiteralPath $apk -Destination $dest -ErrorAction Stop
  }
  Write-Output "APK_BUILT=$dest"
  Write-Output "APK_BYTES=$((Get-Item $dest).Length)"
  Write-Output "APK_SHA256=$digest"
  Write-Output 'BUILD_TYPE=debug (local phone testing only; not store-signed)'
} finally { Pop-Location }
