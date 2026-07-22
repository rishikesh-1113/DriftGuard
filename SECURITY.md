# DriftGuard — Security Design

## Trust Boundaries

DriftGuard operates across three boundaries:
1. GitHub (reads PR diffs, writes PR comments)
2. Google Gemini API (LLM inference + embeddings)
3. Kubernetes cluster (read-only drift checking)

Every boundary follows the same principle: **minimum required permissions, provably enforced.**

---

## GitHub Token Scopes

DriftGuard requires a GitHub token with only these scopes:

| Scope | Why needed |
|---|---|
| `repo:read` | Read PR diffs and file contents |
| `pull_requests:write` | Post review comments on PRs |

**What it does NOT have:**
- No `admin` scope
- No `delete` permissions
- No ability to merge, close, or modify PRs
- No access to secrets or Actions

The token is stored in an environment variable, never hardcoded.

---

## Webhook Signature Verification

Every incoming webhook from GitHub is verified using HMAC-SHA256:

```python
expected = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
hmac.compare_digest(expected, signature)
```

This prevents anyone from sending fake webhook payloads to trigger reviews.
Set `GITHUB_WEBHOOK_SECRET` in your `.env` to enable this.

---

## Read-Only Tools

Every tool in `driftguard/tools/` is read-only by design:

| Tool | Can write? |
|---|---|
| `get_full_manifest` | No — reads files only |
| `get_related_resources` | No — searches files only |
| `check_policy_rules` | No — runs checks only |
| `get_workload_history` | No — queries memory only |

No tool can write to a cluster, repo, or database.
The agent can only **observe** — never **act**.

---

## Kubernetes RBAC

When deployed on a cluster, DriftGuard uses a dedicated ServiceAccount
with a ClusterRole that allows only `get`, `list`, `watch`:

```bash
# Verify DriftGuard cannot write to the cluster
kubectl auth can-i create deployments --as=system:serviceaccount:driftguard:driftguard
# no

kubectl auth can-i delete pods --as=system:serviceaccount:driftguard:driftguard
# no

kubectl auth can-i get deployments --as=system:serviceaccount:driftguard:driftguard
# yes
```

See `k8s/rbac.yaml` for the full RBAC definition.

---

## Human Approval Gate

DriftGuard never auto-applies fixes. Every suggestion requires a human to
comment `/approve` on the PR before any action is taken.

This is a deliberate design decision — the agent reasons and suggests,
humans decide and act.

---

## Secrets Management

| Secret | Where stored |
|---|---|
| `GITHUB_TOKEN` | Environment variable / GitHub Actions secret |
| `GOOGLE_API_KEY` | Environment variable / GitHub Actions secret |
| `QDRANT_API_KEY` | Environment variable / GitHub Actions secret |
| `GITHUB_WEBHOOK_SECRET` | Environment variable / GitHub Actions secret |

Never hardcoded. Never committed to version control.
`.env` is in `.gitignore`.
