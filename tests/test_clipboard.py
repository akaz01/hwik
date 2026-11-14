"""받은 파일을 클립보드에 넣는 부분 시험. 받은 그림은 믿을 수 없는 파일로 다룬다."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData
from PySide6.QtGui import QColor, QGuiApplication, QImage

from hwik import clipboard

pytestmark = pytest.mark.usefixtures("qapp")


def make_image(path: Path, width: int = 40, height: int = 30, file_format: str = "PNG") -> Path:
    image = QImage(width, height, QImage.Format.Format_Grayscale8)
    image.fill(QColor("white"))
    assert image.save(str(path), file_format)
    return path


def copied() -> QMimeData:
    return QGuiApplication.clipboard().mimeData()


def test_nothing_to_copy_gives_empty_message() -> None:
    assert clipboard.copy_received([]) == ""


def test_single_photo_is_copied_as_picture_and_as_file(tmp_path: Path) -> None:
    photo = make_image(tmp_path / "사진.png")

    message = clipboard.copy_received([photo])

    assert message == clipboard.COPIED_IMAGE
    assert copied().hasImage()
    assert [Path(url.toLocalFile()) for url in copied().urls()] == [photo]


def test_jpeg_photo_is_copied_as_picture(tmp_path: Path) -> None:
    photo = make_image(tmp_path / "사진.JPG", file_format="JPG")

    assert clipboard.copy_received([photo]) == clipboard.COPIED_IMAGE


def test_several_files_are_copied_as_files_only(tmp_path: Path) -> None:
    photos = [make_image(tmp_path / f"{index}.png") for index in range(3)]

    message = clipboard.copy_received(photos)

    assert message == clipboard.COPIED_FILES
    assert not copied().hasImage()
    assert len(copied().urls()) == 3


def test_file_that_only_pretends_to_be_png_is_not_opened(tmp_path: Path) -> None:
    fake = make_image(tmp_path / "bmp.bmp", file_format="BMP").rename(tmp_path / "fake.png")

    message = clipboard.copy_received([fake])

    assert message == clipboard.COPIED_FILES
    assert not copied().hasImage()


def test_picture_with_too_many_pixels_is_not_opened(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clipboard, "MAX_IMAGE_PIXELS", 1000)
    big = make_image(tmp_path / "big.png", width=40, height=30)

    assert clipboard.copy_received([big]) == clipboard.COPIED_FILES
    assert not copied().hasImage()


def test_document_is_copied_as_file(tmp_path: Path) -> None:
    document = tmp_path / "보고서.pdf"
    document.write_bytes(b"%PDF")

    assert clipboard.copy_received([document]) == clipboard.COPIED_FILES


def test_copy_text_puts_text_on_clipboard() -> None:
    clipboard.copy_text("붙여넣을 글자")

    assert QGuiApplication.clipboard().text() == "붙여넣을 글자"


def test_pixel_limit_stays_well_below_qt_memory_limit() -> None:
    assert clipboard.MAX_IMAGE_PIXELS * 4 <= clipboard.ALLOCATION_LIMIT_MB * 1024 * 1024


SAMPLE_HEIC = Path(__file__).parent / "data" / "sample.heic"  # 왼쪽 반은 파랑, 오른쪽 반은 빨강인 64x48 그림


def test_iphone_heic_photo_is_copied_as_picture(tmp_path: Path) -> None:
    photo = tmp_path / "IMG_0001.HEIC"
    photo.write_bytes(SAMPLE_HEIC.read_bytes())

    message = clipboard.copy_received([photo])

    assert message == clipboard.COPIED_IMAGE
    picture = QGuiApplication.clipboard().image()
    assert (picture.width(), picture.height()) == (64, 48)
    left, right = picture.pixelColor(5, 5), picture.pixelColor(60, 5)
    assert left.blue() > 150 > left.red() and right.red() > 150 > right.blue()
    assert copied().hasUrls()  # 원본 파일도 그대로 붙여넣을 수 있다


def test_jpeg_that_arrives_with_heic_name_is_still_copied_as_picture(tmp_path: Path) -> None:
    """아이폰은 이름은 .heic인데 내용은 JPG인 사진을 보내기도 한다. 이름이 아니라 내용을 본다."""
    photo = tmp_path / "IMG_0002.heic"
    make_image(tmp_path / "real.jpg", file_format="JPG").rename(photo)

    assert clipboard.copy_received([photo]) == clipboard.COPIED_IMAGE


def test_broken_heic_is_copied_as_file_without_crashing(tmp_path: Path) -> None:
    photo = tmp_path / "broken.heic"
    photo.write_bytes(SAMPLE_HEIC.read_bytes()[:60] + b"\x00" * 200)

    assert clipboard.copy_received([photo]) == clipboard.COPIED_FILES


def test_heic_with_too_many_pixels_is_not_opened(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    photo = tmp_path / "big.heic"
    photo.write_bytes(SAMPLE_HEIC.read_bytes())
    monkeypatch.setattr(clipboard, "MAX_IMAGE_PIXELS", 100)

    assert clipboard.copy_received([photo]) == clipboard.COPIED_FILES
