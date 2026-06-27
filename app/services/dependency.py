"""Dependency check: flag required deps that are missing, and incompatibilities.

Operates on the resolved ``ModMatch`` list. Each ``latest`` version carries a
``dependencies`` list (Modrinth/CurseForge normalized to
``{project_id, dependency_type}``). We compare required/incompatible deps against
the set of project ids actually installed.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models import ModMatch


@dataclass
class DependencyIssue:
    match: ModMatch
    kind: str            # "missing_required" | "incompatible"
    dep_project_id: str
    detail: str


def check_dependencies(matches: list[ModMatch]) -> list[DependencyIssue]:
    installed_projects = {m.project_id for m in matches if m.project_id}
    # Map project id -> display name for nicer messages.
    name_by_id = {m.project_id: m.display_name for m in matches if m.project_id}

    issues: list[DependencyIssue] = []
    for m in matches:
        if not m.latest:
            continue
        for dep in m.latest.dependencies:
            dep_id = dep.get("project_id")
            dtype = dep.get("dependency_type")
            if not dep_id:
                continue
            if dtype == "required" and dep_id not in installed_projects:
                issues.append(
                    DependencyIssue(
                        m, "missing_required", dep_id,
                        f"{m.display_name} requires {dep_id}, which is not installed",
                    )
                )
            elif dtype == "incompatible" and dep_id in installed_projects:
                issues.append(
                    DependencyIssue(
                        m, "incompatible", dep_id,
                        f"{m.display_name} is incompatible with "
                        f"{name_by_id.get(dep_id, dep_id)}",
                    )
                )
    return issues
