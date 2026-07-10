"""
Tool: get_related_resources
Searches all YAML manifests in a directory for references to a given name/namespace.
Read-only. No writes.
"""

import os
import yaml
from dataclasses import dataclass, field
from typing import List


@dataclass
class RelatedResource:
    path: str
    kind: str
    name: str
    namespace: str


@dataclass
class RelatedResourcesResult:
    query_name: str
    query_namespace: str
    matches: List[RelatedResource] = field(default_factory=list)


def get_related_resources(name: str, namespace: str, search_dir: str = "samples") -> RelatedResourcesResult:
    """
    Grep across all YAML manifests in search_dir for any resource
    that references the given name and namespace.
    """
    result = RelatedResourcesResult(query_name=name, query_namespace=namespace)

    for root, _, files in os.walk(search_dir):
        for filename in files:
            if not filename.endswith((".yaml", ".yml")):
                continue

            file_path = os.path.join(root, filename)
            try:
                with open(file_path, "r") as f:
                    content = f.read()

                # quick text grep before parsing — skip files with no mention
                if name not in content:
                    continue

                manifest = yaml.safe_load(content)
                if not manifest:
                    continue

                resource_name = manifest.get("metadata", {}).get("name", "")
                resource_namespace = manifest.get("metadata", {}).get("namespace", "default")
                kind = manifest.get("kind", "Unknown")

                # match if name appears in resource name or namespace matches
                if name in resource_name or resource_namespace == namespace:
                    result.matches.append(RelatedResource(
                        path=file_path,
                        kind=kind,
                        name=resource_name,
                        namespace=resource_namespace,
                    ))

            except (yaml.YAMLError, OSError):
                continue

    return result
