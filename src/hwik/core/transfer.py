"""휴대폰이 보낸 파일을 저장 폴더 안에 안전하게 저장한다.

지키는 것: 저장 폴더 밖으로 나가지 않는다, 있던 파일을 덮어쓰지 않는다, 다 오지 않은 파일을 남기지 않는다,
디스크를 가득 채우지 않는다, 받은 파일을 열거나 실행하지 않는다.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import threading
import time
import unicodedata
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from hwik.core.errors import (
    FileTooLargeError,
    IncompleteTransferError,
    NotEnoughSpaceError,
    TransferError,
)

logger = logging.getLogger(__name__)

CHUNK_BYTES = 256 * 1024
MAX_NAME_LENGTH = 150  # 윈도우가 세는 방식(UTF-16 단위)으로 잰 길이. 번호 꼬리가 붙을 자리를 남긴다
MAX_SUFFIX_LENGTH = 20
MAX_DUPLICATE_NUMBER = 10_000
EMPTY_NAME = "파일"
PART_SUFFIX = ".part"
DEFUSE_SUFFIX = ".txt"
DEFAULT_MAX_FILE_BYTES = 20 * 1024**3
DEFAULT_FREE_SPACE_MARGIN_BYTES = 1024**3  # 받고 나서도 디스크에 이만큼은 남긴다
DEFAULT_MIN_BYTES_PER_SECOND = 8 * 1024
DEFAULT_SLOW_GRACE_SECONDS = 20.0
# 윈도우가 "인터넷에서 받은 파일"로 다루게 하는 표시. 실행하려 하면 윈도우가 먼저 경고한다.
_OUTSIDE_MARK = "[ZoneTransfer]\r\nZoneId=3\r\n"
_FORBIDDEN_CHARACTERS = re.compile(r'[<>:"|?*]')
_WHITESPACE_RUN = re.compile(r"\s+")
_STALE_PART = re.compile(r"^\.[0-9a-f]{32}\.part$")
_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"{port}{number}" for port in ("COM", "LPT") for number in "123456789¹²³"}
)
_INVISIBLE_CATEGORIES = frozenset({"Cc", "Cf"})  # 제어 글자, 글자 방향을 뒤집어 확장자를 속이는 글자 등
# 탐색기가 폴더를 열기만 해도 내용을 읽어 해석하는 파일. 이름 끝에 .txt를 붙여 해석되지 않게 둔다.
_SHELL_SUFFIXES = frozenset(
    {
        ".lnk", ".url", ".website", ".library-ms", ".searchconnector-ms", ".scf", ".theme",
        ".themepack", ".desktopthemepackfile", ".appref-ms", ".settingcontent-ms",
    }
)
_SHELL_NAMES = frozenset({"desktop.ini", "autorun.inf"})

_place_lock = threading.Lock()
_space_lock = threading.Lock()
_promised_bytes = 0  # 지금 받고 있는 전송들이 앞으로 차지할 양

ProgressCallback = Callable[[int, int], None]
"""(지금까지 받은 바이트, 전체 바이트)"""


@dataclass(frozen=True)
class ReceiveLimits:
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    free_space_margin_bytes: int = DEFAULT_FREE_SPACE_MARGIN_BYTES
    min_bytes_per_second: int = DEFAULT_MIN_BYTES_PER_SECOND  # 이보다 느리게 기어 오는 전송은 끊는다
    slow_grace_seconds: float = DEFAULT_SLOW_GRACE_SECONDS  # 처음 이만큼은 느려도 봐준다


@dataclass(frozen=True)
class ReceivedFile:
    path: Path
    size: int


def safe_file_name(raw_name: str) -> str:
    """보낸 쪽이 준 이름에서 폴더 부분과 위험한 글자를 없앤, 저장해도 되는 이름."""
    name = unicodedata.normalize("NFC", raw_name)  # 아이폰은 한글을 자모로 풀어서 보낸다
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join("_" if unicodedata.category(char) in _INVISIBLE_CATEGORIES else char for char in name)
    name = _FORBIDDEN_CHARACTERS.sub("_", name)
    name = _WHITESPACE_RUN.sub(" ", name).strip().rstrip(" .")  # 긴 공백으로 진짜 확장자를 밀어내 숨기지 못하게
    if Path(name).suffix.lower() in _SHELL_SUFFIXES or name.lower() in _SHELL_NAMES:
        name += DEFUSE_SUFFIX
    name = _shorten(name) or EMPTY_NAME
    # 예약 이름은 줄인 뒤에 본다(줄이다가 예약 이름이 될 수 있다).
    if name.split(".", 1)[0].rstrip(" ").upper() in _RESERVED_NAMES:
        name = f"_{name}"
    return name


def _units(text: str) -> int:
    """윈도우가 세는 글자 수. 이모지처럼 두 칸을 차지하는 글자가 있다."""
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def _cut(text: str, units: int) -> str:
    text = text[: max(units, 0)]
    while _units(text) > units:
        text = text[:-1]
    return text


def _shorten(name: str) -> str:
    if _units(name) <= MAX_NAME_LENGTH:
        return name
    suffix = Path(name).suffix
    if _units(suffix) > MAX_SUFFIX_LENGTH:
        suffix = ""
    stem = _cut(name[: len(name) - len(suffix)], MAX_NAME_LENGTH - _units(suffix)).rstrip(" .")
    return stem + suffix if stem else ""


def receive_file(
    source: BinaryIO,
    length: int,
    folder: Path,
    raw_name: str,
    limits: ReceiveLimits,
    on_progress: ProgressCallback | None = None,
) -> ReceivedFile:
    """source에서 정확히 length바이트를 읽어 folder 안에 저장한다."""
    if length < 0:
        raise TransferError("파일 크기를 알 수 없어 받지 않았습니다.")
    if length > limits.max_file_bytes:
        raise FileTooLargeError("파일이 너무 커서 받지 않았습니다.")
    name = safe_file_name(raw_name)
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        raise TransferError("저장 폴더를 쓸 수 없습니다. 설정에서 저장 폴더를 확인해 주세요.") from err
    part = folder / f".{uuid.uuid4().hex}{PART_SUFFIX}"
    with _promised_space(folder, length, limits):
        try:
            _copy(source, part, length, limits, on_progress)
            _mark_as_from_outside(part)  # 이름을 붙이기 전에 표시한다(표시 없는 파일이 잠깐이라도 보이지 않게)
            target = _move_into_place(part, folder, name)
        except BaseException:
            _remove_quietly(part)
            raise
    return ReceivedFile(path=target, size=length)


def remove_stale_parts(folder: Path) -> None:
    """지난번에 프로그램이 갑자기 꺼져 남은 덜 받은 파일을 지운다. 이 프로그램이 만든 이름 꼴만 지운다."""
    try:
        leftovers = [path for path in folder.iterdir() if _STALE_PART.match(path.name)]
    except OSError:
        return  # 폴더가 아직 없거나 읽을 수 없다
    for path in leftovers:
        _remove_quietly(path)


@contextmanager
def _promised_space(folder: Path, length: int, limits: ReceiveLimits) -> Iterator[None]:
    """빈 공간을 확인하고 이 전송 몫을 잡아 둔다. 동시에 받는 전송들이 합쳐서 디스크를 채우지 못하게."""
    global _promised_bytes
    with _space_lock:
        try:
            free = _free_bytes(folder)
        except OSError as err:
            raise TransferError("저장 폴더를 쓸 수 없습니다. 설정에서 저장 폴더를 확인해 주세요.") from err
        if free - _promised_bytes - length < limits.free_space_margin_bytes:
            raise NotEnoughSpaceError("PC에 빈 공간이 모자라 받지 않았습니다.")
        _promised_bytes += length
    try:
        yield
    finally:
        with _space_lock:
            _promised_bytes -= length


def _free_bytes(folder: Path) -> int:
    return shutil.disk_usage(folder).free


def _now() -> float:
    return time.monotonic()


def _copy(
    source: BinaryIO, part: Path, length: int, limits: ReceiveLimits, on_progress: ProgressCallback | None
) -> None:
    received, started = 0, _now()
    try:
        out = part.open("xb")
    except OSError as err:
        raise TransferError("저장 폴더에 파일을 만들지 못했습니다.") from err
    with out:
        while received < length:
            piece = _read(source, min(CHUNK_BYTES, length - received))
            try:
                out.write(piece)
            except OSError as err:
                raise TransferError("파일을 저장하는 중 문제가 생겼습니다.") from err
            received += len(piece)
            if on_progress is not None:
                on_progress(received, length)
            _stop_if_crawling(received, length, _now() - started, limits)


def _stop_if_crawling(received: int, length: int, elapsed: float, limits: ReceiveLimits) -> None:
    """아주 조금씩만 보내며 연결을 붙잡아 두는 상대를 끊는다."""
    if received >= length or elapsed <= limits.slow_grace_seconds:
        return
    if received / elapsed < limits.min_bytes_per_second:
        raise IncompleteTransferError("전송이 너무 느려서 받기를 멈췄습니다.")


def _read(source: BinaryIO, size: int) -> bytes:
    try:
        piece = source.read(size)
    except OSError as err:
        raise IncompleteTransferError("보내는 중 연결이 끊겼습니다.") from err
    if not piece:
        raise IncompleteTransferError("보내는 중 연결이 끊겼습니다.")
    return piece


def _move_into_place(part: Path, folder: Path, name: str) -> Path:
    """다 받은 파일에 진짜 이름을 붙인다. 같은 이름이 있으면 번호를 붙이고 덮어쓰지 않는다."""
    if Path(name).name != name or name in (".", ".."):
        raise TransferError("파일 이름을 쓸 수 없습니다.")
    stem, suffix = Path(name).stem, Path(name).suffix
    with _place_lock:
        for number in range(MAX_DUPLICATE_NUMBER):
            target = folder / (name if number == 0 else f"{stem} ({number}){suffix}")
            try:
                if target.exists():
                    continue
                os.rename(part, target)  # 윈도우에서는 대상이 이미 있으면 실패한다(덮어쓰지 않음)
            except FileExistsError:
                continue
            except OSError as err:
                raise TransferError("파일을 저장하는 중 문제가 생겼습니다.") from err
            return target
    raise TransferError("같은 이름의 파일이 너무 많습니다.")


def _mark_as_from_outside(path: Path) -> None:
    try:
        with open(f"{path}:Zone.Identifier", "w", encoding="utf-8", newline="") as mark:
            mark.write(_OUTSIDE_MARK)
    except OSError as err:
        logger.info("파일 출처 표시를 남기지 못했습니다(지원하지 않는 디스크일 수 있음): %s", err)


def _remove_quietly(part: Path) -> None:
    try:
        part.unlink(missing_ok=True)
    except OSError as err:
        logger.warning("덜 받은 파일을 지우지 못했습니다: %s", type(err).__name__)  # 경로는 기록에 남기지 않는다
