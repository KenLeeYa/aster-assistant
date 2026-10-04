from pathlib import Path

import yaml
from ky_jarvis_core.domain.skills import load_skill

EXPECTED_SKILLS = {"demo-workflow"}


def test_all_requested_skills_are_complete_and_fail_closed() -> None:
    root = Path("skills")
    loaded = {path.name: load_skill(path) for path in root.iterdir() if path.is_dir()}

    assert set(loaded) == EXPECTED_SKILLS
    for skill in loaded.values():
        assert skill.manifest.enabled_by_default is False
        assert skill.manifest.voice_intents
        assert skill.permissions.read
        assert skill.permissions.forbidden
        changelog = (skill.path / "CHANGELOG.md").read_text(encoding="utf-8")
        assert skill.manifest.version in changelog
        for intent in skill.manifest.voice_intents:
            if intent.risk_level.value.startswith(("R2", "R3", "R4", "R5")):
                assert intent.requires_approval is True


def test_skill_fixture_cases_and_consequential_action_coverage() -> None:
    loaded = [load_skill(path) for path in Path("skills").iterdir() if path.is_dir()]
    approval_actions = {
        action.casefold() for skill in loaded for action in skill.permissions.approval_required
    }
    forbidden_actions = {
        action.casefold() for skill in loaded for action in skill.permissions.forbidden
    }

    for skill in loaded:
        fixture = yaml.safe_load((skill.path / "tests" / "cases.yaml").read_text(encoding="utf-8"))
        assert isinstance(fixture.get("cases"), list)
        assert len(fixture["cases"]) >= 2
        assert all(case.get("name") and case.get("expected_state") for case in fixture["cases"])

    for action in ("publish", "send", "move"):
        assert any(action in permission for permission in approval_actions)
    assert any(
        "execute" in intent.name for skill in loaded for intent in skill.manifest.voice_intents
    )
    assert any("delete" in permission for permission in forbidden_actions)
