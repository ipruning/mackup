"""Describe restore changes before Mackup mutates the home directory."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class BinaryFile:
    """Content identity for one side of a binary replacement."""

    size: int
    sha256: str


@dataclass(frozen=True)
class BinaryDifference:
    """Current and backup identities for a binary replacement."""

    current: BinaryFile
    backup: BinaryFile


@dataclass(frozen=True)
class RestoreDetail:
    """One file-system change inside a configured restore target."""

    status: str
    path: str
    diff: str | None = None
    binary: BinaryDifference | None = None
    error: str | None = None


@dataclass(frozen=True)
class RestoreChange:
    """One configured restore target and its pending changes."""

    application: str
    source: str
    destination: str
    status: str
    diff: str | None = None
    binary: BinaryDifference | None = None
    error: str | None = None
    details: tuple[RestoreDetail, ...] = ()


def _binary_file(content: bytes) -> BinaryFile:
    return BinaryFile(size=len(content), sha256=hashlib.sha256(content).hexdigest())


def _source_kind(file_path: str) -> str:
    """Return the kind Mackup copy will materialize from a source path."""
    if os.path.isfile(file_path):
        return "file"
    if os.path.isdir(file_path):
        return "directory"
    return "unsupported"


def _destination_kind(file_path: str) -> str:
    """Return the current kind that restore will replace at a destination."""
    if os.path.islink(file_path):
        return "link"
    return _source_kind(file_path)


def _read_file_diff(
    source: str,
    destination: str,
) -> tuple[str | None, BinaryDifference | None]:
    with open(source, "rb") as source_file:
        source_bytes = source_file.read()
    with open(destination, "rb") as destination_file:
        destination_bytes = destination_file.read()
    if source_bytes == destination_bytes:
        return None, None

    if b"\x00" in source_bytes or b"\x00" in destination_bytes:
        return None, BinaryDifference(
            current=_binary_file(destination_bytes),
            backup=_binary_file(source_bytes),
        )

    try:
        source_text = source_bytes.decode("utf-8").splitlines(keepends=True)
        destination_text = destination_bytes.decode("utf-8").splitlines(
            keepends=True,
        )
    except UnicodeDecodeError:
        return None, BinaryDifference(
            current=_binary_file(destination_bytes),
            backup=_binary_file(source_bytes),
        )

    return (
        "".join(
            difflib.unified_diff(
                destination_text,
                source_text,
                fromfile=f"{destination} (current)",
                tofile=f"{destination} (backup)",
            ),
        ),
        None,
    )


def _compare_directory(source: str, destination: str) -> tuple[RestoreDetail, ...]:
    details: list[RestoreDetail] = []
    names = sorted(set(os.listdir(source)) | set(os.listdir(destination)))
    for name in names:
        source_child = os.path.join(source, name)
        destination_child = os.path.join(destination, name)
        source_exists = os.path.lexists(source_child)
        destination_exists = os.path.lexists(destination_child)
        if not source_exists:
            details.append(RestoreDetail("delete", destination_child))
            continue
        if not destination_exists:
            details.append(RestoreDetail("create", destination_child))
            continue

        source_kind = _source_kind(source_child)
        destination_kind = _destination_kind(destination_child)
        if source_kind != destination_kind:
            details.append(RestoreDetail("type-change", destination_child))
        elif source_kind == "directory":
            details.extend(_compare_directory(source_child, destination_child))
        elif source_kind == "file":
            text_diff, binary = _read_file_diff(source_child, destination_child)
            if text_diff is not None or binary is not None:
                details.append(
                    RestoreDetail("modify", destination_child, text_diff, binary),
                )
    return tuple(details)


def _compare_restore_path(
    application: str,
    source: str,
    destination: str,
) -> RestoreChange:
    """Compare one Mackup source with its home-directory destination."""
    if not os.path.lexists(destination):
        return RestoreChange(application, source, destination, "create")

    source_kind = _source_kind(source)
    destination_kind = _destination_kind(destination)
    if destination_kind == "unsupported":
        return RestoreChange(
            application,
            source,
            destination,
            "blocked",
            error="unsupported destination file type",
        )
    if source_kind != destination_kind:
        return RestoreChange(application, source, destination, "type-change")

    if source_kind == "file":
        text_diff, binary = _read_file_diff(source, destination)
        if text_diff is None and binary is None:
            return RestoreChange(application, source, destination, "unchanged")
        return RestoreChange(
            application,
            source,
            destination,
            "modify",
            text_diff,
            binary,
        )

    details = _compare_directory(source, destination)
    return RestoreChange(
        application,
        source,
        destination,
        "modify" if details else "unchanged",
        details=details,
    )


def compare_restore_path(
    application: str,
    source: str,
    destination: str,
) -> RestoreChange:
    """Compare a restore path, preserving failures as plan blockers."""
    try:
        return _compare_restore_path(application, source, destination)
    except OSError as error:
        message = error.strerror or str(error)
        if error.filename:
            message = f"{message}: {error.filename}"
        return RestoreChange(
            application,
            source,
            destination,
            "blocked",
            error=message,
        )


def restore_plan_summary(changes: list[RestoreChange]) -> dict[str, int]:
    """Count the effective file-system operations in a restore plan."""
    counts: dict[str, int] = {}
    for change in changes:
        effective_changes = change.details or (
            RestoreDetail(change.status, change.destination, change.diff),
        )
        for detail in effective_changes:
            counts[detail.status] = counts.get(detail.status, 0) + 1
    return counts


def restore_plan_has_blockers(changes: list[RestoreChange]) -> bool:
    """Return whether any part of a restore plan could not be inspected."""
    return any(
        change.status == "blocked"
        or any(detail.status == "blocked" for detail in change.details)
        for change in changes
    )


def render_restore_plan(changes: list[RestoreChange]) -> None:
    """Print a stable, human-readable restore plan."""
    visible_changes = [change for change in changes if change.status != "unchanged"]
    for change in visible_changes:
        print(f"{change.status.upper()} {change.destination}")
        if change.diff:
            print(change.diff, end="" if change.diff.endswith("\n") else "\n")
        if change.binary:
            print(
                "  binary: "
                f"current size={change.binary.current.size} "
                f"sha256={change.binary.current.sha256}; "
                f"backup size={change.binary.backup.size} "
                f"sha256={change.binary.backup.sha256}",
            )
        if change.error:
            print(f"  error: {change.error}")
        for detail in change.details:
            print(f"{detail.status.upper()} {detail.path}")
            if detail.diff:
                print(detail.diff, end="" if detail.diff.endswith("\n") else "\n")
            if detail.binary:
                print(
                    "  binary: "
                    f"current size={detail.binary.current.size} "
                    f"sha256={detail.binary.current.sha256}; "
                    f"backup size={detail.binary.backup.size} "
                    f"sha256={detail.binary.backup.sha256}",
                )
            if detail.error:
                print(f"  error: {detail.error}")

    counts = restore_plan_summary(changes)
    summary = ", ".join(
        f"{count} {status}" for status, count in sorted(counts.items()) if count
    )
    print(f"Summary: {summary or 'no managed files'}")


def render_restore_plan_json(changes: list[RestoreChange]) -> None:
    """Print a stable JSON restore plan for automation."""
    document = {
        "operation": "restore",
        "dry_run": True,
        "changes": [asdict(change) for change in changes],
        "summary": restore_plan_summary(changes),
    }
    print(json.dumps(document, indent=2, sort_keys=True))
