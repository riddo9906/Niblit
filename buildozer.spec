[app]

# (str) Title of your application
title = Niblit AIOS

# (str) Package name
package.name = niblit

# (str) Package domain (needed for android/ios packaging)
package.domain = org.niblit

# (str) Source code where the main.py live
source.dir = .

# (list) Source files to include (let empty to include all the files)
source.include_exts = py,png,jpg,kv,atlas,sh,json

# (list) Source files to exclude
source.exclude_exts = spec

# (list) List of directory to exclude (let empty to not exclude anything)
source.exclude_dirs = tests, bin, .git, __pycache__, .github, chat_logs, ProjectOne

# (str) Application versioning (method 1)
version = 2.0.0

# (list) Application requirements
# ─────────────────────────────────────────────────────────────────────────────
# Runtime requirements for the Kivy APK.
# Heavy AI/ML packages (torch, transformers, etc.) are NOT bundled here —
# they are pip-installed inside the proot rootfs on first launch.
requirements =
    python3,
    kivy==2.3.0,
    requests,
    python-dotenv,
    certifi,
    urllib3,
    charset-normalizer,
    idna

# (list) Garden requirements
#garden_requirements =

# (str) Presplash of the application
#presplash.filename = %(source.dir)s/data/presplash.png

# (str) Icon of the application
#icon.filename = %(source.dir)s/data/icon.png

# (str) Supported orientation (one of landscape, sensorLandscape, portrait or all)
orientation = portrait

# (list) List of service to declare
#services = NAME:ENTRYPOINT_TO_PY,NAME2:ENTRYPOINT2_TO_PY

#
# OSX Specific
#

#
# author © <FullName>

# change the major version of python used by the app
osx.python_version = 3

# Kivy version to use
osx.kivy_version = 2.3.0

#
# Android specific
#

# (bool) Indicate if the application should be fullscreen or not
fullscreen = 0

# (string) Presplash background color (for android toolchain)
android.presplash_color = #0d0d10

# (str) Adaptive icon of the application (used if Android API level is 26+ at runtime)
#android.adaptive_icon_fg = %(source.dir)s/data/icon_fg.png
#android.adaptive_icon_bg = %(source.dir)s/data/icon_bg.png

# (list) Permissions
# INTERNET + network state for API/download mode.
# READ/WRITE_EXTERNAL_STORAGE to read/write the rootfs on external storage
# if the user opts for that.
# REQUEST_INSTALL_PACKAGES is needed to allow Niblit's proot to install apks
# inside its own userland (advanced).
android.permissions =
    INTERNET,
    ACCESS_NETWORK_STATE,
    READ_EXTERNAL_STORAGE,
    WRITE_EXTERNAL_STORAGE

# (int) Target Android API, should be as high as possible.
android.api = 33

# (int) Minimum API your APK / AAB will support.
android.minapi = 21

# (int) Android SDK version to use
android.sdk = 33

# (str) Android NDK version to use
android.ndk = 25b

# (int) Android NDK API to use.  Should usually match android.minapi.
android.ndk_api = 21

# (list) Architectures to build for.
# arm64-v8a  — modern 64-bit Android devices (primary target)
# armeabi-v7a — older 32-bit ARM devices (compatibility)
android.archs = arm64-v8a, armeabi-v7a

# (bool) Use --private data storage (True) or --dir public storage (False)
# Must be True so the rootfs lives in the app-private sandbox.
android.private_storage = True

# (str) Android logcat filters to use
android.logcat_filters = *:S python:D

# (bool) Android allow backup feature (Android API>=23)
android.allow_backup = True

# (str) The format used to package the app for release mode (aab or apk or aar).
android.release_artifact = apk

# (str) The format used to package the app for debug mode (apk or aar).
android.debug_artifact = apk

# (list) Add additional jar/aar archives into the libs directory
#android.add_jars = foo.jar,bar.jar,...

# (list) Add additional src/java directories to the build
#android.add_src =

# (list) Assets to include in the APK.
# The setup_niblit.sh script is bundled so the proot setup can run it
# at first launch without any network access.
# Prebuilt static proot binaries should be placed in assets/ — the
# APKBootstrap / ProotEnvironment will look for them there.
#
# To bundle a rootfs tarball (highly recommended for offline-first usage):
#   1. Download the Alpine minirootfs:
#        https://dl-cdn.alpinelinux.org/alpine/v3.19/releases/aarch64/alpine-minirootfs-3.19.1-aarch64.tar.gz
#   2. Rename it to  assets/alpine-rootfs.tar.gz
#   3. Uncomment the line below.
#
#android.add_assets = assets/setup_niblit.sh:assets/setup_niblit.sh,assets/alpine-rootfs.tar.gz:assets/alpine-rootfs.tar.gz

# For now ship only the setup script; the rootfs is downloaded on demand.
android.add_assets = assets/setup_niblit.sh:assets/setup_niblit.sh

# (str) python-for-android bootstrap
# sdl2 is the standard Kivy bootstrap
p4a.bootstrap = sdl2

# (bool) Use --private data storage
# android.private_storage = True

#
# Python for android (p4a) specific
#

# (str) python-for-android URL to use for p4a
#p4a.url =

# (str) The directory in which python-for-android should look for your own build recipes (if any)
#p4a.local_recipes =

# (str) Filename to the hook for p4a
#p4a.hook =

#
# iOS specific
#

# (str) Path to a custom kivy-ios folder
#ios.kivy_ios_url = https://github.com/kivy/kivy-ios
#ios.kivy_ios_tag = master

# (str) Name of the certificate to use for signing the debug version
#ios.codesign.debug = "iPhone Developer: <lastname> <firstname> (<hexstring>)"

# (str) Name of the certificate to use for signing the release version
#ios.codesign.release = %(ios.codesign.debug)s

[buildozer]

# (int) Log level (0 = error only, 1 = info, 2 = debug (with command output))
log_level = 2

# (int) Display warning if buildozer is run as root (0 = False, 1 = True)
warn_on_root = 1

# (str) Path to build artifact storage, absolute or relative to spec file
# build_dir = ./.buildozer

# (str) Path to build output (i.e. .apk, .aab, .ipa) storage
# bin_dir = ./bin

