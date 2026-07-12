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
        "directory = reference\n"
        "[applications_to_sync]\n"
        "test-app\n",
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

    with patch("sys.argv", argv), contextlib.redirect_stdout(output):
        main()

    document = json.loads(output.getvalue())
    assert document["schema_version"] == 1
    assert document["operation"] == "diff"
    assert document["changes"][0]["kind"] == "modified"
    assert "live-secret" not in output.getvalue()
    assert "reference-secret" not in output.getvalue()
    assert live_file.read_text() == "token=live-secret\n"
    assert reference_file.read_text() == "token=reference-secret\n"


def test_backup_is_not_a_public_command(monkeypatch) -> None:
    monkeypatch.setenv("HOME", os.fspath(Path.home()))
    with (
        patch("sys.argv", ["mackup", "backup"]),
        pytest.raises(SystemExit) as context,
    ):
        main()
    assert context.value.code == USAGE_ERROR
