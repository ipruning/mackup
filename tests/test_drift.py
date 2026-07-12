import json
from pathlib import Path

from mackup.drift import compare_paths, render_drift_json


def test_compare_paths_reports_modified_file_without_content(
    tmp_path: Path,
    capsys,
) -> None:
    reference = tmp_path / "reference.toml"
    live = tmp_path / "live.toml"
    reference.write_text("token=reference-secret\n")
    live.write_text("token=live-secret\n")

    changes = compare_paths("example", reference, live)
    render_drift_json(changes)

    document = json.loads(capsys.readouterr().out)
    assert document == {
        "changes": [
            {
                "application": "example",
                "error": None,
                "kind": "modified",
                "live_kind": "file",
                "live_path": str(live),
                "reference_kind": "file",
                "reference_path": str(reference),
            },
        ],
        "operation": "diff",
        "schema_version": 1,
        "summary": {"modified": 1},
    }
    output = json.dumps(document)
    assert "reference-secret" not in output
    assert "live-secret" not in output


def test_compare_paths_reports_presence_and_type_transitions(tmp_path: Path) -> None:
    reference = tmp_path / "reference"
    live = tmp_path / "live"

    reference.write_text("reference\n")
    assert [change.kind for change in compare_paths("example", reference, live)] == [
        "only-reference",
    ]

    reference.unlink()
    live.write_text("live\n")
    assert [change.kind for change in compare_paths("example", reference, live)] == [
        "only-live",
    ]

    reference.mkdir()
    assert [change.kind for change in compare_paths("example", reference, live)] == [
        "type-changed",
    ]


def test_compare_paths_reports_nested_directory_drift(tmp_path: Path) -> None:
    reference = tmp_path / "reference"
    live = tmp_path / "live"
    reference.mkdir()
    live.mkdir()
    (reference / "same.txt").write_text("same\n")
    (live / "same.txt").write_text("same\n")
    (reference / "changed.txt").write_text("reference\n")
    (live / "changed.txt").write_text("live\n")
    (reference / "reference-only.txt").write_text("reference\n")
    (live / "live-only.txt").write_text("live\n")

    changes = compare_paths("example", reference, live)

    assert [(Path(change.live_path).name, change.kind) for change in changes] == [
        ("changed.txt", "modified"),
        ("live-only.txt", "only-live"),
        ("reference-only.txt", "only-reference"),
    ]


def test_compare_paths_preserves_read_failures_as_unreadable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    reference = tmp_path / "reference"
    live = tmp_path / "live"
    reference.write_text("reference\n")
    live.write_text("live\n")
    original_read_bytes = Path.read_bytes

    def fail_for_live(file_path: Path) -> bytes:
        if file_path == live:
            raise PermissionError(13, "Permission denied", str(file_path))
        return original_read_bytes(file_path)

    monkeypatch.setattr(Path, "read_bytes", fail_for_live)

    changes = compare_paths("example", reference, live)

    assert len(changes) == 1
    assert changes[0].kind == "unreadable"
    assert changes[0].error == f"Permission denied: {live}"


def test_compare_paths_compares_symbolic_link_targets(tmp_path: Path) -> None:
    reference = tmp_path / "reference"
    live = tmp_path / "live"
    reference.symlink_to("reference-target")
    live.symlink_to("live-target")

    changes = compare_paths("example", reference, live)

    assert len(changes) == 1
    assert changes[0].kind == "modified"
    assert changes[0].reference_kind == "link"
    assert changes[0].live_kind == "link"
