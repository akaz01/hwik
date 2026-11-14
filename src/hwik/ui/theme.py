"""PC 화면의 색·글꼴. 휴대폰 화면(web/app.css)과 같은 값을 쓴다.

색은 글자 대비 4.5:1(조작 부품의 테두리와 초점 표시는 3:1) 이상이 되도록 골랐다.
"""
from __future__ import annotations

from PySide6.QtGui import QFont

INK = "#0b1026"
PAPER = "#f1f3fa"
COBALT = "#2340f0"  # 상태판: 기다리는 중. 밝은 바탕 위의 조작 글자·초점 표시
DEEP = "#101a6b"  # 상태판: 차오르는 색(받는 중)
DONE = "#07704c"  # 상태판: 다 받음
FAILED = "#b92a26"  # 상태판: 문제 있음
LINE = "#d3d8ea"  # 구분선(조작 부품이 아닌 곳)
MUTED = "#5a6282"
WHITE = "#ffffff"
SOFT_WHITE = "rgba(255, 255, 255, 224)"  # 상태판 위의 보조 글자
TINT = "#dde2f9"  # 보내기 단추 바탕(파랑을 옅게)
TINT_HOVER = "#cbd3f6"
QUIET_HOVER = "#e2e6f5"
DISABLED_TEXT = "#8f97b3"

FONT_FAMILIES = ["Pretendard", "Malgun Gothic"]
STAGE_RADIUS = 22


def font(pixel_size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    result = QFont()
    result.setFamilies(FONT_FAMILIES)
    result.setPixelSize(pixel_size)
    result.setWeight(weight)
    return result


# 단추는 세 단계로 나눈다: 상태판의 흰 단추(가장 중요) > 보내기 단추(옅은 파랑) > 받는 곳 단추(글자만).
# 테두리 굵기를 늘 같게 두고 색만 바꿔서, 초점이 옮겨 가도 단추 크기가 변하지 않게 한다.
STYLE_SHEET = f"""
QWidget#window {{ background: {PAPER}; }}
QLabel {{ color: {INK}; }}
QLabel#stageStatus {{ color: {SOFT_WHITE}; }}
QLabel#stageHeadline {{ color: {WHITE}; }}
QLabel#stageDetail {{ color: {SOFT_WHITE}; }}
QLabel#qrCard {{ background: {WHITE}; border-radius: 14px; }}
QLabel#caption {{ color: {MUTED}; }}
QLabel#folderPath {{ color: {COBALT}; }}
QFrame#card {{ background: {WHITE}; border-radius: 14px; }}
QFrame#divider {{ background: {LINE}; }}

QPushButton {{ border: 2px solid transparent; border-radius: 9px; padding: 5px 8px; }}

QPushButton#stagePrimary {{ padding: 7px 16px; border-radius: 11px; background: {WHITE}; color: {INK}; }}
QPushButton#stagePrimary:hover {{ background: #e7ebff; }}
QPushButton#stagePrimary:pressed {{ background: #d3daff; }}
QPushButton#stagePrimary:focus {{ border-color: {INK}; }}
QPushButton#stageGhost {{
    padding: 7px 14px; border-radius: 11px; background: rgba(255, 255, 255, 46); color: {WHITE};
}}
QPushButton#stageGhost:hover {{ background: rgba(255, 255, 255, 76); }}
QPushButton#stageGhost:pressed {{ background: rgba(255, 255, 255, 30); }}
QPushButton#stageGhost:focus {{ border-color: {WHITE}; }}

QPushButton#sendFiles, QPushButton#sendText {{ padding: 7px 8px; background: {TINT}; color: {COBALT}; }}
QPushButton#sendFiles:hover, QPushButton#sendText:hover {{ background: {TINT_HOVER}; }}
QPushButton#sendFiles:pressed, QPushButton#sendText:pressed {{ background: #b9c3f2; }}

QPushButton#openFolder, QPushButton#changeFolder {{
    padding: 2px 10px; border-radius: 8px; background: {TINT}; color: {COBALT};
}}
QPushButton#openFolder:hover, QPushButton#changeFolder:hover {{ background: {TINT_HOVER}; }}
QPushButton#openFolder:pressed, QPushButton#changeFolder:pressed {{ background: #b9c3f2; }}
QLabel#cardTitle {{ color: {INK}; }}

QPushButton#sendFiles:focus, QPushButton#sendText:focus,
QPushButton#openFolder:focus, QPushButton#changeFolder:focus {{ border-color: {COBALT}; }}
QPushButton:disabled {{ color: {DISABLED_TEXT}; }}

QCheckBox {{ color: {INK}; spacing: 6px; }}
"""
