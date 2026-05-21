# tests/test_items_123.py
# Regression tests for items 1-3:
#   1. deploy --python / --venv CLI option (tested via core_logic.upload_to_pypi)
#   2. ensure_build_tool / ensure_twine_tool split
#   3. generate_pypirc() in core_logic

import configparser
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from PiPnDeploy.core_logic import (
    _ensure_tool,
    ensure_build_tool,
    ensure_twine_tool,
    generate_pypirc,
    install_build_tools,
)


# ─── Item 2: ensure_build_tool / ensure_twine_tool split ─────────────────────

class TestEnsureBuildTool:
    def test_installs_build_when_missing(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            r = MagicMock(); r.returncode = 0; return r

        # _tool_is_available returns False (missing), then run installs it
        with patch("PiPnDeploy.core_logic._tool_is_available", return_value=False), \
             patch("PiPnDeploy.core_logic.subprocess.run", side_effect=fake_run):
            ensure_build_tool("/usr/bin/python3")

        assert any("build" in str(c) for c in calls), \
            "ensure_build_tool must install build"
        assert not any("twine" in str(c) for c in calls), \
            "ensure_build_tool must NOT install twine"

    def test_skips_when_already_present(self):
        calls = []

        with patch("PiPnDeploy.core_logic._tool_is_available", return_value=True), \
             patch("PiPnDeploy.core_logic.subprocess.run") as mock_run:
            ensure_build_tool("/usr/bin/python3")

        mock_run.assert_not_called()


class TestEnsureTwineTool:
    def test_installs_twine_when_missing(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            r = MagicMock(); r.returncode = 0; return r

        with patch("PiPnDeploy.core_logic._tool_is_available", return_value=False), \
             patch("PiPnDeploy.core_logic.subprocess.run", side_effect=fake_run):
            ensure_twine_tool("/usr/bin/python3")

        assert any("twine" in str(c) for c in calls), \
            "ensure_twine_tool must install twine"
        assert not any(c for c in calls if "build" in str(c) and "twine" not in str(c)), \
            "ensure_twine_tool must NOT install build"

    def test_skips_when_already_present(self):
        with patch("PiPnDeploy.core_logic._tool_is_available", return_value=True), \
             patch("PiPnDeploy.core_logic.subprocess.run") as mock_run:
            ensure_twine_tool("/usr/bin/python3")

        mock_run.assert_not_called()


class TestInstallBuildToolsBackwardCompat:
    """install_build_tools() must still work for backward compatibility."""

    def test_installs_both_when_missing(self):
        installed = []

        def fake_run(cmd, **kwargs):
            installed.extend(cmd)
            r = MagicMock(); r.returncode = 0; return r

        with patch("PiPnDeploy.core_logic._tool_is_available", return_value=False), \
             patch("PiPnDeploy.core_logic.subprocess.run", side_effect=fake_run):
            install_build_tools("/usr/bin/python3")

        assert "build" in " ".join(str(x) for x in installed)
        assert "twine" in " ".join(str(x) for x in installed)


# ─── Item 3: generate_pypirc in core_logic ───────────────────────────────────

class TestGeneratePypirc:
    def test_creates_file_with_pypi_token(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.chdir(tmp_path)
        with patch("PiPnDeploy.core_logic.Path.home", return_value=tmp_path):
            out = generate_pypirc(pypi_token="pypi-abc123", overwrite=False)

        assert out.exists()
        config = configparser.ConfigParser()
        config.read(out)
        assert "pypi" in config
        assert config["pypi"]["password"] == "pypi-abc123"
        assert config["pypi"]["username"] == "__token__"

    def test_creates_file_with_testpypi_token(self, tmp_path):
        with patch("PiPnDeploy.core_logic.Path.home", return_value=tmp_path):
            out = generate_pypirc(testpypi_token="pypi-testtoken", overwrite=False)

        config = configparser.ConfigParser()
        config.read(out)
        assert "testpypi" in config
        assert "pypi" not in config   # only configured servers listed

    def test_creates_file_with_both_tokens(self, tmp_path):
        with patch("PiPnDeploy.core_logic.Path.home", return_value=tmp_path):
            out = generate_pypirc(
                pypi_token="pypi-main", testpypi_token="pypi-test", overwrite=False
            )

        config = configparser.ConfigParser()
        config.read(out)
        assert "pypi" in config
        assert "testpypi" in config

    def test_only_lists_configured_servers(self, tmp_path):
        """index-servers must only list pypi — not testpypi — when only pypi token given."""
        with patch("PiPnDeploy.core_logic.Path.home", return_value=tmp_path):
            out = generate_pypirc(pypi_token="pypi-only", overwrite=False)

        content = out.read_text()
        assert "testpypi" not in content

    def test_raises_with_no_tokens(self, tmp_path):
        with patch("PiPnDeploy.core_logic.Path.home", return_value=tmp_path):
            with pytest.raises(ValueError, match="At least one"):
                generate_pypirc(overwrite=False)

    def test_raises_if_exists_and_overwrite_false(self, tmp_path):
        pypirc = tmp_path / ".pypirc"
        pypirc.write_text("[distutils]\n")
        with patch("PiPnDeploy.core_logic.Path.home", return_value=tmp_path):
            with pytest.raises(FileExistsError, match="already exists"):
                generate_pypirc(pypi_token="pypi-abc", overwrite=False)

    def test_overwrites_with_backup_when_overwrite_true(self, tmp_path):
        pypirc = tmp_path / ".pypirc"
        pypirc.write_text("[distutils]\nindex-servers = old\n")
        with patch("PiPnDeploy.core_logic.Path.home", return_value=tmp_path):
            generate_pypirc(pypi_token="pypi-new", overwrite=True, backup=True)

        bak = tmp_path / ".pypirc.bak"
        assert bak.exists(), ".pypirc.bak must be created when overwriting"
        assert "old" in bak.read_text(), "backup must contain original content"
        config = configparser.ConfigParser()
        config.read(pypirc)
        assert config["pypi"]["password"] == "pypi-new"

    def test_no_backup_when_backup_false(self, tmp_path):
        pypirc = tmp_path / ".pypirc"
        pypirc.write_text("[distutils]\n")
        with patch("PiPnDeploy.core_logic.Path.home", return_value=tmp_path):
            generate_pypirc(pypi_token="pypi-abc", overwrite=True, backup=False)

        assert not (tmp_path / ".pypirc.bak").exists()

    @pytest.mark.skipif(os.name == "nt", reason="chmod not applicable on Windows")
    def test_sets_permissions_600_on_unix(self, tmp_path):
        with patch("PiPnDeploy.core_logic.Path.home", return_value=tmp_path):
            out = generate_pypirc(pypi_token="pypi-abc", overwrite=False)

        mode = oct(out.stat().st_mode)[-3:]
        assert mode == "600", f"Expected 600, got {mode}"

    def test_returns_path_to_written_file(self, tmp_path):
        with patch("PiPnDeploy.core_logic.Path.home", return_value=tmp_path):
            out = generate_pypirc(pypi_token="pypi-abc", overwrite=False)

        assert isinstance(out, Path)
        assert out.name == ".pypirc"


# ─── Item 1: upload_to_pypi accepts python param (already tested elsewhere)
# These tests verify the deploy command path specifically ─────────────────────

class TestDeployPythonParam:
    """Verify upload_to_pypi correctly uses the python param for twine."""

    def test_upload_uses_provided_python(self, tmp_path):
        """The python param must be forwarded to the twine subprocess call."""
        from PiPnDeploy.core_logic import upload_to_pypi

        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            r = MagicMock(); r.returncode = 0; return r

        with patch("PiPnDeploy.core_logic.auth_check_for_target", return_value=(True, "")), \
             patch("PiPnDeploy.core_logic.run_hook", return_value=True), \
             patch("PiPnDeploy.core_logic.ensure_twine_tool"), \
             patch("PiPnDeploy.core_logic.subprocess.run", side_effect=fake_run):
            upload_to_pypi(project_root=tmp_path, python="/custom/python3")

        twine_calls = [c for c in calls if "twine" in str(c)]
        assert twine_calls, "twine must be called"
        assert twine_calls[0][0] == "/custom/python3", \
            f"Expected /custom/python3 as interpreter, got {twine_calls[0][0]}"

    def test_upload_defaults_to_sys_executable(self, tmp_path):
        import sys as _sys
        from PiPnDeploy.core_logic import upload_to_pypi

        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            r = MagicMock(); r.returncode = 0; return r

        with patch("PiPnDeploy.core_logic.auth_check_for_target", return_value=(True, "")), \
             patch("PiPnDeploy.core_logic.run_hook", return_value=True), \
             patch("PiPnDeploy.core_logic.ensure_twine_tool"), \
             patch("PiPnDeploy.core_logic.subprocess.run", side_effect=fake_run):
            upload_to_pypi(project_root=tmp_path)

        twine_calls = [c for c in calls if "twine" in str(c)]
        assert twine_calls[0][0] == _sys.executable
