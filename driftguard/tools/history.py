"""
Tool: get_workload_history
Returns past approved incidents/fixes for a given workload, scoped to the
current repo. Backed by the same Qdrant memory used by the recall node.
"""

from dataclasses import dataclass, field
from typing import List

from driftguard.memory.recall import recall_similar_findings


@dataclass
class PastIncident:
    workload_name: str
    issue: str
    severity: str
    approved_fix: str


@dataclass
class WorkloadHistoryResult:
    workload_name: str
    incidents: List[PastIncident] = field(default_factory=list)

    @property
    def has_history(self) -> bool:
        return len(self.incidents) > 0


def get_workload_history(name: str, repo_name: str = "") -> WorkloadHistoryResult:
    """
    Fetch past approved reviews for a workload, scoped to repo_name.
    Uses the same Qdrant-backed recall as the agent's recall node.
    """
    past = recall_similar_findings(
        rule="general",
        message=name,
        file_path=name,
        repo_name=repo_name,
    )

    incidents = [
        PastIncident(
            workload_name=name,
            issue=p.get("message", ""),
            severity=p.get("severity", ""),
            approved_fix=p.get("approved_fix", ""),
        )
        for p in past
    ]

    return WorkloadHistoryResult(workload_name=name, incidents=incidents)
