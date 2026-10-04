from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_stop_rechecks_parent_after_taskkill_child_race() -> None:
    script = (REPOSITORY_ROOT / "scripts" / "stop.ps1").read_text(encoding="utf-8")
    taskkill = script.index("$taskkillOutput = & taskkill.exe")
    bounded_wait = script.index("for ($attempt", taskkill)

    assert 'throw "Failed to stop PID' not in script[taskkill:bounded_wait]
    assert '$process = Get-CimInstance Win32_Process -Filter "ProcessId = ' in script[bounded_wait:]


def test_inventory_reports_dynamic_model_and_device_state() -> None:
    script = (REPOSITORY_ROOT / "scripts" / "inventory.ps1").read_text(encoding="utf-8")

    assert "http://127.0.0.1:11434/api/tags" in script
    assert "models = $ollamaModels" in script
    assert "No model was downloaded by this work." not in script
    assert "No Android device was connected or authorized." not in script
    assert "physical-device testing remains NOT RUN" not in script
    assert "physical-device test status is tracked" in script


def test_android_checksum_manifest_includes_instrumentation_apk() -> None:
    script = (REPOSITORY_ROOT / "scripts" / "sbom.ps1").read_text(encoding="utf-8")

    assert "app-debug-androidTest.apk" in script


def test_package_script_keeps_desktop_android_and_sbom_lanes_independent() -> None:
    package = (REPOSITORY_ROOT / "scripts" / "package.ps1").read_text(encoding="utf-8")
    sbom = (REPOSITORY_ROOT / "scripts" / "sbom.ps1").read_text(encoding="utf-8")
    rust_toolchain = (REPOSITORY_ROOT / "rust-toolchain.toml").read_text(encoding="utf-8")

    assert "Invoke-PackageLane -Name 'Windows desktop'" in package
    assert "Invoke-PackageLane -Name 'Android'" in package
    assert "Invoke-PackageLane -Name 'SBOM/checksums'" in package
    assert "$childPowerShellPath -NoProfile -File" in package
    assert "reports\\package_report.md" in package
    assert "WINDOWS_ARTIFACT_SHA256SUMS" in package
    assert "signing key or password is created" in package
    assert "windows-desktop.cdx.json" in sbom
    assert "AndroidEmulatorSerial" in package
    assert "instrumented tests were not rerun" in package
    assert 'channel = "1.98.0"' in rust_toolchain
    assert 'profile = "minimal"' in rust_toolchain


def test_backup_and_restore_are_complete_and_fail_closed() -> None:
    backup = (REPOSITORY_ROOT / "scripts" / "backup.ps1").read_text(encoding="utf-8")
    prune = (REPOSITORY_ROOT / "scripts" / "prune-backups.ps1").read_text(encoding="utf-8")
    restore = (REPOSITORY_ROOT / "scripts" / "restore.ps1").read_text(encoding="utf-8")

    assert "configuration_files" in backup
    assert "skill_files" in backup
    assert "artifact_files" in backup
    assert "excluded_secret_sources" in backup
    assert "BackupRoot must remain outside the repository" in backup
    assert "Refusing to recursively back up a filesystem root" in backup
    assert "Refusing to follow a reparse-point backup root" in backup
    assert "hasReparseParent" in backup
    assert "runtime/operator" in backup
    assert "database'" in backup
    assert "files = $backupFiles" in backup
    assert "RetentionDays" in backup
    assert "ConfirmRetentionPrune" in backup
    assert "requires a positive -RetentionDays value" in backup
    assert "prune-backups.ps1" in backup
    assert "ConfirmPrune" in prune
    assert "TryParseExact" in prune
    assert "manifest.json" in prune
    assert "Refusing to prune a filesystem root" in prune
    assert "reparse-point backup-root component" in prune
    assert "direct child of BackupRoot" in prune
    assert "$PSCmdlet.ShouldProcess" in prune
    assert "Remove-Item -LiteralPath $candidatePath -Recurse -Force" in prune
    assert "ConfirmReplaceActiveData" in restore
    assert restore.index("if (-not $ConfirmReplaceActiveData)") < restore.index(
        "alter database $activeDatabase"
    )
    assert "restore-test.ps1" in restore
    assert "backup.ps1" in restore
    assert "RecoveredFilesRoot" in restore
    assert "RecoveredFilesRoot must remain outside the repository" in restore
    assert "never overwritten automatically" in restore
    assert "Stop all recorded KY-JARVIS writers" in restore
    assert "No connection was terminated automatically" in restore
    assert "Unable to activate or roll back automatically" in restore
    assert "Assert-NoReparseComponent" in restore
    assert "ky_jarvis_pre_restore_" in restore
    assert "--clean" not in restore


