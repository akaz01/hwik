"""휴대폰이 보낸 파일을 안전하게 저장하는 부분 시험."""
from __future__ import annotations

import io
import threading
import unicodedata
from pathlib import Path

import pytest

from hwik.core import transfer
from hwik.core.errors import (
    FileTooLargeError,
    IncompleteTransferError,
    NotEnoughSpaceError,
    TransferError,
)
from hwik.core.transfer import ReceiveLimits, receive_file, safe_file_name

LIMITS = ReceiveLimits(max_file_bytes=1024 * 1024, free_space_margin_bytes=0)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("사진.png", "사진.png"),
        ("../../evil.bin", "evil.bin"),
        ("..\\..\\evil.bin", "evil.bin"),
        ("C:\\Windows\\system32\\a.dll", "a.dll"),
        ("/etc/passwd", "passwd"),
        ('a<b>c:d"e|f?g*h.txt', "a_b_c_d_e_f_g_h.txt"),
        ("tab\tnew\nline.txt", "tab_new_line.txt"),
        ("  name.txt  ", "name.txt"),
        ("name.txt...", "name.txt"),
        ("", "파일"),
        ("...", "파일"),
        ("/", "파일"),
        ("CON", "_CON"),
        ("con.txt", "_con.txt"),
        ("LPT1.png", "_LPT1.png"),
        ("COM9", "_COM9"),
        ("console.txt", "console.txt"),
        (".gitignore", ".gitignore"),
    ],
)
def test_safe_file_name(raw: str, expected: str) -> None:
    assert safe_file_name(raw) == expected


def test_safe_file_name_joins_split_korean_letters_from_iphone() -> None:
    split = unicodedata.normalize("NFD", "한글 사진.jpg")

    assert safe_file_name(split) == "한글 사진.jpg"


def test_safe_file_name_shortens_very_long_names_but_keeps_extension() -> None:
    name = safe_file_name("가" * 500 + ".jpeg")

    assert name.endswith(".jpeg")
    assert len(name) <= transfer.MAX_NAME_LENGTH


def test_safe_file_name_drops_absurdly_long_extension() -> None:
    name = safe_file_name("a." + "x" * 400)

    assert len(name) <= transfer.MAX_NAME_LENGTH


def receive(folder: Path, data: bytes, name: str = "a.bin", limits: ReceiveLimits = LIMITS) -> transfer.ReceivedFile:
    return receive_file(io.BytesIO(data), len(data), folder, name, limits)


def test_receive_file_saves_bytes_under_safe_name(tmp_path: Path) -> None:
    received = receive(tmp_path, b"hello", "../사진.png")

    assert received.path == tmp_path / "사진.png"
    assert received.size == 5
    assert received.path.read_bytes() == b"hello"


def test_receive_file_creates_missing_folder(tmp_path: Path) -> None:
    folder = tmp_path / "받은 파일" / "오늘"

    received = receive(folder, b"x")

    assert received.path.parent == folder


def test_receive_file_numbers_duplicates_instead_of_overwriting(tmp_path: Path) -> None:
    first = receive(tmp_path, b"1", "a.png")
    second = receive(tmp_path, b"2", "a.png")
    third = receive(tmp_path, b"3", "a.png")

    assert [item.path.name for item in (first, second, third)] == ["a.png", "a (1).png", "a (2).png"]
    assert first.path.read_bytes() == b"1"


def test_receive_file_accepts_empty_file(tmp_path: Path) -> None:
    received = receive(tmp_path, b"", "empty.txt")

    assert received.path.read_bytes() == b""


def test_receive_file_reports_progress(tmp_path: Path) -> None:
    seen: list[tuple[int, int]] = []
    data = b"x" * (transfer.CHUNK_BYTES * 2 + 10)

    receive_file(io.BytesIO(data), len(data), tmp_path, "a.bin", LIMITS, on_progress=lambda got, total: seen.append((got, total)))

    assert seen[-1] == (len(data), len(data))
    assert [got for got, _ in seen] == sorted(got for got, _ in seen)
    assert len(seen) == 3


