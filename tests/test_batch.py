"""한 번에 받은 파일 묶음의 진행 계산과 화면 문구 시험."""
from __future__ import annotations

from pathlib import Path

from hwik import batch
from hwik.batch import Batch, apply
from hwik.core.events import TransferFailed, TransferFinished, TransferProgress, TransferStarted

FOLDER = Path("C:/받은 파일")


def started(transfer_id: str, name: str, size: int = 100) -> TransferStarted:
    return TransferStarted(transfer_id, name, size, "192.168.0.7")


def finished(transfer_id: str, name: str, size: int = 100) -> TransferFinished:
    return TransferFinished(transfer_id, FOLDER / name, size)


def receive_all(names: list[str], now: float = 0.0) -> Batch:
    current = Batch()
    for index, name in enumerate(names):
        current = apply(current, started(str(index), name), now)
        current = apply(current, finished(str(index), name), now)
    return current


def test_empty_batch() -> None:
    empty = Batch()

    assert empty.is_empty
    assert not empty.is_running
    assert empty.progress == 0.0


def test_apply_returns_new_batch_and_leaves_old_one_alone() -> None:
    before = Batch()

    after = apply(before, started("a", "a.png"), 0.0)

    assert before.is_empty
    assert after.is_running
    assert [item.name for item in after.items] == ["a.png"]


def test_progress_counts_bytes_across_files() -> None:
    current = apply(Batch(), started("a", "a.png", 100), 0.0)
    current = apply(current, finished("a", "a.png", 100), 0.1)
    current = apply(current, started("b", "b.mp4", 300), 0.2)
    current = apply(current, TransferProgress("b", 100, 300), 0.3)

    assert current.total_bytes == 400
    assert current.received_bytes == 200
    assert current.progress == 0.5
    assert current.is_running


def test_finished_item_remembers_saved_path() -> None:
    current = receive_all(["a.png"])

    assert current.saved_paths == (FOLDER / "a.png",)
    assert not current.is_running


def test_failed_item_keeps_message_and_is_not_counted_as_saved() -> None:
    current = apply(Batch(), started("a", "big.bin"), 0.0)
    current = apply(current, TransferFailed("a", "big.bin", "파일이 너무 커서 받지 않았습니다."), 0.1)

    assert current.saved_paths == ()
    assert current.failed_count == 1
    assert current.last_failure_message == "파일이 너무 커서 받지 않았습니다."
    assert not current.is_running


def test_events_for_unknown_transfer_are_ignored() -> None:
    current = apply(Batch(), started("a", "a.png"), 0.0)

    assert apply(current, TransferProgress("zzz", 5, 10), 0.1).items == current.items
    assert apply(current, finished("zzz", "x.png"), 0.1).items == current.items


def test_file_arriving_soon_after_previous_one_joins_same_batch() -> None:
    current = receive_all(["a.png"], now=10.0)

    current = apply(current, started("b", "b.png"), 10.0 + batch.BATCH_GAP_SECONDS - 0.1)

    assert len(current.items) == 2


def test_file_arriving_long_after_previous_batch_starts_new_batch() -> None:
    current = receive_all(["a.png", "b.png"], now=10.0)

    current = apply(current, started("c", "c.png"), 10.0 + batch.BATCH_GAP_SECONDS + 0.1)

    assert [item.name for item in current.items] == ["c.png"]


def test_new_file_while_another_is_still_running_joins_batch_even_after_long_time() -> None:
    current = apply(Batch(), started("a", "long.mp4"), 0.0)

    current = apply(current, started("b", "b.png"), 500.0)

    assert len(current.items) == 2


def test_batch_is_settled_only_after_quiet_gap() -> None:
    current = receive_all(["a.png"], now=10.0)

    assert not current.is_settled(10.5)
    assert current.is_settled(10.0 + batch.BATCH_GAP_SECONDS + 0.1)
    assert not Batch().is_settled(100.0)


def test_running_batch_is_never_settled() -> None:
    current = apply(Batch(), started("a", "a.png"), 0.0)

    assert not current.is_settled(1000.0)


def test_speed_is_bytes_per_second_since_batch_started() -> None:
    current = apply(Batch(), started("a", "a.bin", 1000), 10.0)
    current = apply(current, TransferProgress("a", 500, 1000), 12.0)

    assert current.speed(12.0) == 250.0
    assert Batch().speed(5.0) == 0.0


