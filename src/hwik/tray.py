"""시계 옆 아이콘과 메뉴."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from hwik import DISPLAY_NAME
from hwik.ui import theme

ICON_GRID = 64  # 아이콘을 그릴 때 기준으로 삼는 칸 수
ICON_SIZES = (16, 20, 24, 32, 48, 64, 256)
NOTICE_MS = 5000
DETAIL_FROM_SIZE = 32  # 이보다 작은 아이콘은 단순하게 그린다
ICON_LIGHT = "#4d6cff"
ICON_DEEP = "#1226c0"


def draw_icon(size: int) -> QPixmap:
    """깊은 파란 바탕 위로 흰 것이 "휙" 날아가는 모습: 둥근 머리와, 뒤로 갈수록 가늘고 옅어지는 꼬리."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / ICON_GRID, size / ICON_GRID)
    painter.setPen(Qt.PenStyle.NoPen)
    _draw_background(painter)
    if size >= DETAIL_FROM_SIZE:
        _draw_echo(painter)  # 작은 크기에서는 뭉개지므로 그리지 않는다
    _draw_comet(painter, fade_tail=size >= DETAIL_FROM_SIZE)
    painter.end()
    return pixmap


def _draw_background(painter: QPainter) -> None:
    shade = QLinearGradient(8, 2, 56, 62)  # 왼쪽 위는 밝게, 오른쪽 아래는 깊게
    shade.setColorAt(0.0, QColor(ICON_LIGHT))
    shade.setColorAt(1.0, QColor(ICON_DEEP))
    background = QPainterPath()
    background.addRoundedRect(QRectF(2, 2, ICON_GRID - 4, ICON_GRID - 4), 16, 16)
    painter.fillPath(background, shade)


def _draw_comet(painter: QPainter, fade_tail: bool) -> None:
    tail = QPainterPath()  # 왼쪽 아래 뾰족한 끝에서 시작해 휘어 오르며 머리 폭까지 넓어진다
    tail.moveTo(36.3, 14.3)
    tail.quadTo(15, 21, 9, 55)
    tail.quadTo(27, 36, 49.7, 27.7)
    tail.closeSubpath()
    fill = QLinearGradient(9, 55, 40, 22)
    fill.setColorAt(0.0, QColor(255, 255, 255, 120 if fade_tail else 255))
    fill.setColorAt(1.0, QColor(255, 255, 255, 255))
    painter.fillPath(tail, fill)
    painter.setBrush(QColor(theme.WHITE))
    painter.drawEllipse(QRectF(33.5, 11.5, 19, 19))  # 날아가는 것


def _draw_echo(painter: QPainter) -> None:
    echo = QPainterPath()  # 머리 아래쪽을 따라가는 옅은 보조 꼬리(속도감)
    echo.moveTo(55, 36)
    echo.quadTo(38, 39, 27, 56)
    echo.quadTo(41, 46, 56, 42)
    echo.closeSubpath()
    painter.fillPath(echo, QColor(255, 255, 255, 95))


def make_icon() -> QIcon:
    """작은 크기에서도 또렷하게 보이도록 크기마다 따로 그려 넣는다."""
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(draw_icon(size))
    return icon


class Tray(QSystemTrayIcon):
    open_requested = Signal()
    folder_requested = Signal()
    quit_requested = Signal()

    def __init__(self) -> None:
        super().__init__(make_icon())
        self.setToolTip(DISPLAY_NAME)
        self._menu = QMenu()
        self._menu.addAction("휴대폰 연결 열기", self.open_requested.emit)
        self._menu.addAction("받은 폴더 열기", self.folder_requested.emit)
        self._menu.addSeparator()
        self._menu.addAction("끝내기", self.quit_requested.emit)
        self.setContextMenu(self._menu)
        self.activated.connect(self._on_activated)
        self.messageClicked.connect(self.folder_requested.emit)

    def notify(self, summary: str) -> None:
        self.showMessage(DISPLAY_NAME, summary, QSystemTrayIcon.MessageIcon.NoIcon, NOTICE_MS)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.open_requested.emit()