def test_receive_file_refuses_file_over_limit_without_reading(tmp_path: Path) -> None:
    source = io.BytesIO(b"x" * 10)

    with pytest.raises(FileTooLargeError):
        receive_file(source, LIMITS.max_file_bytes + 1, tmp_path, "big.bin", LIMITS)

    assert source.tell() == 0
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("length", [-1, -100])
def test_receive_file_refuses_negative_length(tmp_path: Path, length: int) -> None:
    with pytest.raises(TransferError):
        receive_file(io.BytesIO(b""), length, tmp_path, "a.bin", LIMITS)


def test_receive_file_refuses_when_disk_is_nearly_full(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transfer, "_free_bytes", lambda folder: 100)
    limits = ReceiveLimits(max_file_bytes=10_000, free_space_margin_bytes=50)

    with pytest.raises(NotEnoughSpaceError):
        receive_file(io.BytesIO(b"x" * 60), 60, tmp_path, "a.bin", limits)

    assert list(tmp_path.iterdir()) == []


def test_receive_file_removes_partial_file_when_connection_drops(tmp_path: Path) -> None:
    with pytest.raises(IncompleteTransferError):
        receive_file(io.BytesIO(b"only-part"), 100, tmp_path, "a.bin", LIMITS)

    assert list(tmp_path.iterdir()) == []


def test_receive_file_removes_partial_file_when_reading_fails(tmp_path: Path) -> None:
    class Broken(io.RawIOBase):
        def readable(self) -> bool:
            return True

        def read(self, size: int = -1) -> bytes:
            raise ConnectionResetError("끊김")

    with pytest.raises(IncompleteTransferError):
        receive_file(Broken(), 100, tmp_path, "a.bin", LIMITS)

    assert list(tmp_path.iterdir()) == []


def test_receive_file_removes_partial_file_when_progress_callback_fails(tmp_path: Path) -> None:
    def explode(got: int, total: int) -> None:
        raise RuntimeError("화면 오류")

    with pytest.raises(RuntimeError):
        receive_file(io.BytesIO(b"abc"), 3, tmp_path, "a.bin", LIMITS, on_progress=explode)

    assert list(tmp_path.iterdir()) == []


def test_receive_file_never_reads_past_declared_length(tmp_path: Path) -> None:
    source = io.BytesIO(b"12345-next-request")

    received = receive_file(source, 5, tmp_path, "a.bin", LIMITS)

    assert received.path.read_bytes() == b"12345"
    assert source.read() == b"-next-request"


def test_receive_file_marks_file_as_coming_from_outside(tmp_path: Path) -> None:
    received = receive(tmp_path, b"x", "tool.exe")

    try:
        mark = Path(f"{received.path}:Zone.Identifier").read_text(encoding="utf-8")
    except OSError:
        pytest.skip("이 디스크는 파일 출처 표시를 지원하지 않는다")
    assert "ZoneId=3" in mark


def test_parallel_uploads_with_same_name_all_survive(tmp_path: Path) -> None:
    errors: list[BaseException] = []

    def send(index: int) -> None:
        try:
            receive(tmp_path, bytes([index]) * 100, "same.bin")
        except BaseException as err:  # noqa: BLE001 - 스레드 안의 실패를 시험 본문으로 옮긴다
            errors.append(err)

    threads = [threading.Thread(target=send, args=(index,)) for index in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    saved = sorted(tmp_path.iterdir())
    assert len(saved) == 12
    assert {path.read_bytes()[0] for path in saved} == set(range(12))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("CON .txt", "_CON .txt"),
        ("NUL .tar.gz", "_NUL .tar.gz"),
        ("COM¹.txt", "_COM¹.txt"),
        ("LPT²", "_LPT²"),
        ("CONIN$", "_CONIN$"),
        ("conout$.log", "_conout$.log"),
        ("photo.jpg" + " " * 100 + ".exe", "photo.jpg .exe"),
        ("바로가기.lnk", "바로가기.lnk.txt"),
        ("site.URL", "site.URL.txt"),
        ("x.library-ms", "x.library-ms.txt"),
        ("x.scf", "x.scf.txt"),
        ("desktop.ini", "desktop.ini.txt"),
        ("AutoRun.inf", "AutoRun.inf.txt"),
    ],
)
def test_safe_file_name_defuses_tricky_names(raw: str, expected: str) -> None:
    assert safe_file_name(raw) == expected


def test_safe_file_name_never_returns_empty_name_after_shortening() -> None:
    assert safe_file_name("." * 160 + "a" * 30) == "파일"
    assert safe_file_name("." + " " * 200 + "x") != ""


