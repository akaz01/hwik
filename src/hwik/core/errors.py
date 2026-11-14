"""전송 핵심에서 나는 오류. 글은 사용자에게 그대로 보여 줄 수 있게 쓴다."""
from __future__ import annotations


class TransferError(Exception):
    """전송 기능이 스스로 알아챈 문제."""


class FileTooLargeError(TransferError):
    """정해 둔 크기보다 큰 파일이 들어왔다."""


class NotEnoughSpaceError(TransferError):
    """저장할 디스크에 빈 공간이 모자란다."""


class IncompleteTransferError(TransferError):
    """보내는 도중에 연결이 끊겨 파일이 다 오지 않았다."""


class PortUnavailableError(TransferError):
    """서버가 쓸 포트를 열지 못했다(다른 프로그램이 쓰는 중이거나 주소가 사라짐)."""


class NoNetworkError(TransferError):
    """휴대폰이 접속할 수 있는 와이파이 주소가 없다."""
