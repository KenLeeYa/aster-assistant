from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class RiskLevel(StrEnum):
    R0_READ_LOCAL = "R0_READ_LOCAL"
    R1_READ_EXTERNAL = "R1_READ_EXTERNAL"
    R2_CREATE_REVERSIBLE = "R2_CREATE_REVERSIBLE"
    R3_MODIFY = "R3_MODIFY"
    R4_DELETE_OR_EXECUTE = "R4_DELETE_OR_EXECUTE"
    R5_FINANCIAL_OR_PRIVILEGED = "R5_FINANCIAL_OR_PRIVILEGED"


class PolicyDecision(BaseModel):
    allowed: bool
    requires_approval: bool
    requires_two_step: bool = False
    reason: str


def classify_permission(risk: RiskLevel, *, external_write: bool = False) -> PolicyDecision:
    if risk in {RiskLevel.R0_READ_LOCAL, RiskLevel.R1_READ_EXTERNAL}:
        return PolicyDecision(allowed=True, requires_approval=False, reason="audited read")
    if risk is RiskLevel.R2_CREATE_REVERSIBLE and not external_write:
        return PolicyDecision(
            allowed=True,
            requires_approval=False,
            reason="reversible internal draft",
        )
    if risk is RiskLevel.R5_FINANCIAL_OR_PRIVILEGED:
        return PolicyDecision(
            allowed=False,
            requires_approval=True,
            requires_two_step=True,
            reason="financial or privileged actions are never autonomous",
        )
    return PolicyDecision(
        allowed=True,
        requires_approval=True,
        requires_two_step=risk is RiskLevel.R4_DELETE_OR_EXECUTE,
        reason="consequential action requires scoped approval",
    )