def test_headline_for_running_batch_shows_which_file() -> None:
    current = receive_all(["a.png"])
    current = apply(current, started("b", "b.png"), 0.1)

    assert batch.headline(current) == "받는 중 2 / 2"
    assert batch.headline(apply(Batch(), started("a", "a.png"), 0.0)) == "받는 중"


def test_headline_counts_files_that_are_still_to_come() -> None:
    first = TransferStarted("a", "a.png", 100, "192.168.0.7", upcoming_files=9, upcoming_bytes=900)

    assert batch.headline(apply(Batch(), first, 0.0)) == "받는 중 1 / 10"


def test_time_left_and_progress_include_files_that_have_not_started_yet() -> None:
    mb = 1024 * 1024
    first = TransferStarted("a", "a.mp4", 100 * mb, "192.168.0.7", upcoming_files=1, upcoming_bytes=300 * mb)
    current = apply(Batch(), first, 0.0)
    current = apply(current, TransferProgress("a", 20 * mb, 100 * mb), 2.0)

    assert current.progress == 0.05
    assert batch.detail(current, 2.0) == "a.mp4\n초당 10.0MB · 약 40초 남음"


def test_newest_file_says_how_much_is_still_to_come() -> None:
    current = apply(Batch(), TransferStarted("a", "a.png", 100, "p", upcoming_files=1, upcoming_bytes=300), 0.0)
    current = apply(current, finished("a", "a.png"), 0.1)
    current = apply(current, TransferStarted("b", "b.png", 300, "p"), 0.2)

    assert current.expected_bytes == 400
    assert batch.headline(current) == "받는 중 2 / 2"


def test_headline_names_what_was_received() -> None:
    assert batch.headline(receive_all(["a.png"])) == "사진 1장 받았습니다"
    assert batch.headline(receive_all(["a.png", "b.JPG", "c.heic"])) == "사진 3장 받았습니다"
    assert batch.headline(receive_all(["a.mp4", "b.mov"])) == "영상 2개 받았습니다"
    assert batch.headline(receive_all(["a.png", "b.pdf"])) == "파일 2개 받았습니다"
    assert batch.headline(receive_all(["보고서.hwp"])) == "파일 1개 받았습니다"


def test_headline_tells_when_some_or_all_failed() -> None:
    partly = receive_all(["a.png"])
    partly = apply(partly, started("x", "b.png"), 0.1)
    partly = apply(partly, TransferFailed("x", "b.png", "끊김"), 0.2)
    nothing = apply(Batch(), started("x", "b.png"), 0.0)
    nothing = apply(nothing, TransferFailed("x", "b.png", "끊김"), 0.1)

    assert batch.headline(partly) == "2개 중 1개만 받음"
    assert batch.headline(nothing) == "받지 못했습니다"


def test_format_size() -> None:
    assert batch.format_size(0) == "1KB"
    assert batch.format_size(1536) == "2KB"
    assert batch.format_size(5 * 1024 * 1024) == "5.0MB"
    assert batch.format_size(3 * 1024**3) == "3.0GB"


def test_format_remaining() -> None:
    assert batch.format_remaining(2) == "곧 끝남"
    assert batch.format_remaining(12) == "약 15초 남음"
    assert batch.format_remaining(125) == "약 3분 남음"
    assert batch.format_remaining(55) == "약 55초 남음"
    assert batch.format_remaining(58) == "약 1분 남음"


def test_detail_for_running_batch_shows_name_speed_and_time_left() -> None:
    current = apply(Batch(), started("a", "여행.mp4", 100 * 1024 * 1024), 0.0)
    current = apply(current, TransferProgress("a", 20 * 1024 * 1024, 100 * 1024 * 1024), 2.0)

    assert batch.detail(current, 2.0) == "여행.mp4\n초당 10.0MB · 약 10초 남음"


def test_detail_hides_speed_at_the_very_start() -> None:
    current = apply(Batch(), started("a", "a.png", 1000), 0.0)

    assert batch.detail(current, 0.1) == "a.png"


def test_failed_file_counts_only_what_arrived_so_progress_can_reach_the_end() -> None:
    current = apply(Batch(), started("a", "a.bin", 1000), 0.0)
    current = apply(current, TransferProgress("a", 300, 1000), 0.1)
    current = apply(current, TransferFailed("a", "a.bin", "끊김"), 0.2)
    current = apply(current, started("b", "b.bin", 700), 0.3)
    current = apply(current, TransferProgress("b", 700, 700), 0.4)

    assert current.total_bytes == 1000
    assert current.progress == 1.0
