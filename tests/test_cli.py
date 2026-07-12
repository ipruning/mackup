import contextlib
import io
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from mackup.main import USAGE_ERROR, main


def _fixture(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path]:
    home = tmp_path / "home"
    storage = tmp_path / "storage"
    reference = storage / "reference"
    applications = tmp_path / "applications"
    home.mkdir()
    reference.mkdir(parents=True)
    applications.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    config_path = home / ".mackup.cfg"
    config_path.write_text(
        "[storage]\n"
        "engine = file_system\n"
        f"path = {storage}\n"
        "directory = reference\n",
    )
    (applications / "test-app.cfg").write_text(
        "[application]\nname = test-app\n[configuration_files]\n.testrc\n",
    )
    return home, reference, applications


def test_diff_reports_location_only_json_without_mutating_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home, reference, applications = _fixture(tmp_path, monkeypatch)
    live_file = home / ".testrc"
    reference_file = reference / ".testrc"
    live_file.write_text("token=live-secret\n")
    reference_file.write_text("token=reference-secret\n")
    output = io.StringIO()
    argv = [
        "mackup",
        "--config-file",
        str(home / ".mackup.cfg"),
        "--applications-dir",
        str(applications),
        "--json",
        "diff",
    ]

    with (
        patch("sys.argv", argv),
        patch("mackup.mackup.os.geteuid", return_value=0),
        contextlib.redirect_stdout(output),
    ):
        main()

    document = json.loads(output.getvalue())
    assert document["schema_version"] == 1
    assert document["operation"] == "diff"
    test_app_changes = [
        change for change in document["changes"] if change["application"] == "test-app"
    ]
    assert [change["kind"] for change in test_app_changes] == ["modified"]
    assert "live-secret" not in output.getvalue()
    assert "reference-secret" not in output.getvalue()
    assert live_file.read_text() == "token=live-secret\n"
    assert reference_file.read_text() == "token=reference-secret\n"


@pytest.mark.parametrize(
    "command",
    [
        ["backup"],
        ["restore"],
        ["link"],
        ["link", "install"],
        ["link", "uninstall"],
    ],
)
def test_mutation_is_not_a_public_command(
    monkeypatch,
    command: list[str],
) -> None:
    monkeypatch.setenv("HOME", os.fspath(Path.home()))
    with (
        patch("sys.argv", ["mackup", *command]),
        pytest.raises(SystemExit) as context,
    ):
        main()
    assert context.value.code == USAGE_ERROR


def test_json_requires_diff(monkeypatch) -> None:
    monkeypatch.setenv("HOME", os.fspath(Path.home()))
    with (
        patch("sys.argv", ["mackup", "--json", "list"]),
        pytest.raises(SystemExit) as context,
    ):
        main()
    assert context.value.code == USAGE_ERROR


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (["list"], "test-app"),
        (["show", "test-app"], "Name: test-app"),
    ],
)
def test_metadata_inspection_commands_run_as_root(
    tmp_path: Path,
    monkeypatch,
    capsys,
    command: list[str],
    expected: str,
) -> None:
    home, _reference, applications = _fixture(tmp_path, monkeypatch)
    argv = [
        "mackup",
        "--config-file",
        str(home / ".mackup.cfg"),
        "--applications-dir",
        str(applications),
        *command,
    ]

    with patch("sys.argv", argv), patch("mackup.mackup.os.geteuid", return_value=0):
        main()

    assert expected in capsys.readouterr().out


def test_unknown_application_is_a_usage_error(tmp_path: Path, monkeypatch) -> None:
    home, _reference, applications = _fixture(tmp_path, monkeypatch)
    argv = [
        "mackup",
        "--config-file",
        str(home / ".mackup.cfg"),
        "--applications-dir",
        str(applications),
        "diff",
        "unknown",
    ]
    with patch("sys.argv", argv), pytest.raises(SystemExit) as context:
        main()
    assert context.value.code == USAGE_ERROR


def test_explicit_applications_directory_must_exist(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    home, _reference, applications = _fixture(tmp_path, monkeypatch)
    applications.joinpath("test-app.cfg").unlink()
    applications.rmdir()
    argv = [
        "mackup",
        "--config-file",
        str(home / ".mackup.cfg"),
        "--applications-dir",
        str(applications),
        "diff",
    ]

    with patch("sys.argv", argv), pytest.raises(SystemExit) as context:
        main()

    assert context.value.code == USAGE_ERROR
    assert capsys.readouterr().err == (
        f"Applications directory is not a directory: {applications}\n"
    )


def test_unreadable_path_is_json_error_and_exit_one(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home, reference, applications = _fixture(tmp_path, monkeypatch)
    live_file = home / ".testrc"
    reference_file = reference / ".testrc"
    live_file.write_text("live\n")
    reference_file.write_text("reference\n")
    original_lstat = Path.lstat

    def deny_live(file_path: Path) -> os.stat_result:
        if file_path == live_file:
            raise PermissionError(13, "Permission denied", str(file_path))
        return original_lstat(file_path)

    output = io.StringIO()
    argv = [
        "mackup",
        "--config-file",
        str(home / ".mackup.cfg"),
        "--applications-dir",
        str(applications),
        "--json",
        "diff",
    ]
    with (
        patch("sys.argv", argv),
        patch.object(Path, "lstat", deny_live),
        contextlib.redirect_stdout(output),
        pytest.raises(SystemExit) as context,
    ):
        main()

    document = json.loads(output.getvalue())
    assert context.value.code == 1
    test_app_changes = [
        change for change in document["changes"] if change["application"] == "test-app"
    ]
    assert test_app_changes[0]["kind"] == "unreadable"
    assert test_app_changes[0]["error"] == f"Permission denied: {live_file}"
