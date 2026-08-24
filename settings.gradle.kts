pluginManagement {
    repositories {
        val locIsCi =
                providers.gradleProperty("CI")
                .orElse(providers.environmentVariable("CI"))
                .map { it.equals("true", ignoreCase = true) }
                .orElse(false)
                .get()

        gradlePluginPortal()
        if (!locIsCi) {
            mavenLocal()
        }
        mavenCentral()
        maven {
            name = "algites-public-releases"
            url = uri("https://repo1.maven.org/maven2")
            mavenContent {
                releasesOnly()
            }
        }
        maven {
            name = "algites-public-snapshots"
            url = uri("https://dl.cloudsmith.io/public/algites/maven-snapshots-pub/")
            mavenContent {
                snapshotsOnly()
            }
        }
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        val locIsCi =
                providers.gradleProperty("CI")
                .orElse(providers.environmentVariable("CI"))
                .map { it.equals("true", ignoreCase = true) }
                .orElse(false)
                .get()

        if (!locIsCi) {
            mavenLocal()
        }
        mavenCentral()
        maven {
            name = "algites-public-releases"
            url = uri("https://repo1.maven.org/maven2")
            mavenContent {
                releasesOnly()
            }
        }
        maven {
            name = "algites-public-snapshots"
            url = uri("https://dl.cloudsmith.io/public/algites/maven-snapshots-pub/maven/")
            mavenContent {
                snapshotsOnly()
            }
        }
    }
}

apply(from = uri("https://raw.githubusercontent.com/Algites-EU/pub.gov.Algites/main/gradle/tool/repository/algites-root-settings-discovery.gradle.kts"))
