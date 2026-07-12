"""Report differences between Mackup reference data and live files."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class Drift:
    """One observable difference between a reference path and a live path."""

    application: str
    reference_path: str
    live_path: str
    kind: str
    reference_kind: str | None
    live_kind: str | None
    error: str | None = None


def _path_kind(file_path: Path) -> str | None:
    if file_path.is_symlink():
        return "link"
    if file_path.is_file():
        return "file"
    if file_path.is_dir():
        return "directory"
    if file_path.exists():
        return "unsupported"
    return None


def _difference(
    application: str,
    reference: Path,
    live: Path,
    kind: str,
    path_kinds: tuple[str | None, str | None],
) -> list[Drift]:
    return [
        Drift(
            application,
            str(reference),
            str(live),
            kind,
            path_kinds[0],
            path_kinds[1],
        ),
    ]


def _compare_files(application: str, reference: Path, live: Path) -> list[Drift]:
    if reference.read_bytes() == live.read_bytes():
        return []
    return _difference(application, reference, live, "modified", ("file", "file"))


def _compare_directories(
    application: str,
    reference: Path,
    live: Path,
) -> list[Drift]:
    changes: list[Drift] = []
    names = sorted(
        {child.name for child in reference.iterdir()}
        | {child.name for child in live.iterdir()},
    )
    for name in names:
        changes.extend(compare_paths(application, reference / name, live / name))
    return changes


def _compare_links(application: str, reference: Path, live: Path) -> list[Drift]:
    if reference.readlink() == live.readlink():
        return []
    return _difference(application, reference, live, "modified", ("link", "link"))


def _compare_paths(application: str, reference: Path, live: Path) -> list[Drift]:
    """Compare one configured reference path with its live counterpart."""
    reference_kind = _path_kind(reference)
    live_kind = _path_kind(live)
    if reference_kind is None and live_kind is None:
        return []
    if reference_kind is None:
        kind = "only-live"
    elif live_kind is None:
        kind = "only-reference"
    elif reference_kind != live_kind:
        kind = "type-changed"
    else:
        kind = ""
    if kind:
        return _difference(
            application,
            reference,
            live,
            kind,
            (reference_kind, live_kind),
        )
    if reference_kind == "file" and live_kind == "file":
        return _compare_files(application, reference, live)
    if reference_kind == "directory" and live_kind == "directory":
        return _compare_directories(application, reference, live)
    if reference_kind == "link" and live_kind == "link":
        return _compare_links(application, reference, live)
    return []


def compare_paths(application: str, reference: Path, live: Path) -> list[Drift]:
    """Compare paths while preserving inspection failures in the report."""
    try:
        return _compare_paths(application, reference, live)
    except OSError as error:
        message = error.strerror or str(error)
        if error.filename:
            message = f"{message}: {error.filename}"
        return [
            Drift(
                application,
                str(reference),
                str(live),
                "unreadable",
                _path_kind(reference),
                _path_kind(live),
                message,
            ),
        ]


def render_drift_json(changes: list[Drift]) -> None:
    """Render a stable machine-readable drift report."""
    summary = dict(sorted(Counter(change.kind for change in changes).items()))
    document = {
        "schema_version": 1,
        "operation": "diff",
        "changes": [asdict(change) for change in changes],
        "summary": summary,
    }
    print(json.dumps(document, indent=2, sort_keys=True))


def render_drift(changes: list[Drift]) -> None:
    """Render location-only drift for a person."""
    for change in changes:
        print(f"{change.kind.upper()} {change.live_path}")
        print(f"  reference: {change.reference_path}")
        if change.error:
            print(f"  error: {change.error}")
    summary = Counter(change.kind for change in changes)
    rendered = ", ".join(f"{count} {kind}" for kind, count in sorted(summary.items()))
    print(f"Summary: {rendered or 'no drift'}")


def drift_has_errors(changes: list[Drift]) -> bool:
    """Return whether the inspection was incomplete."""
    return any(change.kind == "unreadable" for change in changes)
