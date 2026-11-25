$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$root='D:\NiblitAIOS\toolchains\android'
$downloads=Join-Path $root 'downloads'
$sdk=Join-Path $root 'sdk'
$jdk=Join-Path $root 'jdk17'
$gradle=Join-Path $root 'gradle'
$log=Join-Path $root 'install-status.log'
New-Item -ItemType Directory -Force $downloads,$sdk,$jdk,$gradle | Out-Null
function Log($msg) { $line=((Get-Date).ToString('s')+' '+$msg);Add-Content -LiteralPath $log -Value $line;Write-Output $line }
function Download($url,$path) {
 if((Test-Path $path) -and (Get-Item $path).Length -gt 1000000) { Log "REUSE $path";return }
 $tmp=$path+'.partial'
 if(Test-Path $tmp){Remove-Item -LiteralPath $tmp -Force}
 Log "DOWNLOADING $url"
 Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing -MaximumRedirection 8 -TimeoutSec 1200
 Move-Item -LiteralPath $tmp -Destination $path -Force
 Log ("DOWNLOADED "+$path+" bytes="+(Get-Item $path).Length)
}
Log 'ANDROID_BOOTSTRAP_STARTED'
$cmdzip=Join-Path $downloads 'commandlinetools-win-15859902_latest.zip'
Download 'https://dl.google.com/android/repository/commandlinetools-win-15859902_latest.zip' $cmdzip
$hash=(Get-FileHash $cmdzip -Algorithm SHA256).Hash.ToLowerInvariant()
if($hash -ne '90ae805d20434428bffcb699c290860f19bb5f66a67e6b330067e3de801fb04a'){throw "SDK commandline ZIP checksum mismatch: $hash"}
Log 'CMDLINE_SHA256_VERIFIED'
$stage=Join-Path $root 'cmdline-stage'
if(!(Test-Path (Join-Path $sdk 'cmdline-tools\latest\bin\sdkmanager.bat'))){
 New-Item -ItemType Directory -Force $stage|Out-Null
 Expand-Archive -LiteralPath $cmdzip -DestinationPath $stage -Force
 $dest=Join-Path $sdk 'cmdline-tools\latest'
 New-Item -ItemType Directory -Force $dest|Out-Null
 Copy-Item -Path (Join-Path $stage 'cmdline-tools\*') -Destination $dest -Recurse -Force
}
Log 'CMDLINE_TOOLS_INSTALLED'
$jdkzip=Join-Path $downloads 'temurin-17-jdk.zip'
Download 'https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jdk/hotspot/normal/eclipse' $jdkzip
if(!(Test-Path (Join-Path $jdk 'bin\java.exe'))){
 $stageJ=Join-Path $root 'jdk-stage';New-Item -ItemType Directory -Force $stageJ|Out-Null
 Expand-Archive -LiteralPath $jdkzip -DestinationPath $stageJ -Force
 $source=Get-ChildItem -Path $stageJ -Directory |Where-Object {Test-Path (Join-Path $_.FullName 'bin\java.exe')}|Select-Object -First 1
 if(!$source){throw 'JDK extract missing java.exe'}
 Copy-Item -Path (Join-Path $source.FullName '*') -Destination $jdk -Recurse -Force
}
Log 'JDK17_INSTALLED'
$env:JAVA_HOME=$jdk
$env:ANDROID_HOME=$sdk
$env:ANDROID_SDK_ROOT=$sdk
$env:PATH=(Join-Path $jdk 'bin')+';'+$env:PATH
$gradlezip=Join-Path $downloads 'gradle-8.9-bin.zip'
Download 'https://services.gradle.org/distributions/gradle-8.9-bin.zip' $gradlezip
if(!(Test-Path (Join-Path $gradle 'gradle-8.9\bin\gradle.bat'))){
 Expand-Archive -LiteralPath $gradlezip -DestinationPath $gradle -Force
}
Log 'GRADLE_8_9_INSTALLED'
$manager=Join-Path $sdk 'cmdline-tools\latest\bin\sdkmanager.bat'
Log 'SDK_PACKAGES_INSTALLING'
& $manager --sdk_root=$sdk 'platform-tools' 'platforms;android-35' 'build-tools;35.0.0' 'cmdline-tools;latest' 2>&1 | ForEach-Object { if($_){$msg=[string]$_;if($msg -match 'error|failed|license|installing|done|100%'){Log $msg.Substring(0,[Math]::Min($msg.Length,260))}} }
if($LASTEXITCODE -ne 0){throw "sdkmanager exit $LASTEXITCODE"}
Log 'SDK_PACKAGES_INSTALLED'
$project='C:\Users\Riyaad\Documents\GitHub\Niblit\android\NiblitMobile'
$env:GRADLE_USER_HOME=Join-Path $root 'gradle-home'
Set-Location $project
& (Join-Path $gradle 'gradle-8.9\bin\gradle.bat') wrapper --gradle-version 8.9 2>&1 | ForEach-Object {if($_){Log ([string]$_)}}
if($LASTEXITCODE -ne 0){throw "gradle wrapper exit $LASTEXITCODE"}
Log 'GRADLE_WRAPPER_READY'
& '.\gradlew.bat' ':app:assembleDebug' '--no-daemon' 2>&1 | ForEach-Object {if($_){$msg=[string]$_;if($msg -match 'failed|error|BUILD|Downloading|Task |What went wrong|Could not'){Log $msg.Substring(0,[Math]::Min($msg.Length,300))}}}
if($LASTEXITCODE -ne 0){throw "android build exit $LASTEXITCODE"}
$apk=Join-Path $project 'app\build\outputs\apk\debug\app-debug.apk'
if(!(Test-Path $apk)){throw 'APK missing after build'}
Log ("ANDROID_APK_SUCCESS bytes="+(Get-Item $apk).Length+" path="+$apk)
