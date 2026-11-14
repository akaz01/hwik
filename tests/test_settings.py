"""설정 저장·불러오기 시험."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from hwik import settings
from hwik.settings import Settings


def test_defaults_point_to_a_folder_inside_downloads() -> None:
    defaults = Settings()

    assert Path(defaults.save_dir).parent == Path.home() / "Downloads"
    assert defaults.copy_to_clipboard is True


def test_settings_cannot_be_changed_in_place() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        Settings().save_dir = "x"  # type: ignore[misc]


def test_save_then_load_returns_same_settings(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "settings.json"
    wanted = Settings(save_dir=str(tmp_path / "받은 파일"), copy_to_clipboard=False)

    settings.save(wanted, path)

    assert settings.load(path) == wanted
    assert [item.name for item in path.parent.iterdir()] == ["settings.json"]


def test_saved_file_keeps_korean_readable(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"

    settings.save(Settings(save_dir="C:\\받은 파일"), path)

    assert "받은 파일" in path.read_text(encoding="utf-8")


def test_load_returns_defaults_when_file_is_missing(tmp_path: Path) -> None:
    assert settings.load(tmp_path / "none.json") == Settings()


@pytest.mark.parametrize("content", ["", "{broken", "[1, 2]", '"text"', "null"])
def test_load_returns_defaults_when_file_is_broken(tmp_path: Path, content: str) -> None:
    path = tmp_path / "settings.json"
    path.write_text(content, encoding="utf-8")

    assert settings.load(path) == Settings()


def test_load_ignores_wrong_types_and_unknown_keys(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"save_dir": 5, "copy_to_clipboard": "yes", "old_key": 1}), encoding="utf-8"
    )

    assert settings.load(path) == Settings()


def test_load_keeps_valid_fields_next_to_invalid_ones(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"save_dir": "D:\\받기", "copy_to_clipboard": "yes"}), encoding="utf-8")

    assert settings.load(path) == Settings(save_dir="D:\\받기", copy_to_clipboard=True)


def test_load_ignores_empty_or_relative_save_dir(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    for bad in ("", "   ", "relative\\folder"):
        path.write_text(json.dumps({"save_dir": bad}), encoding="utf-8")

        assert settings.load(path) == Settings()


@pytest.mark.parametrize(
    "bad",
    ["C:\\", "D:/", "\\\\server\\share\\받기", "//server/share/x", "C:\\a\\..\\Windows", "relative", ""],
)
def test_risky_locations_are_not_usable_as_save_dir(bad: str) -> None:
    assert settings.is_usable_save_dir(bad) is False


@pytest.mark.parametrize("good", ["C:\\Users\\me\\Downloads\\받은 파일", "D:\\받기", "E:/사진/휴대폰"])
def test_ordinary_folders_are_usable_as_save_dir(good: str) -> None:
    assert settings.is_usable_save_dir(good) is True


def test_load_ignores_risky_save_dir_in_file(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"save_dir": "C:\\"}), encoding="utf-8")

    assert settings.load(path) == Settings()


def test_load_survives_absurdly_nested_file(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("[" * 100_000, encoding="utf-8")

    assert settings.load(path) == Settings()


def test_settings_path_is_under_appdata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))

    assert settings.settings_path() == tmp_path / "Hwik" / "settings.json"


HOME = Path("C:/Users/tester")


def test_display_path_drops_home_and_uses_explorer_names() -> None:
    shown = settings.display_path(str(HOME / "Downloads" / "휴대폰에서 받은 파일"), HOME)

    assert shown == "다운로드 › 휴대폰에서 받은 파일"


def test_display_path_keeps_unknown_folder_names_under_home() -> None:
    assert settings.display_path(str(HOME / "작업" / "받은 것"), HOME) == "작업 › 받은 것"


def test_display_path_outside_home_is_shown_whole() -> None:
    assert settings.display_path("D:\사진\받은 것", HOME) == "D:\사진\받은 것"
    assert settings.display_path(str(HOME), HOME) == str(HOME)
