"""assets 폴더의 아이콘 파일(hwik.png, hwik.ico)을 hwik.tray.draw_icon 그림으로 다시 만든다.

실행: PYTHONPATH=src python scripts/make_icon_files.py
"""
from __future__ import annotations

import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtWidgets import QApplication

from hwik.tray import ICON_SIZES, draw_icon

ASSETS = Path(__file__).resolve().parent.parent / "assets"
PNG_SIZE = 256


def png_bytes(size: int) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    draw_icon(size).save(buffer, "PNG")
    return bytes(buffer.data())


def ico_bytes(sizes: tuple[int, ...]) -> bytes:
    """크기마다 PNG로 담은 ICO 파일. 256은 칸에 0으로 적는 것이 형식의 약속이다."""
    images = [png_bytes(size) for size in sizes]
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = len(header) + 16 * len(sizes)
    entries = b""
    for size, image in zip(sizes, images):
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(image), offset)
        offset += len(image)
    return header + entries + b"".join(images)


def main() -> None:
    app = QApplication([])  # 그림을 그리려면 필요하다
    ASSETS.mkdir(exist_ok=True)
    (ASSETS / "hwik.png").write_bytes(png_bytes(PNG_SIZE))
    (ASSETS / "hwik.ico").write_bytes(ico_bytes(ICON_SIZES))
    del app


if __name__ == "__main__":
    main()
