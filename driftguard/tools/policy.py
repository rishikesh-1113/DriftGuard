"""
Tool: check_policy_rules
Wraps the Phase 1 rule-based checker as a callable tool.
This is the ground truth — AI findings are validated against this.
Read-only. No writes.
"""

from dataclasses import dataclass, field
from typing import List
from driftguard.checker.rules import run_checks, Violation


@dataclass
class PolicyCheckResult:
    path: str
    violations: List[Violation] = field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0

    @property
    def summary(self) -> str:
        if not self.violations:
            return "No violations found."
        lines = [f"[{v.severity}] {v.rule}: {v.message}" for v in self.violations]
        return "\n".join(lines)


def check_policy_rules(path: str, content: str) -> PolicyCheckResult:
    """
    Run all rule-based checks on a manifest or Dockerfile.
    Returns structured result with all violations.
    """
    violations = run_checks(path, content)
    return PolicyCheckResult(path=path, violations=violations)
