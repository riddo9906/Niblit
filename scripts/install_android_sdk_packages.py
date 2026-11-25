"""Finish the Android toolchain install on D: using subprocess, preserving logs."""
import os
import subprocess
import sys
from pathlib import Path

root = Path(r"D:\NiblitAIOS\toolchains\android")
sdk = root / "sdk"
jdk = root / "jdk17"
gradle = root / "gradle" / "gradle-8.9" / "bin" / "gradle.bat"
manager = sdk / "cmdline-tools" / "latest" / "bin" / "sdkmanager.bat"
log = root / "sdk-packages.log"
status = root / "install-status.log"
project = Path(r"C:\Users\Riyaad\Documents\GitHub\Niblit\android\NiblitMobile")
env = os.environ.copy()
env.update({
    "JAVA_HOME":str(jdk), "ANDROID_HOME":str(sdk), "ANDROID_SDK_ROOT":str(sdk),
    "GRADLE_USER_HOME":str(root / "gradle-home"),
    "PATH": str(jdk / "bin") + ";" + env.get("PATH",""),
})
def note(msg):
    with status.open("a",encoding="utf-8") as f:f.write(msg+"\n")
    print(msg,flush=True)
def step(label,cmd,*,input=None,cwd=None,timeout=1800):
    note(label+" STARTED")
    with log.open("a",encoding="utf-8") as f:
        f.write("\n=== "+label+" ===\n")
        f.flush()
        r=subprocess.run(cmd,input=input,stdout=f,stderr=subprocess.STDOUT,text=True,
                         env=env,cwd=str(cwd) if cwd else None,timeout=timeout)
    note(label+" EXIT="+str(r.returncode))
    if r.returncode:raise RuntimeError(label+" returned "+str(r.returncode)+" (see "+str(log)+")")
if __name__=="__main__":
    step("ANDROID_LICENSES", [str(manager), "--sdk_root="+str(sdk), "--licenses"],
         input="y\n"*200,timeout=600)
    step("ANDROID_PACKAGES",[str(manager),"--sdk_root="+str(sdk),
         "platform-tools","platforms;android-35","build-tools;35.0.0"],input="y\n"*200)
    if not (sdk/"platforms"/"android-35"/"android.jar").is_file():
        raise RuntimeError("android.jar is missing")
    note("ANDROID_PLATFORM35_READY")
    step("GRADLE_WRAPPER",[str(gradle),"wrapper","--gradle-version","8.9"],
         cwd=project,timeout=900)
    step("APK_BUILD",[str(project/"gradlew.bat"),":app:assembleDebug","--no-daemon"],
         cwd=project,timeout=1800)
    apk=project/"app"/"build"/"outputs"/"apk"/"debug"/"app-debug.apk"
    if not apk.is_file():raise RuntimeError("APK missing despite successful build")
    note("ANDROID_APK_BUILT "+str(apk)+" bytes="+str(apk.stat().st_size))
