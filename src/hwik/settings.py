"""사용자 설정: %APPDATA%\\<앱>\\settings.json 에 저장한다."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path, PureWindowsPath

from hwik import APP_NAME

PATH_SEPARATOR = " › "
_EXPLORER_NAMES = {  # 탐색기가 우리말로 보여 주는 홈 아래 폴더들
    "downloads": "다운로드",
    "desktop": "바탕 화면",
    "documents": "문서",
    "pictures": "사진",
    "videos": "동영상",
    "music": "음악",
}

logger = logging.getLogger(__name__)

SETTINGS_FILE = "settings.json"
DEFAULT_SAVE_FOLDER_NAME = "휴대폰에서 받은 파일"


def _default_save_dir() -> str:
    return str(Path.home() / "Downloads" / DEFAULT_SAVE_FOLDER_NAME)


@dataclass(frozen=True)
class Settings:
    save_dir: str = field(default_factory=_default_save_dir)
    copy_to_clipboard: bool = True  # 받은 것을 바로 붙여넣을 수 있게 클립보드에 넣는다


def settings_path() -> Path:
    appdata = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    return appdata / APP_NAME / SETTINGS_FILE


def load(path: Path | None = None) -> Settings:
    """저장된 설정. 파일이 없거나 깨졌으면 기본값, 일부 값만 이상하면 그 값만 기본값으로 둔다."""
    path = path or settings_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Settings()
    except (OSError, ValueError, RecursionError) as err:  # RecursionError: 괄호가 끝없이 겹친 깨진 파일
        logger.warning("설정 파일을 읽지 못해 기본값을 씁니다: %s", type(err).__name__)
        return Settings()
    if not isinstance(raw, dict):
        logger.warning("설정 파일 형식이 달라 기본값을 씁니다.")
        return Settings()
    return Settings(**{item.name: raw[item.name] for item in fields(Settings) if _is_valid(item.name, raw)})


def is_usable_save_dir(value: str) -> bool:
    """받은 파일을 둘 폴더로 써도 되는 경로인지. 드라이브 맨 위와 네트워크 경로는 받지 않는다.

    드라이브 맨 위(C:\\ 등)는 다른 파일과 뒤섞이고, 네트워크 경로는 끊기면 프로그램이 멈출 수 있다.
    """
    if not value.strip() or value.startswith(("\\\\", "//")):
        return False
    path = PureWindowsPath(value)
    return path.is_absolute() and path.parent != path and ".." not in path.parts


def _is_valid(name: str, raw: dict[str, object]) -> bool:
    value = raw.get(name)
    if name == "save_dir":
        return isinstance(value, str) and is_usable_save_dir(value)
    return isinstance(value, bool)


def save(settings: Settings, path: Path | None = None) -> None:
    """임시 파일에 쓴 뒤 바꿔치기한다(쓰다가 꺼져도 설정 파일이 반쯤 쓰인 채 남지 않게)."""
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def display_path(value: str, home: Path | None = None) -> str:
    """화면에 보여 줄 짧은 경로. 홈 폴더 아래면 홈 부분을 빼고 탐색기에서 보이는 이름으로 적는다."""
    try:
        parts = PureWindowsPath(value).relative_to(PureWindowsPath(home or Path.home())).parts
    except ValueError:
        return value
    if not parts:
        return value
    first = _EXPLORER_NAMES.get(parts[0].lower(), parts[0])
    return PATH_SEPARATOR.join((first, *parts[1:]))
