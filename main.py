"""
DriftGuard CLI entry point.
Usage:
  python main.py                        # rule-based checker only (Phase 1)
  python main.py --agent <file_path>    # full LangGraph agent (Phase 3)
"""

import os
import sys
from driftguard.checker.rules import run_checks, Violation
from typing import List


SEVERITY_PREFIX = {
    "HIGH": "[HIGH]",
    "MEDIUM": "[MEDIUM]",
    "LOW": "[LOW]",
}


def print_violations(file_path: str, violations: List[Violation]):
    if not violations:
        print(f"\n[OK] {file_path} - No violations found.")
        return

    print(f"\n{'='*60}")
    print(f"File: {file_path}")
    print(f"{'='*60}")
    for v in violations:
        prefix = SEVERITY_PREFIX.get(v.severity, "[LOW]")
        line_info = f" (line {v.line})" if v.line else ""
        print(f"{prefix} {v.rule}{line_info}")
        print(f"   {v.message}")


def run_rule_checker():
    print("DriftGuard - Phase 1: Rule-Based Checker")
    print("Scanning samples/bad-manifests ...\n")
    for root, _, files in os.walk("samples/bad-manifests"):
        for filename in files:
            if filename.endswith((".yaml", ".yml")) or "Dockerfile" in filename:
                file_path = os.path.join(root, filename)
                with open(file_path, "r") as f:
                    content = f.read()
                violations = run_checks(file_path, content)
                print_violations(file_path, violations)


def run_agent(file_path: str):
    from driftguard.agent.graph import agent

    print(f"\nDriftGuard - Phase 3: Agent Review")
    print(f"Reviewing: {file_path}\n")

    result = agent.invoke({"file_path": file_path, "file_content": ""})

    print(result["pr_comment"])


if __name__ == "__main__":
    if "--agent" in sys.argv:
        idx = sys.argv.index("--agent")
        if idx + 1 >= len(sys.argv):
            print("Usage: python main.py --agent <file_path>")
            sys.exit(1)
        run_agent(sys.argv[idx + 1])
    else:
        run_rule_checker()
