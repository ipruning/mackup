"""Tests for the --config-file command line option."""
import os
import unittest
from pathlib import Path

import pytest

from mackup.config import Config
from mackup.mackup import Mackup


class TestConfigFileOption(unittest.TestCase):
    def setUp(self):
        realpath = os.path.dirname(os.path.realpath(__file__))
        os.environ["HOME"] = os.path.join(realpath, "fixtures")

        # Clear environment variables that could interfere
        os.environ.pop("XDG_CONFIG_HOME", None)
        os.environ.pop("MACKUP_CONFIG", None)

    def test_config_with_relative_path(self):
        """Test that a relative path to config file works."""
        cfg = Config("mackup-apps_to_ignore.cfg")

        assert cfg.apps_to_ignore == {"subversion", "sequel-pro", "sabnzbd"}

    def test_config_with_absolute_path(self):
        """Test that an absolute path to config file works."""
        abs_path = os.path.join(os.environ["HOME"], "mackup-apps_to_sync.cfg")
        cfg = Config(abs_path)

        assert cfg.apps_to_sync == {"sabnzbd", "sublime-text-3", "x11"}

    def test_mackup_with_config_file(self):
        """Test that Mackup class accepts config_file parameter."""
        # This should not raise any errors
        mckp = Mackup("mackup-empty.cfg")

        # Verify that the config was properly initialized
        assert isinstance(mckp.mackup_folder, str)

    def test_mackup_without_config_file(self):
        """Test that Mackup class works without config_file parameter."""
        # This should use default config file discovery
        mckp = Mackup()

        # Verify that the config was properly initialized
        assert isinstance(mckp.mackup_folder, str)

    def test_config_file_does_not_exist(self):
        """Test that specifying a non-existent config file raises an error."""
        with pytest.raises(SystemExit):
            Config("nonexistent-config-file.cfg")


def test_explicit_config_file_can_be_outside_home(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    storage = tmp_path / "storage"
    config_path = tmp_path / "runtime" / "mackup.cfg"
    home.mkdir()
    config_path.parent.mkdir()
    config_path.write_text(
        "[storage]\nengine = file_system\n"
        f"path = {storage}\ndirectory = reference\n",
    )
    monkeypatch.setenv("HOME", str(home))

    config = Config(str(config_path))

    assert config.path == str(storage)
