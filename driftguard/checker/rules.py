"""
Rule-based checks for Kubernetes manifests and Dockerfiles.
No LLM involved — pure Python logic. This is the ground truth.
"""

import yaml
from dataclasses import dataclass
from typing import List


@dataclass
class Violation:
    rule: str
    severity: str  # HIGH, MEDIUM, LOW
    message: str
    line: int = None


def check_kubernetes_manifest(content: str) -> List[Violation]:
    """Parse a YAML manifest and run all K8s rules against it."""
    violations = []

    try:
        manifest = yaml.safe_load(content)
    except yaml.YAMLError as e:
        return [Violation(rule="INVALID_YAML", severity="HIGH", message=f"Could not parse YAML: {e}")]

    if not manifest:
        return violations

    kind = manifest.get("kind", "")

    if kind in ("Role", "ClusterRole"):
        violations.extend(_check_role(manifest, kind))
        return violations

    if kind in ("RoleBinding", "ClusterRoleBinding"):
        violations.extend(_check_role_binding(manifest, kind))
        return violations

    if kind in ("Deployment", "DaemonSet", "StatefulSet", "Job", "CronJob"):
        spec = manifest.get("spec", {})
        template = spec.get("template", {})
        pod_spec = template.get("spec", {})
        containers = pod_spec.get("containers", [])

        # --- pod-level checks ---
        if pod_spec.get("hostNetwork") is True:
            violations.append(Violation(
                rule="HOST_NETWORK",
                severity="HIGH",
                message="Pod uses hostNetwork: true — bypasses network isolation, can sniff host traffic."
            ))

        if pod_spec.get("hostPID") is True:
            violations.append(Violation(
                rule="HOST_PID",
                severity="HIGH",
                message="Pod uses hostPID: true — container can see and signal all processes on the host."
            ))

        if pod_spec.get("hostIPC") is True:
            violations.append(Violation(
                rule="HOST_IPC",
                severity="HIGH",
                message="Pod uses hostIPC: true — container shares host IPC namespace, a container-escape vector."
            ))

        for volume in pod_spec.get("volumes", []) or []:
            if "hostPath" in volume:
                violations.append(Violation(
                    rule="HOST_PATH_VOLUME",
                    severity="HIGH",
                    message=f"Volume '{volume.get('name', 'unknown')}' mounts hostPath — gives the container access to the host filesystem."
                ))

        for container in containers:
            name = container.get("name", "unknown")

            # Rule: latest tag
            image = container.get("image", "")
            if image.endswith(":latest") or ":" not in image:
                violations.append(Violation(
                    rule="LATEST_TAG",
                    severity="HIGH",
                    message=f"Container '{name}' uses image '{image}' — avoid :latest, pin a specific version."
                ))

            # Rule: no resource limits/requests
            resources = container.get("resources", {})
            if not resources.get("limits") or not resources.get("requests"):
                violations.append(Violation(
                    rule="NO_RESOURCE_LIMITS",
                    severity="HIGH",
                    message=f"Container '{name}' has no resource requests/limits — can starve other pods."
                ))

            # Rule: privileged container
            security_ctx = container.get("securityContext", {})
            if security_ctx.get("privileged") is True:
                violations.append(Violation(
                    rule="PRIVILEGED_CONTAINER",
                    severity="HIGH",
                    message=f"Container '{name}' runs as privileged — full host access, major security risk."
                ))

            # Rule: allowPrivilegeEscalation not explicitly disabled
            if security_ctx.get("allowPrivilegeEscalation") is not False:
                violations.append(Violation(
                    rule="PRIVILEGE_ESCALATION_ALLOWED",
                    severity="HIGH",
                    message=f"Container '{name}' does not set allowPrivilegeEscalation: false — a compromised process could gain root."
                ))

            # Rule: readOnlyRootFilesystem not set
            if security_ctx.get("readOnlyRootFilesystem") is not True:
                violations.append(Violation(
                    rule="WRITABLE_ROOT_FILESYSTEM",
                    severity="MEDIUM",
                    message=f"Container '{name}' does not set readOnlyRootFilesystem: true — malware could persist by writing to the container's own filesystem."
                ))

            # Rule: capabilities not dropped
            capabilities = security_ctx.get("capabilities", {})
            dropped = capabilities.get("drop", [])
            if "ALL" not in dropped:
                violations.append(Violation(
                    rule="CAPABILITIES_NOT_DROPPED",
                    severity="MEDIUM",
                    message=f"Container '{name}' does not drop all Linux capabilities (capabilities.drop: [ALL]) — runs with more kernel privileges than most workloads need."
                ))

            # Rule: no liveness probe
            if not container.get("livenessProbe"):
                violations.append(Violation(
                    rule="NO_LIVENESS_PROBE",
                    severity="MEDIUM",
                    message=f"Container '{name}' has no liveness probe — Kubernetes can't detect if it's stuck."
                ))

            # Rule: no readiness probe
            if not container.get("readinessProbe"):
                violations.append(Violation(
                    rule="NO_READINESS_PROBE",
                    severity="MEDIUM",
                    message=f"Container '{name}' has no readiness probe — traffic may hit unready pods."
                ))

            # Rule: hardcoded secrets in env vars
            env_vars = container.get("env", [])
            secret_keywords = ["password", "secret", "token", "key", "api_key", "passwd"]
            for env in env_vars:
                env_name = env.get("name", "").lower()
                env_value = env.get("value")
                if env_value and any(kw in env_name for kw in secret_keywords):
                    violations.append(Violation(
                        rule="HARDCODED_SECRET",
                        severity="HIGH",
                        message=f"Container '{name}' has hardcoded secret in env var '{env.get('name')}' — use a Secret resource instead."
                    ))

    return violations


