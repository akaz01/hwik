"""앱 창: QR을 보여 주고, 주고받는 상태를 크게 보여 준다. 창을 닫으면 연결이 꺼진다."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from hwik import DISPLAY_NAME, batch, clipboard, settings
from hwik.batch import Batch
from hwik.core.errors import TransferError
from hwik.core.events import FileSent, TextReceived, TransferEvent
from hwik.core.outbox import MAX_ITEMS
from hwik.service import TransferService
from hwik.settings import Settings
from hwik.ui import dialogs, theme
from hwik.ui.bridge import EventBridge
from hwik.ui.stage import QR_CARD_SIZE, Stage, StageView, render_qr
from hwik.ui.toggle import Toggle

logger = logging.getLogger(__name__)

WINDOW_WIDTH = 280
WINDOW_HEIGHT = 480
PANEL_MARGIN = 16
PANEL_WIDTH = WINDOW_WIDTH - PANEL_MARGIN * 2
DETAIL_FONT_SIZE = 12  # 상태판 설명 글자(ui/stage.py와 같은 값)
DETAIL_WIDTH = WINDOW_WIDTH - 48  # 상태판 좌우 여백과 약간의 여유를 뺀 폭
DIRECTION_MARKS = frozenset("‎‏‪‫‬‭‮⁦⁧⁨⁩")
REFRESH_MS = 250
CARD_PADDING = 12
TEXT_PREVIEW_CHARS = 80
OPEN_FOLDER = "폴더 열기"
OPEN_SHORT = "열기"
COPY_TEXT = "글자 복사"
SHOW_QR = "QR 다시 보기"
RETRY = "다시 시도"
CONNECTED = "휴대폰과 연결됨"
PICK_UP_HEADLINE = "휴대폰에서 받아 주세요"
WAITING_VIEW = StageView(
    state="waiting",
    status="휴대폰을 기다리는 중",
    headline="QR을 찍어 주세요",
    detail="같은 와이파이나 핫스팟에서 찍어 주세요.",
    show_qr=True,
)


def _has_hidden_marks(text: str) -> bool:
    """글자 방향을 뒤집는 표시나 제어 글자(줄바꿈·탭 제외)가 들어 있는지."""
    return any(char in DIRECTION_MARKS or (ord(char) < 32 and char not in "\n\r\t") or ord(char) == 127 for char in text)


def _fit_first_line(detail: str) -> str:
    """받는 중 설명의 첫 줄(파일 이름)이 창보다 길면 가운데를 줄인다. 확장자가 보이게 끝은 남긴다."""
    first, separator, rest = detail.partition("\n")
    metrics = QFontMetrics(theme.font(DETAIL_FONT_SIZE))
    return metrics.elidedText(first, Qt.TextElideMode.ElideMiddle, DETAIL_WIDTH) + separator + rest


class MainWindow(QWidget):
    batch_settled = Signal(str)  # 무언가를 다 받았을 때 한 줄 요약(시계 옆 알림용)

    def __init__(
        self,
        current: Settings,
        service: TransferService | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__()
        self._settings = current
        self._clock = clock
        self._bridge = EventBridge(self)
        self._bridge.received.connect(self._on_event)
        self._service = service or TransferService(self._bridge)
        self._batch = Batch()
        self._result_shown = True  # 지금 묶음의 결과를 이미 보여 줬는지
        self._primary_action: Callable[[], None] = self.open_save_folder
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.refresh)

        self.setObjectName("window")
        self.setWindowTitle(DISPLAY_NAME)
        self.setFixedSize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setStyleSheet(theme.STYLE_SHEET)
        self.setAcceptDrops(True)  # 파일을 창에 끌어다 놓으면 휴대폰으로 보낸다
        self._stage = Stage(self)
        self._stage.primary_clicked.connect(lambda: self._primary_action())
        self._stage.secondary_clicked.connect(self.show_qr)
        self._folder_path = QLabel(objectName="folderPath")  # 받은 파일이 저장되는 전체 경로
        self._folder_path.setFont(theme.font(11, QFont.Weight.Medium))
        self._folder_path.setTextFormat(Qt.TextFormat.PlainText)
        self._change_button = QPushButton("바꾸기", objectName="changeFolder")
        self._change_button.clicked.connect(self._choose_folder)
        self._copy_box = Toggle("받으면 바로 붙여넣을 수 있게 복사")
        self._copy_box.setFont(theme.font(12, QFont.Weight.DemiBold))
        self._copy_box.setChecked(current.copy_to_clipboard)
        self._copy_box.toggled.connect(self._on_copy_toggled)
        self._build_layout()
        self._show_folder_name()
        self._stage.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._stage.setFocus()  # 창을 열자마자 단추에 초점 테두리가 켜져 있지 않게
        for button in self.findChildren(QPushButton):
            button.setCursor(Qt.CursorShape.PointingHandCursor)  # 누를 수 있는 곳임을 커서로도 알린다

    def _build_layout(self) -> None:
        panel = QVBoxLayout()
        panel.setContentsMargins(PANEL_MARGIN, 14, PANEL_MARGIN, 14)
        panel.setSpacing(10)
        panel.addLayout(self._build_send_row())
        panel.addWidget(self._build_settings_card())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._stage, 1)
        layout.addLayout(panel)

    def _build_send_row(self) -> QHBoxLayout:
        send_files = QPushButton("파일 보내기", objectName="sendFiles")
        send_files.clicked.connect(self._choose_files_to_send)
        send_text = QPushButton("글자 보내기", objectName="sendText")
        send_text.clicked.connect(self.send_clipboard_text)
        send_files.setToolTip("파일을 골라 휴대폰으로 보냅니다. 파일을 이 창에 끌어다 놓아도 됩니다")
        send_text.setToolTip("PC에서 복사(Ctrl+C)해 둔 글자를 휴대폰으로 보냅니다")
        row = QHBoxLayout()
        row.setSpacing(6)
        for button in (send_files, send_text):
            button.setFont(theme.font(12, QFont.Weight.DemiBold))
            row.addWidget(button, 1)
        return row

    def _build_settings_card(self) -> QFrame:
        """받는 곳과 복사 설정을 흰 카드 하나로 묶는다."""
        divider = QFrame(objectName="divider")
        divider.setFixedHeight(1)
        card = QFrame(objectName="card")
        box = QVBoxLayout(card)
        box.setContentsMargins(CARD_PADDING, 10, CARD_PADDING, 9)
        box.setSpacing(0)
        box.addLayout(self._build_folder_row())
        box.addSpacing(5)
        box.addWidget(self._folder_path)
        box.addSpacing(10)
        box.addWidget(divider)
        box.addSpacing(7)
        box.addWidget(self._copy_box)
        return card

    def _build_folder_row(self) -> QHBoxLayout:
        caption = QLabel("받는 곳", objectName="cardTitle")
        caption.setFont(theme.font(12, QFont.Weight.DemiBold))
        open_button = QPushButton(OPEN_SHORT, objectName="openFolder")
        open_button.setToolTip("받은 파일이 있는 폴더를 엽니다")
        self._change_button.setToolTip("받은 파일을 둘 폴더를 바꿉니다")
        open_button.clicked.connect(self.open_save_folder)
        for button in (open_button, self._change_button):
            button.setFont(theme.font(11, QFont.Weight.DemiBold))
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(caption, 1)
        row.addWidget(open_button)
        row.addWidget(self._change_button)
        return row

    # ── 시험과 다른 부품이 들여다보는 것 ──

    @property
    def bridge(self) -> EventBridge:
        return self._bridge

    @property
    def stage_view(self) -> StageView:
        return self._stage.view

    @property
    def save_dir(self) -> str:
        return self._settings.save_dir

    # ── 연결 켜기·끄기 ──

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt가 정한 이름
        super().showEvent(event)
        if not self._service.is_running and not event.spontaneous():  # 최소화했다 되돌릴 때는 다시 켜지 않는다
            self._connect()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt가 정한 이름
        self.disconnect_phone()
        super().closeEvent(event)

    def disconnect_phone(self) -> None:
        self._timer.stop()
        self._service.stop()
        self._forget_connection()

    def show_qr(self) -> None:
        """QR 화면으로 돌아간다. 연결이 꺼져 있으면 새 암호로 다시 켠다."""
        if self._service.is_running:
            self._stage.set_view(WAITING_VIEW)
        else:
            self._connect()

    def _forget_connection(self) -> None:
        """지난 연결에서 늦게 도착하는 알림을 가려낼 수 있게 번호를 올리고, 받던 묶음을 비운다."""
        self._bridge.generation += 1
        self._batch, self._result_shown = Batch(), True
        self._change_button.setEnabled(True)

    def _connect(self) -> None:
        self._timer.stop()
        self._service.stop()
        self._forget_connection()
        try:
            connection = self._service.start(Path(self._settings.save_dir))
        except TransferError as err:
            self._stage.set_view(
                StageView(
                    state="failed",
                    status="연결 안 됨",
                    headline="연결하지 못했습니다",
                    detail=str(err),
                    secondary_label=RETRY,
                )
            )
            return
        self._stage.set_qr(render_qr(connection.url, QR_CARD_SIZE - 18, self.devicePixelRatioF()))
        self._stage.set_view(WAITING_VIEW)
        self._timer.start()

    # ── 휴대폰에서 받기 ──

    def _on_event(self, generation: int, event: TransferEvent) -> None:
        if generation != self._bridge.generation or not self._service.is_running:
            return  # 창을 닫기 전의 연결에서 늦게 도착한 알림
        if isinstance(event, FileSent):
            self._show_sent(event)
        elif isinstance(event, TextReceived):
            self._show_text(event)
        else:
            changed = batch.apply(self._batch, event, self._clock())
            if changed is self._batch:
                return  # 묶음에 영향을 주지 않는 알림
            self._batch, self._result_shown = changed, False
            self.refresh()

    def refresh(self) -> None:
        now = self._clock()
        self._change_button.setEnabled(not self._is_receiving(now))  # 받는 도중에는 받는 곳을 바꾸지 못한다
        if self._batch.is_running:
            self._stage.set_view(
                StageView(
                    state="receiving",
                    status="휴대폰에서 받는 중",
                    headline=batch.headline(self._batch),
                    detail=_fit_first_line(batch.detail(self._batch, now)),
                    progress=self._batch.progress,
                )
            )
        elif not self._result_shown and self._batch.is_settled(now):
            self._result_shown = True
            self._show_result()

    def _is_receiving(self, now: float) -> bool:
        """받는 중이거나, 한 묶음의 파일과 파일 사이 틈인지(다음 파일이 곧 올 수 있다)."""
        between_files = not self._batch.is_empty and not self._batch.is_settled(now)
        return self._batch.is_running or between_files

    def _show_result(self) -> None:
        saved = self._batch.saved_paths
        headline = batch.headline(self._batch)
        copied = clipboard.copy_received(saved) if self._settings.copy_to_clipboard else ""
        self._primary_action = self.open_save_folder
        self._stage.set_view(
            StageView(
                state="done" if saved else "failed",
                status=CONNECTED,
                headline=headline,
                detail=self._batch.last_failure_message or copied,
                primary_label=OPEN_FOLDER if saved else "",
                secondary_label=SHOW_QR,
            )
        )
        self.batch_settled.emit(headline.replace("\n", " "))

    def _show_text(self, event: TextReceived) -> None:
        preview = " ".join(event.text.split())[:TEXT_PREVIEW_CHARS]
        # 눈에 안 보이는 조종 글자가 섞인 글은 보이는 것과 붙여넣어지는 것이 다를 수 있어, 자동으로 복사하지 않는다.
        auto_copy = self._settings.copy_to_clipboard and not _has_hidden_marks(event.text)
        self._primary_action = lambda: clipboard.copy_text(event.text)
        headline = "글자를 받았습니다"
        self._stage.set_view(
            StageView(
                state="done",
                status=CONNECTED,
                headline=headline,
                detail=f"{clipboard.copy_text(event.text)}\n{preview}" if auto_copy else preview,
                primary_label="" if auto_copy else COPY_TEXT,
                secondary_label=SHOW_QR,
            )
        )
        self.batch_settled.emit(headline.replace("\n", " "))

    # ── 휴대폰으로 보내기 ──

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 - Qt가 정한 이름
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 - Qt가 정한 이름
        self.offer_files([Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()])

    def offer_files(self, paths: Sequence[Path]) -> None:
        """휴대폰이 받아 갈 수 있게 파일을 올려 둔다."""
        if not paths:
            return
        try:
            count = self._service.offer_files(paths)
        except TransferError as err:
            self._show_pick_up(str(err), "보낼 수 없습니다")
            return
        if count == 0:
            self._show_pick_up("폴더는 보낼 수 없습니다. 파일을 골라 주세요.", "보낼 수 없습니다")
            return
        if count > MAX_ITEMS:
            note = f"한 번에 {MAX_ITEMS}개까지 올릴 수 있어 마지막 {MAX_ITEMS}개만 올렸습니다."
        elif count < len(paths):
            note = f"파일 {count}개를 올려 두었습니다. 보낼 수 없는 {len(paths) - count}개는 뺐습니다."
        else:
            note = f"파일 {count}개를 올려 두었습니다."
        self._show_pick_up(f"{note} 휴대폰 화면에서 '받기'를 눌러 주세요.")

    def send_clipboard_text(self) -> None:
        """PC에서 복사해 둔 글자를 휴대폰이 가져갈 수 있게 올려 둔다."""
        text = QGuiApplication.clipboard().text()
        if not text.strip():
            self._show_pick_up("복사한 글자가 없습니다. 글자를 복사(Ctrl+C)한 뒤 다시 눌러 주세요.", "보낼 글자가 없습니다")
            return
        try:
            self._service.offer_text(text)
        except TransferError as err:
            self._show_pick_up(str(err), "보낼 수 없습니다")
            return
        self._show_pick_up("복사한 글자를 올려 두었습니다. 휴대폰 화면에서 '복사'를 눌러 주세요.")

    def _show_pick_up(self, detail: str, headline: str = PICK_UP_HEADLINE) -> None:
        self._stage.set_view(
            StageView(state="waiting", status="휴대폰으로 보내기", headline=headline, detail=detail, secondary_label=SHOW_QR)
        )

    def _show_sent(self, event: FileSent) -> None:
        self._stage.set_view(
            StageView(
                state="done",
                status=CONNECTED,
                headline="휴대폰으로 보냈습니다",
                detail=event.name,
                secondary_label=SHOW_QR,
            )
        )

    def _choose_files_to_send(self) -> None:
        chosen, _ = QFileDialog.getOpenFileNames(self, "휴대폰으로 보낼 파일")
        self.offer_files([Path(name) for name in chosen])

    # ── 받는 곳·설정 ──

    def open_save_folder(self) -> None:
        folder = Path(self._settings.save_dir)
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as err:
            logger.warning("받는 폴더를 만들지 못했습니다: %s", type(err).__name__)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _choose_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "받은 파일을 둘 폴더", self._settings.save_dir)
        if not chosen or Path(chosen) == Path(self._settings.save_dir):
            return
        if self._is_receiving(self._clock()):  # 폴더를 고르는 사이에 휴대폰이 보내기 시작했다: 끊지 않는다
            dialogs.inform(self, "지금 파일을 받고 있습니다. 다 받은 뒤에 다시 바꿔 주세요.")
            return
        folder = str(Path(chosen))
        if not settings.is_usable_save_dir(folder):
            dialogs.warn(self, "이 위치는 받는 곳으로 쓸 수 없습니다.\n드라이브 맨 위나 네트워크 위치가 아닌 폴더를 골라 주세요.")
            return
        self._update_settings(replace(self._settings, save_dir=folder))
        self._show_folder_name()
        if self._service.is_running:
            self._connect()  # 받는 곳이 바뀌면 새 주소로 다시 연결한다(받는 도중에는 단추가 잠겨 있다)

    def _on_copy_toggled(self, checked: bool) -> None:
        self._update_settings(replace(self._settings, copy_to_clipboard=checked))

    def _update_settings(self, changed: Settings) -> None:
        self._settings = changed
        try:
            settings.save(changed)
        except OSError as err:
            logger.warning("설정을 저장하지 못했습니다: %s", type(err).__name__)

    def _show_folder_name(self) -> None:
        folder = Path(self._settings.save_dir)
        path_metrics = QFontMetrics(self._folder_path.font())
        room = PANEL_WIDTH - CARD_PADDING * 2 - 2
        # 길면 앞쪽을 줄인다: 끝에 있는 실제 폴더 이름이 온전히 보이는 편이 알아보기 쉽다.
        shown = settings.display_path(str(folder))
        self._folder_path.setText(path_metrics.elidedText(shown, Qt.TextElideMode.ElideLeft, room))
        self._folder_path.setToolTip(str(folder))
