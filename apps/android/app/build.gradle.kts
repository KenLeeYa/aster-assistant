plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
    id("io.gitlab.arturbosch.detekt")
    id("org.jlleitschuh.gradle.ktlint")
}

detekt {
    buildUponDefaultConfig = true
    config.setFrom(rootProject.files("config/detekt/detekt.yml"))
    parallel = false
}

ktlint {
    version.set("1.8.0")
    android.set(true)
    outputToConsole.set(true)
    ignoreFailures.set(false)
    filter {
        exclude("**/build/**")
    }
}

configurations.configureEach {
    resolutionStrategy.eachDependency {
        when (requested.group) {
            "io.netty" -> {
                useVersion("4.1.137.Final")
                because("align AGP test-tool transitive Netty modules to security-fixed release")
            }

            "org.bouncycastle" -> {
                useVersion("1.84")
                because("align AGP lint/test transitive Bouncy Castle modules to fixed release")
            }

            "org.apache.commons" -> {
                if (requested.name == "commons-lang3") {
                    useVersion("3.18.0")
                    because("upgrade AGP lint transitive Commons Lang to a security-fixed release")
                }
            }

            "org.apache.httpcomponents" -> {
                if (
                    requested.name == "httpclient" || requested.name == "httpmime"
                ) {
                    useVersion("4.5.13")
                    because("upgrade AGP lint transitive HttpClient to a security-fixed release")
                }
            }
        }
    }
}

android {
    namespace = "tw.ky.jarvis"
    compileSdk {
        version =
            release(37) {
                minorApiLevel = 1
            }
    }

    defaultConfig {
        applicationId = "tw.ky.jarvis"
        minSdk = 29
        targetSdk = 37
        versionCode = 1
        versionName = "0.1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        buildConfigField("String", "CORE_BASE_URL", "\"\"")
        resValue("string", "shortcut_target_package", "tw.ky.jarvis")
    }

    buildTypes {
        debug {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
            buildConfigField("String", "CORE_BASE_URL", "\"http://127.0.0.1:8765\"")
            resValue("string", "shortcut_target_package", "tw.ky.jarvis.debug")
        }
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    buildFeatures {
        buildConfig = true
        compose = true
        resValues = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    packaging {
        resources.excludes += setOf("/META-INF/{AL2.0,LGPL2.1}")
    }

    lint {
        abortOnError = true
        checkReleaseBuilds = true
        warningsAsErrors = true
    }

    testOptions {
        unitTests.isReturnDefaultValues = false
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2026.08.00")
    implementation(composeBom)
    androidTestImplementation(composeBom)

    implementation("androidx.core:core-ktx:1.19.0")
    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.fragment:fragment-ktx:1.9.0")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.11.0")
    implementation("androidx.biometric:biometric:1.1.0")

    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.7.0")
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}

dependencyLocking {
    lockAllConfigurations()
}
