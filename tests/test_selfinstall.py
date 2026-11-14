"""스스로 설치·제거하는 부품 시험. 실제 레지스트리·바로가기·프로그램 폴더는 건드리지 않는다."""
from __future__ import annotations

from pathlib import Path

import pytest

from hwik import selfinstall


@pytest.fixture
def local(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    return tmp_path / "local"


def test_install_folder_is_under_users_own_programs_folder(local: Path) -> None:
    assert selfinstall.install_dir() == local / "Programs" / "Hwik"


def test_running_from_unzipped_folder_needs_install(local: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(selfinstall.sys, "executable", str(tmp_path / "내려받기" / "Hwik" / "Hwik.exe"))

    assert selfinstall.needs_install()


def test_running_from_install_folder_does_not_need_install(local: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(selfinstall.sys, "executable", str(local / "programs" / "HWIK" / "Hwik.exe"))

    assert not selfinstall.needs_install()


def test_copy_tree_copies_files_but_not_caches_and_reports_progress(tmp_path: Path) -> None:
    src, dst = tmp_path / "src", tmp_path / "dst"
    (src / "app" / "__pycache__").mkdir(parents=True)
    (src / "app" / "a.py").write_text("a", encoding="utf-8")
    (src / "app" / "__pycache__" / "a.pyc").write_bytes(b"x")
    (src / "Hwik.exe").write_bytes(b"exe")
    steps: list[tuple[int, int]] = []

    selfinstall.copy_tree(src, dst, lambda done, total: steps.append((done, total)))

    assert sorted(p.relative_to(dst).as_posix() for p in dst.rglob("*") if p.is_file()) == ["Hwik.exe", "app/a.py"]
    assert steps[-1] == (2, 2)


def test_clear_refuses_any_folder_other_than_install_folder(local: Path, tmp_path: Path) -> None:
    precious = tmp_path / "내 문서"
    precious.mkdir()
    (precious / "중요.txt").write_text("x", encoding="utf-8")

    with pytest.raises(ValueError):
        selfinstall.clear_old_files(precious)

    assert (precious / "중요.txt").exists()


def test_clear_removes_old_program_files(local: Path) -> None:
    old = selfinstall.install_dir()
    (old / "app").mkdir(parents=True)
    (old / "app" / "old.py").write_text("x", encoding="utf-8")

    selfinstall.clear_old_files(old)

    assert not old.exists()


def test_uninstall_command_runs_installed_exe(local: Path) -> None:
    command = selfinstall.uninstall_command(selfinstall.install_dir())

    assert command == f'"{selfinstall.install_dir() / "Hwik.exe"}" -m hwik --uninstall'


def test_shortcut_scripts_take_paths_only_from_environment() -> None:
    """경로를 명령 글자에 끼워 넣지 않는다(이름에 따옴표가 든 폴더로 명령이 바뀌지 않게)."""
    for script in (selfinstall.MAKE_SHORTCUTS, selfinstall.REMOVE_SHORTCUTS):
        assert "$env:HWIK_EXE" in script
        assert "Hwik.exe" not in script and ":\\" not in script  # 실제 경로가 글자로 박혀 있지 않다


def test_shortcut_environment_carries_exe_icon_and_choice(local: Path) -> None:
    env = selfinstall.shortcut_environment(selfinstall.install_dir(), desktop=False)

    assert env["HWIK_EXE"].endswith("Hwik.exe")
    assert env["HWIK_ICON"].endswith("hwik.ico")
    assert env["HWIK_DESKTOP"] == "0"
    assert env["HWIK_NAME"] == "Hwik"
