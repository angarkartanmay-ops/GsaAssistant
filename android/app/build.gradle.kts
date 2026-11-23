plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "dev.havoc.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "dev.havoc.app"
        minSdk = 26
        targetSdk = 35
        versionCode = 2
        versionName = "1.1.0"
        // Phones are ARM; dropping emulator-only x86 builds of the speech engine halves the APK.
        ndk { abiFilters += listOf("arm64-v8a", "armeabi-v7a") }
    }

    // A fixed key committed with the repo: every build (here, your PC, GitHub Actions) signs the
    // same way, so a new APK installs over the old one. Fine for a personal sideloaded app; never
    // reuse this key for anything published.
    signingConfigs {
        create("sideload") {
            storeFile = rootProject.file("havoc-sideload.keystore")
            storePassword = "havoc-sideload"
            keyAlias = "havoc"
            keyPassword = "havoc-sideload"
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("sideload")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    // Offline keyword spotting for "Hey Havoc" (Apache-2.0). Runs entirely on the phone.
    implementation("com.alphacephei:vosk-android:0.3.75@aar")
    implementation("net.java.dev.jna:jna:5.18.1@aar")
}