def test_launch_at_login_scripts_require_explicit_current_user_action() -> None:
    register = (REPOSITORY_ROOT / "scripts" / "register-startup.ps1").read_text(encoding="utf-8")
    unregister = (REPOSITORY_ROOT / "scripts" / "unregister-startup.ps1").read_text(
        encoding="utf-8"
    )
    daily_register = (REPOSITORY_ROOT / "scripts" / "register-daily-backup.ps1").read_text(
        encoding="utf-8"
    )
    daily_unregister = (REPOSITORY_ROOT / "scripts" / "unregister-daily-backup.ps1").read_text(
        encoding="utf-8"
    )

    assert "if (-not $Confirm)" in register
    assert "if (-not $Confirm)" in unregister
    assert "GetFolderPath('Startup')" in register + unregister
    assert "KY-JARVIS current-user startup" in register + unregister
    assert "Refusing to replace" in register
    assert "Refusing to remove" in unregister
    assert "Register-ScheduledTask" not in register
    assert "RunAs" not in register
    assert "if (-not $Confirm)" in daily_register + daily_unregister
    assert "New-ScheduledTaskTrigger -Daily" in daily_register
    assert "-LogonType Interactive -RunLevel Limited" in daily_register
    assert "-ConfirmRetentionPrune" in daily_register
    assert "Refusing to replace a scheduled task not owned" in daily_register
    assert "Refusing to remove a scheduled task not owned" in daily_unregister


def test_model_pull_script_detects_before_explicit_download() -> None:
    script = (REPOSITORY_ROOT / "scripts" / "pull-models.ps1").read_text(encoding="utf-8")

    probe = script.index("http://127.0.0.1:11434/api/tags")
    approval = script.index("if (-not $ConfirmDownload)")
    pull = script.index("& $ollama.Source pull $model")
    assert probe < approval < pull
    assert "qwen3:8b" in script
    assert "nomic-embed-text:latest" in script
    assert "installed manifests were inspected without starting it" in script
    assert "No download was started" in script


def test_full_test_script_runs_isolated_playwright_when_ports_are_free() -> None:
    script = (REPOSITORY_ROOT / "scripts" / "test.ps1").read_text(encoding="utf-8")
    runner = (REPOSITORY_ROOT / "tests" / "e2e" / "run_core.py").read_text(encoding="utf-8")

    assert "SkipWebE2E" in script
    assert script.index("uv run ruff format --check .") < script.index("uv run ruff check .")
    assert "@(3100, 8765)" in script
    assert "web e2e BLOCKED" in script
    assert "$failures += 'web e2e (isolated ports unavailable)'" in script
    assert "pnpm@11.24.0 --dir apps/web test:e2e" in script
    assert runner.index('startswith("KY_JARVIS_")') < runner.index("from ky_jarvis_core.main")
    assert 'os.environ["LOCALAPPDATA"]' in runner
    assert "database_url=None" in runner
    assert "operator_bootstrap_secret=None" in runner


def test_android_release_scan_checks_manifest_archives_and_signing() -> None:
    script = (REPOSITORY_ROOT / "scripts" / "android-security-scan.ps1").read_text(encoding="utf-8")

    assert "usesCleartextTraffic" in script
    assert "prohibitedPermissions" in script
    assert "forbiddenArchivePatterns" in script
    assert "apksigner verify --verbose" in script
    assert "jar is unsigned" in script


def test_android_doctor_covers_emulator_licenses_and_redacted_report() -> None:
    script = (REPOSITORY_ROOT / "scripts" / "android-doctor.ps1").read_text(encoding="utf-8")

    assert "Android Studio" in script
    assert "SDK license receipts" in script
    assert "-list-avds" in script
    assert "serial_sha256_prefix" in script
    assert "reports\\android_environment.md" in script


def test_security_scan_keeps_an_all_severity_dependency_inventory() -> None:
    script = (REPOSITORY_ROOT / "scripts" / "security-scan.ps1").read_text(encoding="utf-8")

    assert "trivy-all.json" in script
    assert "--scanners vuln" in script
    assert "trivy-all=$trivyAllExit" in script


def test_android_compatibility_entrypoints_and_install_safety() -> None:
    build = (REPOSITORY_ROOT / "scripts" / "build-android.ps1").read_text(encoding="utf-8")
    pipeline = (REPOSITORY_ROOT / "scripts" / "android-build.ps1").read_text(encoding="utf-8")
    install = (REPOSITORY_ROOT / "scripts" / "android-install.ps1").read_text(encoding="utf-8")

    assert "android-build.ps1" in build
    assert "':app:ktlintCheck'" in pipeline
    assert "':app:detekt'" in pipeline
    assert "[string[]]$packageTasks" in pipeline
    assert "connectedDebugAndroidTest" in pipeline
    assert "emulator target only; physical devices are refused" in pipeline
    assert "install -r" in install
    assert "serial_sha256_prefix" in install
    assert "shell am start -n" in install
    assert "uninstall" not in install.lower()


def test_device_admin_scripts_fail_closed_until_operator_auth_exists() -> None:
    pair = (REPOSITORY_ROOT / "scripts" / "pair-device.ps1").read_text(encoding="utf-8")
    revoke = (REPOSITORY_ROOT / "scripts" / "revoke-device.ps1").read_text(encoding="utf-8")

    assert "OS-protected desktop operator session" in pair
    assert "OS-protected desktop operator session" in revoke
    assert "Invoke-RestMethod" not in pair + revoke
    assert "-Confirm" in revoke


def test_postgres_profile_uses_only_the_file_secret_contract() -> None:
    script = (REPOSITORY_ROOT / "scripts" / "test-postgres.ps1").read_text(encoding="utf-8")

    assert "Remove-Item Env:KY_JARVIS_DB_PASSWORD " in script
    assert "Remove-Item Env:KY_JARVIS_DB_PASSWORD_FILE_CONTAINER " in script
    assert "$env:KY_JARVIS_DB_PASSWORD = $password" not in script
