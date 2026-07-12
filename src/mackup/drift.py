"""Report differences between Mackup reference data and live files."""

from __future__ import annotations

import json
import stat
from collections import Counter
from dataclasses import asdict, dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class DriftKind(str, Enum):
    MODIFIED = "modified"
    ONLY_REFERENCE = "only-reference"
    ONLY_LIVE = "only-live"
    TYPE_CHANGED = "type-changed"
    UNREADABLE = "unreadable"


class FileKind(str, Enum):
    FILE = "file"
    DIRECTORY = "directory"
    LINK = "link"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class Drift:
    """One observable difference between a reference path and a live path."""

    application: str
    reference_path: str
    live_path: str
    kind: DriftKind
    reference_kind: FileKind | None
    live_kind: FileKind | None
    error: str | None = None


def _path_kind(file_path: Path) -> FileKind | None:
    try:
        mode = file_path.lstat().st_mode
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(mode):
        return FileKind.LINK
    if stat.S_ISREG(mode):
        return FileKind.FILE
    if stat.S_ISDIR(mode):
        return FileKind.DIRECTORY
    return FileKind.UNSUPPORTED


def _safe_path_kind(file_path: Path) -> FileKind | None:
    try:
        return _path_kind(file_path)
    except OSError:
        return None


def _drift(
    application: str,
    reference: Path,
    live: Path,
    kind: DriftKind,
    path_kinds: tuple[FileKind | None, FileKind | None],
) -> Drift:
    return Drift(
        application,
        str(reference),
        str(live),
        kind,
        path_kinds[0],
        path_kinds[1],
    )


def _compare_files(application: str, reference: Path, live: Path) -> list[Drift]:
    if reference.read_bytes() == live.read_bytes():
        return []
    return [
        _drift(
            application,
            reference,
            live,
            DriftKind.MODIFIED,
            (FileKind.FILE, FileKind.FILE),
        ),
    ]


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
    return [
        _drift(
            application,
            reference,
            live,
            DriftKind.MODIFIED,
            (FileKind.LINK, FileKind.LINK),
        ),
    ]


def _compare_paths(application: str, reference: Path, live: Path) -> list[Drift]:
    """Compare one configured reference path with its live counterpart."""
    reference_kind = _path_kind(reference)
    live_kind = _path_kind(live)
    if reference_kind is None and live_kind is None:
        return []
    if reference_kind is None:
        kind = DriftKind.ONLY_LIVE
    elif live_kind is None:
        kind = DriftKind.ONLY_REFERENCE
    elif reference_kind != live_kind:
        kind = DriftKind.TYPE_CHANGED
    else:
        kind = None
    if kind:
        return [
            _drift(
                application,
                reference,
                live,
                kind,
                (reference_kind, live_kind),
            ),
        ]
    if reference_kind is FileKind.FILE and live_kind is FileKind.FILE:
        return _compare_files(application, reference, live)
    if reference_kind is FileKind.DIRECTORY and live_kind is FileKind.DIRECTORY:
        return _compare_directories(application, reference, live)
    if reference_kind is FileKind.LINK and live_kind is FileKind.LINK:
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
                DriftKind.UNREADABLE,
                _safe_path_kind(reference),
                _safe_path_kind(live),
                message,
            ),
        ]


def render_drift_json(changes: list[Drift]) -> None:
    """Render a stable machine-readable drift report."""
    summary = dict(
        sorted(Counter(change.kind.value for change in changes).items()),
    )
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
        print(f"{change.kind.value.upper()} {change.live_path}")
        print(f"  reference: {change.reference_path}")
        if change.error:
            print(f"  error: {change.error}")
    summary = Counter(change.kind.value for change in changes)
    rendered = ", ".join(f"{count} {kind}" for kind, count in sorted(summary.items()))
    print(f"Summary: {rendered or 'no drift'}")


def drift_has_errors(changes: list[Drift]) -> bool:
    """Return whether the inspection was incomplete."""
    return any(change.kind is DriftKind.UNREADABLE for change in changes)
