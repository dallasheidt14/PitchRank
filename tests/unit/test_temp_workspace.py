from pathlib import Path

from src.tournaments import temp_workspace


def test_windows_workspace_inherits_parent_acl_and_is_removed(monkeypatch, tmp_path):
    monkeypatch.setattr(temp_workspace.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(temp_workspace, "_WINDOWS", True)
    mkdir_modes = []
    real_mkdir = Path.mkdir

    def tracked_mkdir(path, mode=0o777, parents=False, exist_ok=False):
        mkdir_modes.append(mode)
        return real_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(Path, "mkdir", tracked_mkdir)
    with temp_workspace.temporary_workspace("matchbalance-seeding-") as workspace:
        created = workspace
        payload = workspace / "input.json"
        payload.write_text("{}", encoding="utf-8")
        assert payload.read_text(encoding="utf-8") == "{}"

    assert mkdir_modes == [0o777]
    assert not created.exists()


def test_posix_workspace_remains_owner_only(monkeypatch, tmp_path):
    monkeypatch.setattr(temp_workspace.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(temp_workspace, "_WINDOWS", False)
    mkdir_modes = []
    real_mkdir = Path.mkdir

    def tracked_mkdir(path, mode=0o777, parents=False, exist_ok=False):
        mkdir_modes.append(mode)
        return real_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(Path, "mkdir", tracked_mkdir)
    with temp_workspace.temporary_workspace("matchbalance-seeding-"):
        pass

    assert mkdir_modes == [0o700]
