from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_android_lockscreen_and_capture_source_policy() -> None:
    main_activity = (
        REPOSITORY_ROOT / "apps/android/app/src/main/java/tw/ky/jarvis/MainActivity.kt"
    ).read_text(encoding="utf-8")
    push_to_talk = (
        REPOSITORY_ROOT / "apps/android/app/src/main/java/tw/ky/jarvis/voice/PushToTalkService.kt"
    ).read_text(encoding="utf-8")

    assert "WindowManager.LayoutParams.FLAG_SECURE" in main_activity
    assert ".setVisibility(NotificationCompat.VISIBILITY_SECRET)" in push_to_talk
    assert "shouldStopForAudioFocusChange(change)" in push_to_talk
    assert "internal fun shouldStopForAudioFocusChange(change: Int): Boolean = change < 0" in (
        push_to_talk
    )
