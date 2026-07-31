"""Repository paths and naming conventions for generated artifacts."""

from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CACHE_ROOT = REPOSITORY_ROOT / ".cache" / "twin_lab"
EXPORT_ROOT = REPOSITORY_ROOT / "exports"


def resolve_repo_path(value: str | Path, *, relative_to: Path | None = None) -> Path:
    """Resolve an input path from the current directory, review directory, or repository root."""

    path = Path(value)
    if path.is_absolute():
        return path
    candidates = [Path.cwd() / path]
    if relative_to is not None:
        candidates.append(relative_to / path)
    candidates.append(REPOSITORY_ROOT / path)
    return next((candidate.resolve() for candidate in candidates if candidate.exists()), path)


def review_artifact_stem(review_path: str | Path) -> str:
    """Return a project-qualified stable name for cache and export directories."""

    path = Path(review_path)
    name = path.name.removesuffix(".inventory.yaml").removesuffix(".kinematics.yaml")
    if path.parent.name == "reviews":
        return f"{path.parent.parent.name}.{name}"
    return name
