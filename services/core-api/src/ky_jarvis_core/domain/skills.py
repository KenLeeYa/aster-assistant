from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ky_jarvis_core.domain.policy import RiskLevel

SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
READ_ONLY_RISKS = {RiskLevel.R0_READ_LOCAL, RiskLevel.R1_READ_EXTERNAL}


class VoiceIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    description: str = Field(min_length=1, max_length=240)
    risk_level: RiskLevel
    requires_approval: bool

    @model_validator(mode="after")
    def gate_mutation(self) -> VoiceIntent:
        if self.risk_level not in READ_ONLY_RISKS and not self.requires_approval:
            raise ValueError("non-read-only voice intents require central approval")
        return self


class SkillManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    version: str
    description: str = Field(min_length=1, max_length=500)
    enabled_by_default: bool = False
    voice_intents: tuple[VoiceIntent, ...]

    @model_validator(mode="after")
    def secure_defaults(self) -> SkillManifest:
        if not SEMVER_PATTERN.fullmatch(self.version):
            raise ValueError("skill version must use semantic versioning")
        if self.enabled_by_default:
            raise ValueError("project skills must be disabled by default")
        if not self.voice_intents:
            raise ValueError("skill must publish at least one bounded voice intent")
        return self


class SkillPermissions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    read: tuple[str, ...] = ()
    write: tuple[str, ...] = ()
    approval_required: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()


class LoadedSkill(BaseModel):
    path: Path
    manifest: SkillManifest
    permissions: SkillPermissions


def load_skill(path: Path) -> LoadedSkill:
    required = (
        "SKILL.md",
        "manifest.yaml",
        "permissions.yaml",
        "examples",
        "tests",
        "CHANGELOG.md",
    )
    missing = [name for name in required if not (path / name).exists()]
    if missing:
        raise ValueError(f"skill scaffold is incomplete: {', '.join(missing)}")
    manifest_data = yaml.safe_load((path / "manifest.yaml").read_text(encoding="utf-8"))
    permissions_data = yaml.safe_load((path / "permissions.yaml").read_text(encoding="utf-8"))
    manifest = SkillManifest.model_validate(manifest_data)
    if manifest.name != path.name:
        raise ValueError("manifest name must match the skill directory")
    permissions = SkillPermissions.model_validate(permissions_data)
    if permissions.write and not permissions.approval_required:
        raise ValueError("skills with write permissions must declare approval gates")
    return LoadedSkill(path=path, manifest=manifest, permissions=permissions)
