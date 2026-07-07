# DriftGuard

An agentic PR reviewer that catches Kubernetes/Docker/Terraform config mistakes before they hit production.

## Architecture

```
collect → recall → (diagnose ⇄ tools) → approval → propose → record
```

## Tech Stack

| Layer | Tool |
|---|---|
| Agent framework | LangGraph |
| LLM | Gemini 2.5 Flash |
| Embeddings | gemini-embedding-001 (3072-dim) |
| GitHub integration | PyGithub + GitHub Actions |
| Memory | Qdrant Cloud |
| Backend | FastAPI |
| Containerization | Docker |
| Orchestration | Kubernetes (k3s on EC2) |

## Project Structure

```
DriftGuard/
├── .github/workflows/       # CI/CD pipelines
├── driftguard/
│   ├── checker/             # Rule-based checks (Phase 1)
│   ├── tools/               # LangGraph tools (Phase 2)
│   ├── agent/               # LangGraph agent (Phase 3)
│   └── api/                 # FastAPI backend (Phase 4)
├── samples/bad-manifests/   # Sample bad manifests for testing
├── tests/                   # Tests
├── main.py                  # CLI entry point
└── requirements.txt
```

## Phase 1 — Rule-Based Checker

Checks Kubernetes manifests and Dockerfiles for:
- `:latest` image tag
- Missing resource requests/limits
- Privileged containers
- Missing liveness/readiness probes
- Hardcoded secrets in env vars
- Missing USER directive in Dockerfile

### Setup

```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

### Run checks

```bash
python main.py
```

### Run tests

```bash
pytest tests/ -v
```
