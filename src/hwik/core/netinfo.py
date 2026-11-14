"""이 PC의 와이파이 주소를 찾고 휴대폰이 열 주소를 만든다."""
from __future__ import annotations

import ipaddress
import logging
import socket

from hwik.core.session import Session

logger = logging.getLogger(__name__)

# 실제로는 아무것도 보내지 않는다. 운영체제에 "이 주소로 간다면 어느 연결을 쓰느냐"만 묻는다.
_ROUTE_PROBE_TARGET = ("10.255.255.255", 1)


def is_home_network_address(address: str) -> bool:
    """공유기 안쪽에서만 쓰는 IPv4 주소인지. 인터넷에 바로 드러난 주소에서는 서버를 열지 않는다."""
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    if parsed.version != 4:
        return False
    return parsed.is_private and not (parsed.is_loopback or parsed.is_link_local or parsed.is_unspecified)


def _route_address() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect(_ROUTE_PROBE_TARGET)
        return probe.getsockname()[0]


def lan_ip() -> str | None:
    """휴대폰이 접속할 이 PC의 주소. 쓸 수 있는 연결이 없으면 None."""
    try:
        address = _route_address()
    except OSError as err:
        logger.info("네트워크 주소를 찾지 못했습니다: %s", err)
        return None
    if not is_home_network_address(address):
        logger.info("공유기 안쪽 주소가 아니어서 쓰지 않습니다.")
        return None
    return address


def phone_url(address: str, port: int, session: Session) -> str:
    """QR에 담을 주소. 암호가 들어 있으니 기록(로그)에 남기지 않는다."""
    return f"http://{address}:{port}/t/{session.token}/"
