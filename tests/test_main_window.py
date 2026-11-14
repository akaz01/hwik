"""앱 창의 상태 흐름 시험: 창을 띄우지 않고, 가짜 서비스와 가짜 시계로 돌린다."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel, QPushButton

from hwik import batch
from hwik.core.errors import NoNetworkError, TransferError
from hwik.core.events import (
    FileSent,
    TextReceived,
    TransferEvent,
    TransferFailed,
    TransferFinished,
    TransferStarted,
)
from hwik.service import Connection
from hwik.settings import Settings
from hwik.ui.main_window import MainWindow

pytestmark = pytest.mark.usefixtures("qapp")
PHONE = "192.168.0.7"


class FakeService:
    def __init__(self) -> None:
        self.is_running = False
        self.fail_with: TransferError | None = None
        self.started_with: list[Path] = []
        self.offered_files: list[Path] = []
        self.offer_count: int | None = None  # 정해 두면 실제로 올라간 개수인 것처럼 돌려준다
        self.offered_texts: list[str] = []

    def start(self, save_dir: Path) -> Connection:
        self.is_running = False
        if self.fail_with is not None:
            raise self.fail_with
        self.is_running = True
        self.started_with.append(save_dir)
        return Connection("192.168.0.5", 50000, "http://192.168.0.5:50000/t/abcdefghijklmnopqrstuv/")

    def stop(self) -> None:
        self.is_running = False

    def offer_files(self, paths: list[Path]) -> int:
        self.offered_files.extend(paths)
        return len(paths) if self.offer_count is None else self.offer_count

    def offer_text(self, text: str) -> None:
        self.offered_texts.append(text)


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class Harness:
    def __init__(self, save_dir: Path, copy_to_clipboard: bool = True) -> None:
        self.service = FakeService()
        self.clock = FakeClock()
        self.window = MainWindow(
            Settings(save_dir=str(save_dir), copy_to_clipboard=copy_to_clipboard), self.service, self.clock
        )
        self.summaries: list[str] = []
        self.window.batch_settled.connect(self.summaries.append)

    def send(self, event: TransferEvent) -> None:
        """서버가 지금 연결에서 알림을 보낸 것처럼 한다."""
        self.window.bridge(event)
        QGuiApplication.processEvents()

    def receive_file(self, name: str, transfer_id: str = "a") -> Path:
        path = Path(self.window.save_dir) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        self.send(TransferStarted(transfer_id, name, 1, PHONE))
        self.send(TransferFinished(transfer_id, path, 1))
        return path

    def settle(self) -> None:
        self.clock.now += batch.BATCH_GAP_SECONDS + 0.1
        self.window.refresh()

    @property
    def headline(self) -> str:
        return self.window.stage_view.headline


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[Harness]:
    made = Harness(tmp_path / "받은 파일")
    made.window.show()
    QGuiApplication.processEvents()
    yield made
    made.window.close()


def test_opening_window_starts_connection_and_shows_qr(harness: Harness) -> None:
    assert harness.service.started_with == [Path(harness.window.save_dir)]
    assert harness.window.stage_view.show_qr
    assert harness.window.stage_view.state == "waiting"


def test_receiving_then_result_is_shown_once(harness: Harness) -> None:
    harness.send(TransferStarted("a", "사진.png", 100, PHONE))

    assert harness.window.stage_view.state == "receiving"

    harness.send(TransferFinished("a", Path(harness.window.save_dir) / "사진.png", 100))
    harness.settle()
    harness.settle()

    assert harness.headline == "사진 1장 받았습니다"
    assert harness.window.stage_view.state == "done"
    assert harness.summaries == ["사진 1장 받았습니다"]


def test_result_is_not_shown_before_quiet_gap(harness: Harness) -> None:
    harness.receive_file("사진.png")

    harness.window.refresh()

    assert harness.summaries == []


def test_event_that_changes_nothing_does_not_show_result_again(harness: Harness) -> None:
    harness.receive_file("사진.png")
    harness.settle()

    harness.send(TransferFailed("unknown-id", "x.png", "끊김"))
    harness.settle()

    assert harness.summaries == ["사진 1장 받았습니다"]


def test_received_files_are_copied_for_pasting(harness: Harness) -> None:
    first = harness.receive_file("a.pdf", "a")
    second = harness.receive_file("b.pdf", "b")

    harness.settle()

    urls = [Path(url.toLocalFile()) for url in QGuiApplication.clipboard().mimeData().urls()]
    assert urls == [first, second]
    assert "복사했습니다" in harness.window.stage_view.detail


def test_received_files_are_still_copied_when_another_file_failed(harness: Harness) -> None:
    good = harness.receive_file("a.pdf", "a")
    harness.send(TransferStarted("b", "big.bin", 5, PHONE))
    harness.send(TransferFailed("b", "big.bin", "파일이 너무 커서 받지 않았습니다."))

    harness.settle()

    urls = [Path(url.toLocalFile()) for url in QGuiApplication.clipboard().mimeData().urls()]
    assert urls == [good]
    assert harness.window.stage_view.detail == "파일이 너무 커서 받지 않았습니다."


def test_nothing_is_copied_when_setting_is_off(tmp_path: Path) -> None:
    QGuiApplication.clipboard().setText("원래 있던 글자")
    quiet = Harness(tmp_path / "받은 파일", copy_to_clipboard=False)
    quiet.window.show()
    try:
        quiet.receive_file("a.pdf")
        quiet.settle()
        quiet.send(TextReceived("휴대폰에서 온 글자", PHONE))

        assert QGuiApplication.clipboard().text() == "원래 있던 글자"
    finally:
        quiet.window.close()


def test_closing_window_stops_connection(harness: Harness) -> None:
    harness.window.close()

    assert not harness.service.is_running


def test_event_arriving_after_close_is_ignored(harness: Harness) -> None:
    harness.window.close()

    harness.send(TransferStarted("late", "늦은 파일.png", 1, PHONE))
    harness.settle()

    assert harness.summaries == []


def test_event_from_previous_connection_does_not_disturb_new_qr(harness: Harness) -> None:
    stale_generation = harness.window.bridge.generation
    harness.window.close()
    harness.window.show()
    QGuiApplication.processEvents()

    harness.window.bridge.received.emit(stale_generation, TransferStarted("old", "old.png", 1, PHONE))
    harness.window.bridge.received.emit(stale_generation, TransferFailed("old", "old.png", "끊김"))
    QGuiApplication.processEvents()
    harness.settle()

    assert harness.window.stage_view.show_qr
    assert harness.summaries == []


def test_reopening_window_makes_a_new_connection(harness: Harness) -> None:
    harness.window.close()
    harness.window.show()
    QGuiApplication.processEvents()

    assert len(harness.service.started_with) == 2
    assert harness.window.stage_view.show_qr


def test_change_folder_button_is_locked_while_receiving(harness: Harness) -> None:
    button = harness.window.findChild(QPushButton, "changeFolder")
    assert button.isEnabled()

    harness.send(TransferStarted("a", "a.png", 100, PHONE))
    assert not button.isEnabled()

    harness.send(TransferFinished("a", Path(harness.window.save_dir) / "a.png", 100))
    harness.settle()
    assert button.isEnabled()


def test_connection_failure_shows_reason_and_retry(tmp_path: Path) -> None:
    broken = Harness(tmp_path / "받은 파일")
    broken.service.fail_with = NoNetworkError("와이파이에 연결돼 있지 않습니다.")
    broken.window.show()
    try:
        assert broken.window.stage_view.state == "failed"
        assert broken.window.stage_view.detail == "와이파이에 연결돼 있지 않습니다."
        assert broken.window.stage_view.secondary_label == "다시 시도"

        broken.service.fail_with = None
        broken.window.show_qr()

        assert broken.window.stage_view.show_qr
    finally:
        broken.window.close()


def test_qr_screen_is_centred_and_other_screens_read_from_the_left(harness: Harness) -> None:
    qr = harness.window.findChild(QLabel, "qrCard")
    headline = harness.window.findChild(QLabel, "stageHeadline")
    left_gap = qr.mapTo(harness.window, qr.rect().topLeft()).x()
    right_gap = harness.window.width() - left_gap - qr.width()

    assert abs(left_gap - right_gap) <= 1
    assert headline.alignment() & Qt.AlignmentFlag.AlignHCenter

    harness.receive_file("a.png")

    assert headline.alignment() & Qt.AlignmentFlag.AlignLeft


def test_main_screen_shows_full_path_of_save_folder(qapp: object) -> None:
    short = Harness(Path("D:/사진/받은 것"))
    try:
        label = short.window.findChild(QLabel, "folderPath")

        assert label.text() == str(Path("D:/사진/받은 것"))
        assert label.toolTip() == str(Path("D:/사진/받은 것"))
    finally:
        short.window.close()


def test_long_save_path_is_shortened_to_fit_but_kept_whole_in_tooltip(qapp: object) -> None:
    long_path = Path("D:/" + "/".join(f"아주 긴 폴더 이름 {n}" for n in range(12)))
    long = Harness(long_path)
    try:
        label = long.window.findChild(QLabel, "folderPath")

        assert "…" in label.text()
        assert label.fontMetrics().horizontalAdvance(label.text()) <= long.window.width() - 48
        assert label.toolTip() == str(long_path)
    finally:
        long.window.close()


def test_labels_never_treat_text_as_markup(harness: Harness) -> None:
    names = ("stageHeadline", "stageDetail", "folderPath")
    labels = [harness.window.findChild(QLabel, name) for name in names]

    assert all(label.textFormat() == Qt.TextFormat.PlainText for label in labels)


def test_offering_files_tells_user_to_pick_them_up_on_the_phone(harness: Harness, tmp_path: Path) -> None:
    files = [tmp_path / "a.pdf", tmp_path / "b.pdf"]

    harness.window.offer_files(files)

    assert harness.service.offered_files == files
    assert harness.headline == "휴대폰에서 받아 주세요"
    assert "2개" in harness.window.stage_view.detail


def test_offering_nothing_does_nothing(harness: Harness) -> None:
    harness.window.offer_files([])

    assert harness.window.stage_view.show_qr


def test_phone_taking_a_file_is_shown_as_sent(harness: Harness) -> None:
    harness.send(FileSent("보고서.pdf", 10, PHONE))

    assert harness.headline == "휴대폰으로 보냈습니다"
    assert harness.window.stage_view.detail == "보고서.pdf"
    assert harness.window.stage_view.state == "done"


def test_text_from_phone_is_copied_and_announced(harness: Harness) -> None:
    harness.send(TextReceived("휴대폰에서 온 글자", PHONE))

    assert QGuiApplication.clipboard().text() == "휴대폰에서 온 글자"
    assert harness.headline == "글자를 받았습니다"
    assert harness.summaries == ["글자를 받았습니다"]


def test_sending_copied_text_offers_it_to_the_phone(harness: Harness) -> None:
    QGuiApplication.clipboard().setText("PC에서 복사한 글자")

    harness.window.send_clipboard_text()

    assert harness.service.offered_texts == ["PC에서 복사한 글자"]
    assert harness.headline == "휴대폰에서 받아 주세요"


def test_sending_copied_text_with_nothing_copied_explains_why(harness: Harness) -> None:
    QGuiApplication.clipboard().clear()

    harness.window.send_clipboard_text()

    assert harness.service.offered_texts == []
    assert "복사한 글자가 없습니다" in harness.window.stage_view.detail


def test_change_folder_stays_locked_between_files_of_one_batch(harness: Harness) -> None:
    harness.receive_file("a.png")  # 한 장이 끝났지만 다음 장이 곧 올 수 있는 틈

    harness.window.refresh()

    assert not harness.window.findChild(QPushButton, "changeFolder").isEnabled()

    harness.settle()

    assert harness.window.findChild(QPushButton, "changeFolder").isEnabled()


def test_long_file_name_is_shortened_to_fit_the_window(harness: Harness) -> None:
    name = "KakaoTalk_Photo_2026-01-01-12-00-00_001_아주_긴_이름의_사진.jpeg"

    harness.send(TransferStarted("a", name, 1000, PHONE))

    shown = harness.window.stage_view.detail.splitlines()[0]
    assert "…" in shown and shown.endswith(".jpeg")


def test_offering_more_files_than_the_phone_list_holds_says_so(harness: Harness, tmp_path: Path) -> None:
    harness.service.offer_count = 60

    harness.window.offer_files([tmp_path / f"{n}.pdf" for n in range(60)])

    assert "50개" in harness.window.stage_view.detail
    assert "60개를 올려" not in harness.window.stage_view.detail


def test_offering_a_mix_says_how_many_were_left_out(harness: Harness, tmp_path: Path) -> None:
    harness.service.offer_count = 3

    harness.window.offer_files([tmp_path / f"{n}" for n in range(5)])

    assert "3개" in harness.window.stage_view.detail
    assert "2개" in harness.window.stage_view.detail


def test_text_with_hidden_direction_marks_is_not_copied_automatically(harness: Harness) -> None:
    harness.send(TextReceived("입금 계좌 ‮1234", PHONE))

    assert QGuiApplication.clipboard().text() != "입금 계좌 ‮1234"
    assert harness.window.stage_view.primary_label == "글자 복사"