def test_safe_file_name_checks_reserved_names_after_shortening() -> None:
    name = safe_file_name("CON" + " " * 200 + "x.txt")

    assert name.split(".", 1)[0].strip().upper() != "CON"


def test_safe_file_name_counts_length_the_way_windows_does() -> None:
    name = safe_file_name("\U0001f600" * 150 + ".png")

    assert name.endswith(".png")
    assert len(name.encode("utf-16-le")) // 2 <= transfer.MAX_NAME_LENGTH


def test_long_emoji_name_can_actually_be_saved(tmp_path: Path) -> None:
    received = receive(tmp_path, b"x", "\U0001f600" * 150 + ".png")

    assert received.path.read_bytes() == b"x"


def test_space_already_promised_to_other_uploads_is_counted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transfer, "_free_bytes", lambda folder: 1000)
    limits = ReceiveLimits(max_file_bytes=10_000, free_space_margin_bytes=0)
    first_is_writing = threading.Event()
    let_first_finish = threading.Event()

    class SlowSource(io.RawIOBase):
        def readable(self) -> bool:
            return True

        def read(self, size: int = -1) -> bytes:
            first_is_writing.set()
            let_first_finish.wait(5)
            return b"x" * size

    first = threading.Thread(target=lambda: receive_file(SlowSource(), 600, tmp_path, "a.bin", limits))
    first.start()
    try:
        assert first_is_writing.wait(5)
        with pytest.raises(NotEnoughSpaceError):
            receive_file(io.BytesIO(b"y" * 600), 600, tmp_path, "b.bin", limits)
    finally:
        let_first_finish.set()
        first.join(5)

    assert sorted(path.name for path in tmp_path.iterdir()) == ["a.bin"]
    assert receive_file(io.BytesIO(b"z" * 300), 300, tmp_path, "c.bin", limits).size == 300


def test_promised_space_is_given_back_after_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transfer, "_free_bytes", lambda folder: 1000)
    limits = ReceiveLimits(max_file_bytes=10_000, free_space_margin_bytes=0)

    with pytest.raises(IncompleteTransferError):
        receive_file(io.BytesIO(b"short"), 900, tmp_path, "a.bin", limits)

    assert receive_file(io.BytesIO(b"x" * 900), 900, tmp_path, "b.bin", limits).size == 900


class Drip(io.RawIOBase):
    """한 번에 한 바이트씩만 주는 느린 상대."""

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        return b"x"


def slow_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    ticks = iter(range(0, 1_000_000, 30))  # 시계를 볼 때마다 30초씩 흐른다
    monkeypatch.setattr(transfer, "_now", lambda: float(next(ticks)))


def test_upload_that_crawls_is_stopped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    slow_clock(monkeypatch)
    limits = ReceiveLimits(max_file_bytes=10**9, free_space_margin_bytes=0, min_bytes_per_second=1024)

    with pytest.raises(IncompleteTransferError, match="느려"):
        receive_file(Drip(), 10**8, tmp_path, "a.bin", limits)

    assert list(tmp_path.iterdir()) == []


def test_fast_upload_is_not_mistaken_for_a_crawling_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    slow_clock(monkeypatch)
    limits = ReceiveLimits(max_file_bytes=10**9, free_space_margin_bytes=0, min_bytes_per_second=1024)
    data = b"x" * (transfer.CHUNK_BYTES * 3)

    assert receive_file(io.BytesIO(data), len(data), tmp_path, "a.bin", limits).size == len(data)


def test_stale_part_files_are_removed_but_other_files_are_kept(tmp_path: Path) -> None:
    stale = tmp_path / f".{'a1' * 16}.part"
    stale.write_bytes(b"left over")
    keep = [tmp_path / "사진.png", tmp_path / ".hidden.part", tmp_path / "x.part", tmp_path / f".{'zz' * 16}.part"]
    for path in keep:
        path.write_bytes(b"keep")

    transfer.remove_stale_parts(tmp_path)

    assert not stale.exists()
    assert all(path.exists() for path in keep)


def test_remove_stale_parts_ignores_missing_folder(tmp_path: Path) -> None:
    transfer.remove_stale_parts(tmp_path / "없는 폴더")
