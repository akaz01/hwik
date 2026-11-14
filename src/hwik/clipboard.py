"""받은 파일과 글자를 바로 붙여넣을 수 있게 클립보드에 넣는다."""
from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtGui import QGuiApplication, QImage, QImageReader

logger = logging.getLogger(__name__)

# 그림 내용까지 넣는 형식. 받은 파일은 믿을 수 없으므로 파일 앞머리로 형식을 가려 그 해독기 하나로만, 크기를 제한해서 연다.
# 이름이 아니라 내용을 보는 이유: 아이폰은 이름이 .heic인데 내용은 JPG인 사진을 보내기도 한다.
_QT_FORMATS = {"png": b"png", "jpeg": b"jpeg"}
_HEIC_BRANDS = frozenset({b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1", b"msf1"})  # 아이폰 사진
_HEIC_PIXEL_FORMATS = {"RGB": QImage.Format.Format_RGB888, "RGBA": QImage.Format.Format_RGBA8888}
_SNIFF_BYTES = 12
MAX_IMAGE_FILE_BYTES = 40 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000  # 작게 압축됐지만 펼치면 메모리를 가득 채우는 그림을 막는다
ALLOCATION_LIMIT_MB = 128
COPIED_IMAGE = "복사했습니다. Ctrl+V로 바로 붙여넣을 수 있습니다."
COPIED_FILES = "복사했습니다. 폴더나 대화창에서 Ctrl+V로 붙여넣을 수 있습니다."
COPIED_TEXT = "복사했습니다. Ctrl+V로 붙여넣을 수 있습니다."


def copy_received(paths: Sequence[Path]) -> str:
    """받은 파일을 클립보드에 넣고 사용자에게 보여 줄 한 줄을 돌려준다. 넣을 것이 없으면 빈 글."""
    if not paths:
        return ""
    data = QMimeData()
    data.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
    image = _load_image(paths[0]) if len(paths) == 1 else None
    if image is not None:
        data.setImageData(image)
    QGuiApplication.clipboard().setMimeData(data)
    return COPIED_IMAGE if image is not None else COPIED_FILES


def copy_text(text: str) -> str:
    QGuiApplication.clipboard().setText(text)
    return COPIED_TEXT


def _sniff(path: Path) -> str | None:
    """파일 앞머리를 보고 그림 형식을 가린다: "png", "jpeg", "heic" 또는 None."""
    try:
        if path.stat().st_size > MAX_IMAGE_FILE_BYTES:
            return None
        with path.open("rb") as file:
            head = file.read(_SNIFF_BYTES)
    except OSError as err:
        logger.info("받은 그림을 확인하지 못했습니다: %s", type(err).__name__)
        return None
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head[4:8] == b"ftyp" and head[8:12] in _HEIC_BRANDS:
        return "heic"
    return None


def _load_heic(path: Path) -> QImage | None:
    """아이폰 사진(HEIC)을 붙여넣을 그림으로 푼다. 저장된 파일은 건드리지 않는다."""
    try:
        import pi_heif  # 없으면(개발 환경 등) 파일로만 복사한다
    except ImportError:
        return None
    try:
        picture = pi_heif.open_heif(str(path), convert_hdr_to_8bit=True)
        width, height = picture.size
        pixel_format = _HEIC_PIXEL_FORMATS.get(picture.mode)
        if pixel_format is None or width * height > MAX_IMAGE_PIXELS:
            return None
        return QImage(picture.data, width, height, picture.stride, pixel_format).copy()
    except Exception as err:  # noqa: BLE001 - 해독 부품이 깨진 파일에 여러 종류의 오류를 낸다
        logger.warning("받은 HEIC 사진을 열지 못해 파일로만 복사합니다: %s", type(err).__name__)
        return None


def _load_image(path: Path) -> QImage | None:
    kind = _sniff(path)
    if kind is None:
        return None
    if kind == "heic":
        return _load_heic(path)
    QImageReader.setAllocationLimit(ALLOCATION_LIMIT_MB)
    reader = QImageReader(str(path), _QT_FORMATS[kind])
    reader.setDecideFormatFromContent(False)  # 이름만 .png인 다른 형식을 열지 않는다
    reader.setAutoTransform(True)  # 휴대폰 사진의 돌려 찍은 방향을 바로잡는다
    size = reader.size()
    if not size.isValid() or size.width() * size.height() > MAX_IMAGE_PIXELS:
        return None
    image = reader.read()
    if image.isNull():
        logger.warning("받은 그림을 열지 못해 파일로만 복사합니다: %s", reader.errorString())
        return None
    return image