def _check_role(manifest: dict, kind: str) -> List[Violation]:
    """Check Role/ClusterRole for overly broad wildcard permissions."""
    violations = []
    rules = manifest.get("rules", []) or []
    role_name = manifest.get("metadata", {}).get("name", "unknown")

    for rule in rules:
        resources = rule.get("resources", [])
        verbs = rule.get("verbs", [])
        api_groups = rule.get("apiGroups", [])

        if "*" in resources or "*" in verbs or "*" in api_groups:
            violations.append(Violation(
                rule="RBAC_WILDCARD",
                severity="HIGH",
                message=f"{kind} '{role_name}' uses a wildcard ('*') in apiGroups/resources/verbs — grants broader access than almost any workload needs."
            ))

        if "secrets" in resources and any(v in verbs for v in ("get", "list", "watch", "*")):
            violations.append(Violation(
                rule="RBAC_SECRETS_ACCESS",
                severity="MEDIUM",
                message=f"{kind} '{role_name}' can read Secrets — restrict to the smallest group of roles that actually need this."
            ))

    return violations


def _check_role_binding(manifest: dict, kind: str) -> List[Violation]:
    """Check RoleBinding/ClusterRoleBinding for binding to cluster-admin."""
    violations = []
    role_ref = manifest.get("roleRef", {})
    binding_name = manifest.get("metadata", {}).get("name", "unknown")

    if role_ref.get("name") == "cluster-admin":
        violations.append(Violation(
            rule="RBAC_CLUSTER_ADMIN_BINDING",
            severity="HIGH",
            message=f"{kind} '{binding_name}' binds to cluster-admin — grants full control over the entire cluster."
        ))

    return violations


def check_dockerfile(content: str) -> List[Violation]:
    """Run rule checks against a Dockerfile."""
    violations = []
    lines = content.splitlines()

    for i, line in enumerate(lines, start=1):
        stripped = line.strip()

        # Rule: FROM with latest tag
        if stripped.upper().startswith("FROM"):
            parts = stripped.split()
            if len(parts) >= 2:
                image = parts[1]
                if image.endswith(":latest") or (":" not in image and image != "scratch"):
                    violations.append(Violation(
                        rule="LATEST_TAG",
                        severity="HIGH",
                        message=f"FROM uses '{image}' — pin a specific version, not :latest.",
                        line=i
                    ))

        # Rule: ADD used instead of COPY
        if stripped.upper().startswith("ADD "):
            violations.append(Violation(
                rule="ADD_INSTEAD_OF_COPY",
                severity="LOW",
                message="ADD can fetch remote URLs and auto-extract archives — prefer COPY unless you specifically need ADD's behavior.",
                line=i
            ))

    # Rule: no USER directive (running as root)
    has_user = any(l.strip().upper().startswith("USER") for l in lines)
    if not has_user:
        violations.append(Violation(
            rule="NO_USER_DIRECTIVE",
            severity="MEDIUM",
            message="No USER directive found — container will run as root by default."
        ))

    return violations


def run_checks(file_path: str, content: str) -> List[Violation]:
    """Entry point — detects file type and runs appropriate checks."""
    if file_path.endswith("Dockerfile") or "Dockerfile" in file_path:
        return check_dockerfile(content)
    elif file_path.endswith((".yaml", ".yml")):
        return check_kubernetes_manifest(content)
    else:
        return []
