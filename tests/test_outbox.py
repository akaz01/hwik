"""PC가 휴대폰에 내줄 파일·글자 목록(보낼 것 상자) 시험."""
from __future__ import annotations

from pathlib import Path

import pytest

from hwik.core import outbox
from hwik.core.errors import TransferError
from hwik.core.outbox import FileOffer, Outbox, TextOffer


@pytest.fixture
def photo(tmp_path: Path) -> Path:
    path = tmp_path / "여행 사진.png"
    path.write_bytes(b"12345")
    return path


def test_new_outbox_is_empty() -> None:
    version, items = Outbox().snapshot()

    assert (version, items) == (0, ())


def test_add_file_remembers_name_size_and_path(photo: Path) -> None:
    box = Outbox()

    offer = box.add_file(photo)

    assert (offer.name, offer.size, offer.path) == ("여행 사진.png", 5, photo)
    assert box.snapshot() == (1, (offer,))


def test_add_file_refuses_missing_file_and_folder(tmp_path: Path) -> None:
    box = Outbox()

    with pytest.raises(TransferError):
        box.add_file(tmp_path / "없음.png")
    with pytest.raises(TransferError):
        box.add_file(tmp_path)

    assert box.snapshot() == (0, ())


def test_add_text_keeps_text_as_is() -> None:
    box = Outbox()

    offer = box.add_text("  안녕하세요\n둘째 줄  ")

    assert offer.text == "  안녕하세요\n둘째 줄  "


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_add_text_refuses_blank_text(text: str) -> None:
    with pytest.raises(TransferError):
        Outbox().add_text(text)


def test_add_text_refuses_very_long_text() -> None:
    with pytest.raises(TransferError):
        Outbox().add_text("가" * (outbox.MAX_TEXT_CHARS + 1))


def test_every_item_gets_its_own_hard_to_guess_id(photo: Path) -> None:
    box = Outbox()

    ids = {box.add_file(photo).item_id, box.add_file(photo).item_id, box.add_text("a").item_id}

    assert len(ids) == 3
    assert all(len(item_id) >= 22 for item_id in ids)


def test_find_file_returns_only_file_offers(photo: Path) -> None:
    box = Outbox()
    file_offer, text_offer = box.add_file(photo), box.add_text("글자")

    assert box.find_file(file_offer.item_id) == file_offer
    assert box.find_file(text_offer.item_id) is None
    assert box.find_file("unknown") is None


def test_remove_takes_item_out_and_changes_version(photo: Path) -> None:
    box = Outbox()
    offer = box.add_file(photo)

    box.remove(offer.item_id)

    assert box.snapshot() == (2, ())
    assert box.find_file(offer.item_id) is None


def test_remove_of_unknown_item_changes_nothing() -> None:
    box = Outbox()

    box.remove("unknown")

    assert box.snapshot() == (0, ())


def test_clear_empties_the_box(photo: Path) -> None:
    box = Outbox()
    box.add_file(photo)
    box.add_text("글자")

    box.clear()

    version, items = box.snapshot()
    assert items == ()
    assert version == 3


def test_oldest_items_are_dropped_when_box_is_full() -> None:
    box = Outbox()
    offers = [box.add_text(f"글자 {index}") for index in range(outbox.MAX_ITEMS + 3)]

    _, items = box.snapshot()

    assert len(items) == outbox.MAX_ITEMS
    assert items[0] == offers[3]
    assert items[-1] == offers[-1]


def test_offers_cannot_be_changed(photo: Path) -> None:
    box = Outbox()
    file_offer, text_offer = box.add_file(photo), box.add_text("글자")

    assert isinstance(file_offer, FileOffer) and isinstance(text_offer, TextOffer)
    with pytest.raises(AttributeError):
        text_offer.text = "다른 글자"  # type: ignore[misc]
