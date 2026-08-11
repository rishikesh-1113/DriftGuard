# DriftGuard

**An agentic Kubernetes/Docker manifest reviewer that catches misconfigurations before they merge — and learns from every fix a team approves.**

DriftGuard installs as a GitHub App on a repository, watches pull requests for changes to Kubernetes manifests and Dockerfiles, and posts an automated review comment powered by an LLM agent grounded in a deterministic rule engine and a growing memory of past team-approved fixes. Nothing is auto-applied — every suggestion requires a human to comment `/approve` before it's remembered.

---

## Table of Contents

- [Why DriftGuard](#why-driftguard)
- [Architecture Overview](#architecture-overview)
- [End-to-End Flow](#end-to-end-flow)
- [The Agent (LangGraph)](#the-agent-langgraph)
- [Tools Layer](#tools-layer)
- [Rule-Based Checker](#rule-based-checker)
- [Memory / RAG Loop](#memory--rag-loop)
- [GitHub App & Webhook](#github-app--webhook)
- [Deployment](#deployment)
- [Security Design](#security-design)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Setup](#setup)

---

## Why DriftGuard

Static linters catch known patterns but can't reason about context, and plain LLM wrappers hallucinate without a source of truth to check against. DriftGuard combines both:

- A **deterministic rule engine** (pure Python, no LLM) that catches well-known misconfigurations with zero ambiguity — privileged containers, missing resource limits, `:latest` tags, hardcoded secrets, RBAC wildcards, and more.
- An **LLM agent** (Gemini, orchestrated with LangGraph) that reasons about the file, decides when it needs more evidence, cross-checks its own read against the rule engine, and explains *why* something is risky — not just that it is.
- A **memory layer** (Qdrant vector DB) that recalls similar findings a human has already approved in this repo, so the agent's suggestions get more aligned with the team's actual standards over time, instead of repeating generic advice forever.

---

## Architecture Overview

```
┌─────────────┐        ┌──────────────────────────────┐        ┌────────────────────┐
│   GitHub     │◄──────►│         DriftGuard            │◄──────►│   Google Gemini     │
│ (PR diffs,   │        │   (GitHub App on EC2/k3s)      │        │ (LLM inference +    │
│  comments)   │        │                                │        │  embeddings)         │
└─────────────┘        │  FastAPI webhook → LangGraph   │        └────────────────────┘
                        │  agent → rule checker → tools  │
                        └───────────────┬────────────────┘
                                          │
                              ┌───────────┴───────────┐
                              ▼                        ▼
                     ┌─────────────────┐      ┌──────────────────┐
                     │  Qdrant (memory) │      │  Kubernetes       │
                     │  approved fixes  │      │  cluster           │
                     │  as embeddings   │      │  (read-only RBAC) │
                     └─────────────────┘      └──────────────────┘
```

DriftGuard is deployed as a Docker container running in a k3s Pod on a single AWS EC2 instance, exposed via a NodePort Kubernetes Service, and registered as a multi-tenant **GitHub App** so any repository can install it independently.

---

## End-to-End Flow

1. A developer opens or updates a PR touching a `.yaml`/`.yml`/`Dockerfile`.
2. GitHub sends a signed `pull_request` webhook to DriftGuard's FastAPI server.
3. The signature is verified (HMAC-SHA256); the request is queued as a background task and the HTTP response returns immediately.
4. DriftGuard exchanges a short-lived, self-signed JWT for an installation-scoped GitHub access token (per-repo, per-installation — no static personal token involved).
5. Changed manifest/Dockerfile files are fetched via the GitHub API.
6. **For each changed file independently**, the LangGraph agent is invoked — one full run of the graph per file, with no shared context between files in the same PR.
7. Findings from all files are combined into a single PR comment and posted, along with an instruction to comment `/approve`.
8. When a repo member comments `/approve`, a second webhook fires; after a permission check, the pending findings are embedded and written to Qdrant as approved knowledge.
9. Future reviews in that repo recall similar approved findings and use them as grounding context — the agent's suggestions get sharper over time without any model fine-tuning.

---

## The Agent (LangGraph)

DriftGuard's core is a bounded state machine, not a single prompt call:

```
collect → recall → diagnose ⇄ tools → propose → record
```

| Node | Responsibility |
|---|---|
| `collect` | Initializes the shared `AgentState` with defaults |
| `recall` | Embeds the file and queries Qdrant for similar, previously-approved findings in this repo |
| `diagnose` | Gemini reasons over the file, diff, and recalled context; either calls a tool or emits final structured findings |
| `tools` | Executes whichever tool the LLM requested; result is appended to the conversation and control returns to `diagnose` |
| `propose` | Formats findings into a Markdown PR comment |
| `record` | Filters findings by confidence (≥ 0.85) and stages them as pending — **never writes to memory directly** |

The `diagnose ⇄ tools` loop is capped at 5 iterations to guarantee termination. The LLM runs at `temperature=0` for consistent, repeatable judgments. All LLM output is parsed defensively — a malformed response degrades to an empty finding list rather than crashing the review.

**Design principle:** the agent's own confidence never triggers a memory write. Only an explicit human `/approve` does — the model cannot reinforce its own judgment unsupervised.

---

## Tools Layer

Four read-only tools the agent can call mid-reasoning, each a thin wrapper around a plain Python function:

| Tool | Purpose |
|---|---|
| `get_full_manifest` | Reads another file's content — path-traversal guarded, restricted to the workspace root, manifest/Dockerfile only |
| `check_policy_rules` | Runs the deterministic rule engine as ground truth the LLM can cross-check against |
| `get_related_resources` | Searches other manifests in the repo for matching resource names/namespaces |
| `get_workload_history` | Returns past incidents for one workload; the target repo is baked in via closure so the LLM can never redirect the search to another repo's memory |

Every tool returns a structured result object (found/error) and never raises — failures degrade gracefully instead of aborting the review.

---

## Rule-Based Checker

A pure-Python, no-LLM policy engine that parses manifests with `yaml.safe_load` and flags well-defined violations, including:

- Privileged containers, `hostNetwork`/`hostPID`/`hostIPC`, `hostPath` volumes
- Missing `allowPrivilegeEscalation: false`, missing `readOnlyRootFilesystem`, capabilities not dropped
- Missing liveness/readiness probes
- `:latest` image tags, missing resource requests/limits
- Hardcoded secrets in environment variables
- RBAC wildcards and bindings to `cluster-admin`
- Dockerfiles running as root (no `USER` directive)

This engine is the deterministic backbone the LLM agent checks its own reasoning against — it's also runnable standalone via a CLI entry point independent of the agent.

---

## Memory / RAG Loop

- Findings are embedded with Gemini's `gemini-embedding-001` model (3072-dim vectors) and stored in **Qdrant**, tagged by `repo_name` so one repo's history never leaks into another's context.
- **Write path:** only triggered by a human commenting `/approve` on a PR — never automatically.
- **Read path:** the `recall` node searches for the top 3 matches above a 0.80 similarity threshold, scoped to the current repo, and feeds them into the LLM's prompt as grounding context.
- This is retrieval-augmented generation applied to code review: the agent isn't fine-tuned, but its context window is enriched with the team's own accumulated, human-verified decisions.

---

## GitHub App & Webhook

DriftGuard runs as a registered **GitHub App**, not a bot using a personal access token — this is what makes it installable on any repository independently.

- **Authentication** is a two-step trust chain: a short-lived (≤10 min) JWT signed with the app's private key (RS256, asymmetric) proves the app's identity to GitHub; that JWT is exchanged for an **installation access token** scoped to one specific repo installation. Installation tokens are cached in memory (~55 min) to avoid re-authenticating on every request.
- **Webhook delivery** is verified with HMAC-SHA256 signature checking (constant-time comparison) before any payload is trusted.
- **Approval authorization** is a separate, second gate: only commenters with `OWNER`, `MEMBER`, or `COLLABORATOR` association on the repo can trigger a memory write via `/approve`.
- Review work runs as a FastAPI `BackgroundTask` so GitHub's webhook delivery isn't held open waiting on an LLM call.

---

## Deployment

DriftGuard is containerized and deployed as real Kubernetes workloads on a single AWS EC2 instance running **k3s** (lightweight Kubernetes, chosen for its small footprint on a resource-constrained box).

- **Docker:** multi-stage build (dependency install isolated from the runtime image), runs as a dedicated non-root user (UID 1001), with a container-level `HEALTHCHECK`.
- **No image registry:** the image is built locally and imported directly into k3s's containerd store (`docker save | k3s ctr images import -`) — `imagePullPolicy: IfNotPresent` ensures k3s never attempts a network pull.
- **Kubernetes manifests:**
  - A dedicated `driftguard` namespace
  - A `ServiceAccount` bound to a **read-only** `ClusterRole` (`get`/`list`/`watch` only — no write verbs, provable via `kubectl auth can-i`)
  - A `Deployment` with resource requests/limits, liveness and readiness probes on `/health`, and a hardened `securityContext` (non-root, no privilege escalation)
  - A `NodePort` `Service` exposing the app on the EC2 host's public IP so GitHub's webhook can reach it directly
- **EC2 setup:** a 2GB swap file compensates for the instance's limited RAM during build/runtime.

---

## Security Design

Security is organized around three trust boundaries:

1. **GitHub → DriftGuard** — HMAC-verified webhooks, a separate author-association check before any approval is honored, path-traversal-guarded file reads, and prompt sanitization on all PR-derived text before it reaches the LLM.
2. **DriftGuard → Gemini** — LLM output is never blindly trusted: JSON parsing is defensive with safe fallbacks, and — critically — the model's own confidence can never write to memory without human approval.
3. **DriftGuard → Kubernetes** — a dedicated ServiceAccount with a read-only ClusterRole; the agent can observe the cluster but never modify it.

Secrets (`GITHUB_APP_PRIVATE_KEY`, `GOOGLE_API_KEY`, `QDRANT_API_KEY`, `GITHUB_WEBHOOK_SECRET`) are supplied via environment variables or Kubernetes Secrets — never hardcoded, never committed.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Agent orchestration | LangGraph, LangChain |
| LLM | Google Gemini (chat + embeddings) |
| Vector memory | Qdrant |
| API server | FastAPI, Uvicorn |
| GitHub integration | GitHub App, PyGithub, PyJWT |
| Containerization | Docker (multi-stage build) |
| Orchestration | Kubernetes (k3s) |
| Infrastructure | AWS EC2 |

---

## Project Structure

```
driftguard/
├── agent/
│   ├── state.py        # AgentState TypedDict — the shared data flowing through the graph
│   ├── graph.py         # Node/edge wiring, the bounded ReAct loop
│   └── nodes.py         # Node implementations, tool bindings, system prompt, sanitization
├── tools/
│   ├── manifest.py       # Read a file (path-traversal guarded)
│   ├── policy.py          # Wraps the rule checker for the agent
│   ├── search.py           # Find related resources across manifests
│   └── history.py          # Recall past incidents for a workload
├── checker/
│   └── rules.py             # Deterministic, no-LLM policy engine
├── memory/
│   ├── store.py               # Embed + write approved findings to Qdrant
│   └── recall.py                # Embed + query similar past findings
├── api/
│   ├── github_app.py            # JWT → installation token trust chain
│   ├── github.py                  # GitHub API helpers (PyGithub + raw requests)
│   └── webhook.py                  # FastAPI app, signature verification, background tasks
├── Dockerfile
├── k8s/
│   ├── namespace.yaml
│   ├── rbac.yaml
│   ├── deployment.yaml
│   ├── service.yaml
│   └── secrets.yaml
├── scripts/
│   └── deploy-ec2.sh                 # Swap → Docker → k3s → build → import → apply
└── SECURITY.md
```

---

## Setup

1. Register a GitHub App, generate a private key, and note the App ID.
2. Configure environment variables (see `.env.example`): `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET`, `GOOGLE_API_KEY`, `QDRANT_URL`, `QDRANT_API_KEY`.
3. Build and deploy:
   ```bash
   docker build -t driftguard:latest .
   docker save driftguard:latest | sudo k3s ctr images import -
   kubectl apply -f k8s/namespace.yaml
   kubectl apply -f k8s/rbac.yaml
   kubectl apply -f k8s/deployment.yaml
   kubectl apply -f k8s/service.yaml
   ```
4. Point the GitHub App's webhook URL at `http://<host>:30080/webhook`.
5. Install the App on a repository and open a PR touching a manifest or Dockerfile.