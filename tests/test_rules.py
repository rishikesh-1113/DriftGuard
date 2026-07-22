"""
Tests for Phase 1 rule-based checker.
Each test verifies a specific rule fires (or doesn't) correctly.
"""

import pytest
from driftguard.checker.rules import check_kubernetes_manifest, check_dockerfile


CLEAN_DEPLOYMENT = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: good-app
spec:
  replicas: 1
  selector:
    matchLabels:
      app: good-app
  template:
    metadata:
      labels:
        app: good-app
    spec:
      containers:
        - name: good-app
          image: nginx:1.25.0
          resources:
            requests:
              cpu: "100m"
              memory: "128Mi"
            limits:
              cpu: "200m"
              memory: "256Mi"
          livenessProbe:
            httpGet:
              path: /healthz
              port: 8080
          readinessProbe:
            httpGet:
              path: /ready
              port: 8080
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop:
                - ALL
"""

BAD_DEPLOYMENT = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: bad-app
spec:
  replicas: 1
  selector:
    matchLabels:
      app: bad-app
  template:
    metadata:
      labels:
        app: bad-app
    spec:
      containers:
        - name: bad-app
          image: nginx:latest
          securityContext:
            privileged: true
          env:
            - name: DB_PASSWORD
              value: "supersecret"
"""


def get_rules(violations):
    return [v.rule for v in violations]


# --- Kubernetes tests ---

def test_latest_tag_flagged():
    violations = check_kubernetes_manifest(BAD_DEPLOYMENT)
    assert "LATEST_TAG" in get_rules(violations)


def test_no_resource_limits_flagged():
    violations = check_kubernetes_manifest(BAD_DEPLOYMENT)
    assert "NO_RESOURCE_LIMITS" in get_rules(violations)


def test_privileged_container_flagged():
    violations = check_kubernetes_manifest(BAD_DEPLOYMENT)
    assert "PRIVILEGED_CONTAINER" in get_rules(violations)


def test_no_liveness_probe_flagged():
    violations = check_kubernetes_manifest(BAD_DEPLOYMENT)
    assert "NO_LIVENESS_PROBE" in get_rules(violations)


def test_no_readiness_probe_flagged():
    violations = check_kubernetes_manifest(BAD_DEPLOYMENT)
    assert "NO_READINESS_PROBE" in get_rules(violations)


def test_hardcoded_secret_flagged():
    violations = check_kubernetes_manifest(BAD_DEPLOYMENT)
    assert "HARDCODED_SECRET" in get_rules(violations)


def test_clean_manifest_no_violations():
    violations = check_kubernetes_manifest(CLEAN_DEPLOYMENT)
    assert violations == [], f"Expected no violations but got: {violations}"


# --- Dockerfile tests ---

def test_dockerfile_latest_tag():
    content = "FROM python:latest\nCMD ['python', 'app.py']"
    violations = check_dockerfile(content)
    assert "LATEST_TAG" in get_rules(violations)


def test_dockerfile_no_user():
    content = "FROM python:3.11\nCMD ['python', 'app.py']"
    violations = check_dockerfile(content)
    assert "NO_USER_DIRECTIVE" in get_rules(violations)


def test_dockerfile_clean():
    content = "FROM python:3.11\nUSER appuser\nCMD ['python', 'app.py']"
    violations = check_dockerfile(content)
    assert violations == [], f"Expected no violations but got: {violations}"


# --- new security rule tests ---

HOST_NAMESPACE_DEPLOYMENT = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: risky-app
spec:
  replicas: 1
  selector:
    matchLabels:
      app: risky-app
  template:
    metadata:
      labels:
        app: risky-app
    spec:
      hostNetwork: true
      hostPID: true
      hostIPC: true
      volumes:
        - name: host-vol
          hostPath:
            path: /etc
      containers:
        - name: risky-app
          image: nginx:1.25.0
"""

WILDCARD_ROLE = """
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: too-broad
rules:
  - apiGroups: ["*"]
    resources: ["*"]
    verbs: ["*"]
"""

CLUSTER_ADMIN_BINDING = """
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: dangerous-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
  - kind: ServiceAccount
    name: some-app
    namespace: default
"""

SAFE_ROLE = """
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: driftguard-readonly
rules:
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "list", "watch"]
"""


def test_host_network_flagged():
    violations = get_rules(check_kubernetes_manifest(HOST_NAMESPACE_DEPLOYMENT))
    assert "HOST_NETWORK" in violations


def test_host_pid_flagged():
    violations = get_rules(check_kubernetes_manifest(HOST_NAMESPACE_DEPLOYMENT))
    assert "HOST_PID" in violations


def test_host_ipc_flagged():
    violations = get_rules(check_kubernetes_manifest(HOST_NAMESPACE_DEPLOYMENT))
    assert "HOST_IPC" in violations


def test_host_path_volume_flagged():
    violations = get_rules(check_kubernetes_manifest(HOST_NAMESPACE_DEPLOYMENT))
    assert "HOST_PATH_VOLUME" in violations


def test_privilege_escalation_flagged_when_unset():
    violations = get_rules(check_kubernetes_manifest(BAD_DEPLOYMENT))
    assert "PRIVILEGE_ESCALATION_ALLOWED" in violations


def test_capabilities_not_dropped_flagged():
    violations = get_rules(check_kubernetes_manifest(BAD_DEPLOYMENT))
    assert "CAPABILITIES_NOT_DROPPED" in violations


def test_rbac_wildcard_flagged():
    violations = get_rules(check_kubernetes_manifest(WILDCARD_ROLE))
    assert "RBAC_WILDCARD" in violations


def test_rbac_cluster_admin_binding_flagged():
    violations = get_rules(check_kubernetes_manifest(CLUSTER_ADMIN_BINDING))
    assert "RBAC_CLUSTER_ADMIN_BINDING" in violations


def test_rbac_safe_role_no_violations():
    violations = check_kubernetes_manifest(SAFE_ROLE)
    assert violations == [], f"Expected no violations but got: {violations}"
