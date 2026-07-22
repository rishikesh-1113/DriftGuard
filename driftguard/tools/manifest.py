"""
Tool: get_full_manifest
Returns the full content of a manifest file given its path.
Read-only. No writes.
"""

import os
from dataclasses import dataclass

# Allowed base directory — manifests must live under the workspace root
_WORKSPACE_ROOT = os.path.abspath(os.getenv("WORKSPACE_ROOT", "."))


@dataclass
class ManifestResult:
    path: str
    content: str
    found: bool
    error: str = None


def get_full_manifest(path: str) -> ManifestResult:
    """
    Read and return the full content of a manifest file.
    Accepts .yaml, .yml, or Dockerfile.
    Rejects path traversal attempts (e.g. ../../etc/passwd).
    """
    # Resolve to absolute path and check it stays within workspace root
    abs_path = os.path.realpath(os.path.abspath(path))
    if not abs_path.startswith(_WORKSPACE_ROOT):
        return ManifestResult(path=path, content="", found=False, error="Access denied: path outside workspace")

    if not os.path.exists(abs_path):
        return ManifestResult(path=path, content="", found=False, error=f"File not found: {path}")

    if not (abs_path.endswith((".yaml", ".yml")) or "Dockerfile" in os.path.basename(abs_path)):
        return ManifestResult(path=path, content="", found=False, error=f"Unsupported file type: {path}")

    with open(abs_path, "r") as f:
        content = f.read()

    return ManifestResult(path=path, content=content, found=True)
