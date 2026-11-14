"""PC의 와이파이 주소 찾기와 휴대폰용 주소 만들기 시험."""
from __future__ import annotations

import pytest

from hwik.core import netinfo
from hwik.core.session import Session


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("192.168.0.5", True),
        ("172.30.1.14", True),
        ("10.0.0.8", True),
        ("127.0.0.1", False),  # 이 PC 자신
        ("8.8.8.8", False),  # 인터넷에 바로 드러난 주소
        ("169.254.3.4", False),  # 공유기에서 주소를 못 받은 상태
        ("0.0.0.0", False),
        ("fe80::1", False),
        ("not-an-ip", False),
        ("", False),
    ],
)
def test_is_home_network_address(address: str, expected: bool) -> None:
    assert netinfo.is_home_network_address(address) is expected


def test_lan_ip_returns_route_address_when_it_is_a_home_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(netinfo, "_route_address", lambda: "192.168.0.5")

    assert netinfo.lan_ip() == "192.168.0.5"


def test_lan_ip_returns_none_for_public_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(netinfo, "_route_address", lambda: "8.8.8.8")

    assert netinfo.lan_ip() is None


def test_lan_ip_returns_none_when_there_is_no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_network() -> str:
        raise OSError("network unreachable")

    monkeypatch.setattr(netinfo, "_route_address", no_network)

    assert netinfo.lan_ip() is None


def test_real_lan_ip_is_none_or_a_home_address() -> None:
    address = netinfo.lan_ip()

    assert address is None or netinfo.is_home_network_address(address)


def test_phone_url_contains_address_port_and_token() -> None:
    session = Session(token="abc123")

    assert netinfo.phone_url("192.168.0.5", 8765, session) == "http://192.168.0.5:8765/t/abc123/"
