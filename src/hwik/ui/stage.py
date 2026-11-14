"""상태판: 창 위쪽의 큰 색 면. QR을 보여 주고, 받는 동안 아래에서 위로 색이 차오른다."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import segno
from PySide6.QtCore import QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPaintEvent, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from hwik.ui import theme

StageState = Literal["waiting", "receiving", "done", "failed"]

QR_CARD_SIZE = 172
QR_QUIET_MODULES = 2  # QR 둘레의 흰 여백(칸 수)
FILL_ANIMATION_MS = 220
_BACKGROUNDS: dict[str, str] = {
    "waiting": theme.COBALT,
    "receiving": theme.COBALT,
    "done": theme.DONE,
    "failed": theme.FAILED,
}


@dataclass(frozen=True)
class StageView:
    """상태판이 지금 보여 줄 내용."""

    state: StageState
    status: str
    headline: str
    detail: str = ""
    progress: float = 0.0
    show_qr: bool = False
    primary_label: str = ""  # 흰 단추(예: 폴더 열기). 비면 숨긴다
    secondary_label: str = ""  # 테두리 단추(예: QR 다시 보기). 비면 숨긴다


def render_qr(text: str, size: int, pixel_ratio: float) -> QPixmap:
    """QR을 그림으로 만든다. 칸 크기를 정수로 맞춰 또렷하게 그린다."""
    matrix = tuple(segno.make(text, error="m").matrix)
    modules = len(matrix) + QR_QUIET_MODULES * 2
    device_size = int(size * pixel_ratio)
    cell = max(device_size // modules, 1)
    offset = (device_size - cell * len(matrix)) // 2
    pixmap = QPixmap(device_size, device_size)
    pixmap.fill(QColor(theme.WHITE))
    painter = QPainter(pixmap)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(theme.INK))
    for row_index, row in enumerate(matrix):
        for column_index, dark in enumerate(row):
            if dark:
                painter.drawRect(offset + column_index * cell, offset + row_index * cell, cell, cell)
    painter.end()
    pixmap.setDevicePixelRatio(pixel_ratio)
    return pixmap


class Stage(QWidget):
    primary_clicked = Signal()
    secondary_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state: StageState = "waiting"
        self._shown_progress = 0.0
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(FILL_ANIMATION_MS)
        self._animation.valueChanged.connect(self._on_progress_step)

        self._status = QLabel(objectName="stageStatus")
        self._status.setFont(theme.font(12, QFont.Weight.DemiBold))
        self._headline = QLabel(objectName="stageHeadline")
        self._headline.setFont(theme.font(22, QFont.Weight.Bold))
        self._headline.setWordWrap(True)  # 제목은 한 줄로 쓰지만, 드물게 길어지면 잘리지 않고 넘어가게
        self._detail = QLabel(objectName="stageDetail")
        self._detail.setFont(theme.font(12))
        self._detail.setWordWrap(True)
        self._qr = QLabel(objectName="qrCard")
        self._qr.setFixedSize(QR_CARD_SIZE, QR_CARD_SIZE)
        self._qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._primary = QPushButton(objectName="stagePrimary")
        self._primary.setFont(theme.font(13, QFont.Weight.Bold))
        self._primary.clicked.connect(self.primary_clicked)
        self._secondary = QPushButton(objectName="stageGhost")
        self._secondary.setFont(theme.font(12, QFont.Weight.DemiBold))
        self._secondary.clicked.connect(self.secondary_clicked)
        for label in (self._status, self._headline, self._detail):
            # 파일 이름이나 휴대폰이 보낸 글자가 들어가므로 서식(HTML)으로 해석하지 않게 한다.
            label.setTextFormat(Qt.TextFormat.PlainText)
        self._view = StageView(state="waiting", status="", headline="")
        self._build_layout()

    def _build_layout(self) -> None:
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self._primary)
        buttons.addWidget(self._secondary)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(0)
        layout.addWidget(self._status)
        layout.addStretch(1)
        layout.addWidget(self._headline)
        layout.addSpacing(6)
        layout.addWidget(self._detail)
        layout.addSpacing(14)
        layout.addWidget(self._qr, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addLayout(buttons)

    def set_qr(self, pixmap: QPixmap) -> None:
        self._qr.setPixmap(pixmap)

    @property
    def view(self) -> StageView:
        return self._view

    def set_view(self, view: StageView) -> None:
        self._view = view
        self._state = view.state
        self._status.setText(f"●  {view.status}")
        self._headline.setText(view.headline)
        self._detail.setText(view.detail)
        self._detail.setVisible(bool(view.detail))
        self._qr.setVisible(view.show_qr)
        # QR 화면은 QR이 주인공이라 가운데에 모으고, 글을 읽는 나머지 화면은 왼쪽에서 시작한다.
        side = Qt.AlignmentFlag.AlignHCenter if view.show_qr else Qt.AlignmentFlag.AlignLeft
        for label in (self._status, self._headline, self._detail):
            label.setAlignment(side | Qt.AlignmentFlag.AlignVCenter)
        self._primary.setText(view.primary_label)
        self._primary.setVisible(bool(view.primary_label))
        self._secondary.setText(view.secondary_label)
        self._secondary.setVisible(bool(view.secondary_label))
        self._animate_to(view.progress if view.state == "receiving" else 0.0)
        self.update()

    def _animate_to(self, progress: float) -> None:
        self._animation.stop()
        if progress <= self._shown_progress:  # 새로 시작하거나 끝났을 때는 바로 맞춘다
            self._shown_progress = progress
            return
        self._animation.setStartValue(self._shown_progress)
        self._animation.setEndValue(progress)
        self._animation.start()

    def _on_progress_step(self, value: float) -> None:
        self._shown_progress = float(value)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt가 정한 이름
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect())
        shape = QPainterPath()
        # 위쪽은 창 끝까지 닿고 아래쪽 모서리만 둥글게: 위로 한 칸 늘려 그려서 윗모서리를 창 밖으로 보낸다.
        shape.addRoundedRect(area.adjusted(0, -theme.STAGE_RADIUS, 0, 0), theme.STAGE_RADIUS, theme.STAGE_RADIUS)
        painter.setClipPath(shape)
        painter.fillRect(area, QColor(_BACKGROUNDS[self._state]))
        if self._state == "receiving" and self._shown_progress > 0:
            filled = area.height() * self._shown_progress
            painter.fillRect(QRectF(0, area.height() - filled, area.width(), filled), QColor(theme.DEEP))
        painter.end()
