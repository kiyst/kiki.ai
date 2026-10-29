from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RiskLevel(StrEnum):
    READ_ONLY = "read_only"
    LOCAL_WRITE = "local_write"
    EXECUTE = "execute"
    EXTERNAL_SIDE_EFFECT = "external_side_effect"
    DESTRUCTIVE = "destructive"


@dataclass(frozen=True)
class ToolPolicy:
    risk: RiskLevel
    confirmation_required: bool
    description: str


READ_ONLY = ToolPolicy(
    RiskLevel.READ_ONLY,
    False,
    "Reads local or public data without changing user state.",
)
LOCAL_WRITE = ToolPolicy(
    RiskLevel.LOCAL_WRITE,
    True,
    "Changes files inside an explicitly selected workspace.",
)
EXECUTE = ToolPolicy(
    RiskLevel.EXECUTE,
    True,
    "Runs a local command or generated program.",
)
EXTERNAL_SIDE_EFFECT = ToolPolicy(
    RiskLevel.EXTERNAL_SIDE_EFFECT,
    True,
    "Changes state outside the local assistant.",
)
DESTRUCTIVE = ToolPolicy(
    RiskLevel.DESTRUCTIVE,
    True,
    "Deletes, overwrites, or irreversibly changes data.",
)


def requires_confirmation(policy: ToolPolicy) -> bool:
    return policy.confirmation_required or policy.risk in {
        RiskLevel.EXTERNAL_SIDE_EFFECT,
        RiskLevel.DESTRUCTIVE,
    }
