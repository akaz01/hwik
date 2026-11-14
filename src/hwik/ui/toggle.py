"""켜고 끄는 스위치: 왼쪽에 글자, 오른쪽에 알약 모양 스위치. 줄 어디를 눌러도 바뀐다."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QCheckBox, QWidget

from hwik.ui import theme

SWITCH_WIDTH = 36
SWITCH_HEIGHT = 20
KNOB_MARGIN = 3
TEXT_GAP = 10
OFF_COLOR = "#7f89b0"  # 흰 카드 위에서 3:1 이상으로 보이는 회색
FOCUS_PEN_WIDTH = 2


class Toggle(QCheckBox):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt가 정한 이름
        text_width = self.fontMetrics().horizontalAdvance(self.text())
        height = max(self.fontMetrics().height(), SWITCH_HEIGHT) + FOCUS_PEN_WIDTH * 2
        return QSize(text_width + TEXT_GAP + SWITCH_WIDTH + FOCUS_PEN_WIDTH, height)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt가 정한 이름
        return self.sizeHint()

    def hitButton(self, pos: QPoint) -> bool:  # noqa: N802 - Qt가 정한 이름
        return self.rect().contains(pos)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt가 정한 이름
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor(theme.INK if self.isEnabled() else theme.DISABLED_TEXT))
        painter.setFont(self.font())
        text_area = self.rect().adjusted(0, 0, -(SWITCH_WIDTH + TEXT_GAP), 0)
        painter.drawText(text_area, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())

        track = QRectF(
            self.width() - SWITCH_WIDTH - FOCUS_PEN_WIDTH,
            (self.height() - SWITCH_HEIGHT) / 2,
            SWITCH_WIDTH,
            SWITCH_HEIGHT,
        )
        if self.hasFocus():  # 글쇠로 옮겨 왔을 때 어디에 있는지 보이게
            painter.setPen(QColor(theme.INK))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            outline = track.adjusted(-1.5, -1.5, 1.5, 1.5)
            painter.drawRoundedRect(outline, outline.height() / 2, outline.height() / 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.COBALT if self.isChecked() else OFF_COLOR))
        painter.drawRoundedRect(track, SWITCH_HEIGHT / 2, SWITCH_HEIGHT / 2)
        knob_size = SWITCH_HEIGHT - KNOB_MARGIN * 2
        knob_x = track.right() - KNOB_MARGIN - knob_size if self.isChecked() else track.left() + KNOB_MARGIN
        painter.setBrush(QColor(theme.WHITE))
        painter.drawEllipse(QRectF(knob_x, track.top() + KNOB_MARGIN, knob_size, knob_size))
        painter.end()
