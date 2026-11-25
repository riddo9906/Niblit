plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}
android {
    namespace = "ai.niblit.mobile"
    compileSdk = 35
    defaultConfig {
        applicationId = "ai.niblit.mobile"
        minSdk = 26
        targetSdk = 35
        versionCode = 4
        versionName = "0.3.0"
    }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
}
