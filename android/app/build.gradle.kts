import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

// Token API — priorité : local.properties > variable d'env > gradle property.
// local.properties est gitignore et lu automatiquement par Android Studio.
val localProps = Properties().apply {
    val f = rootProject.file("local.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}
val apiToken: String = localProps.getProperty("TENNISBOSS_API_TOKEN")
    ?: System.getenv("TENNISBOSS_API_TOKEN")
    ?: (project.findProperty("TENNISBOSS_API_TOKEN") as? String)
    ?: ""

android {
    namespace = "com.tennisboss.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.tennisboss.app"
        minSdk = 24
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        // Debug uniquement : le vrai appareil (DEFAULT_BASE_URL) passe par le
        // Worker Cloudflare qui injecte le token côté serveur, donc release ne
        // doit JAMAIS embarquer le secret — même si TENNISBOSS_API_TOKEN traîne
        // dans l'environnement local au moment du build.
        debug {
            buildConfigField("String", "TENNISBOSS_API_TOKEN", "\"$apiToken\"")
        }
        release {
            buildConfigField("String", "TENNISBOSS_API_TOKEN", "\"\"")
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    packaging {
        // WSL build : le NDK installé est Windows-only (pas de linux-x86_64 llvm-strip).
        // Le stripping des .so est ignoré — sans impact fonctionnel en debug.
        jniLibs { keepDebugSymbols += "**/*.so" }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    // Jetpack Compose (BOM gère les versions cohérentes)
    implementation(platform("androidx.compose:compose-bom:2024.09.03"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    debugImplementation("androidx.compose.ui:ui-tooling")

    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.activity:activity-compose:1.9.2")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.6")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.6")

    // Stockage chiffré pour les secrets sensibles (token API backup)
    implementation("androidx.security:security-crypto:1.1.0-alpha06")

    // Google Fonts pour la typo hi-tech (Inter) — version gérée par le BOM Compose
    implementation("androidx.compose.ui:ui-text-google-fonts")

    // Réseau : Retrofit + Gson + coroutines
    implementation("com.squareup.retrofit2:retrofit:2.11.0")
    implementation("com.squareup.retrofit2:converter-gson:2.11.0")
    implementation("com.squareup.okhttp3:logging-interceptor:4.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")

    // Background polling + notifications push locales
    implementation("androidx.work:work-runtime-ktx:2.9.1")

    // Tests unitaires (JVM)
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.8.1")
}
