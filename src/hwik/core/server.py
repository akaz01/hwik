"""휴대폰이 접속하는 작은 웹 서버.

주소에 든 암호가 맞을 때만 응답하고, 그 밖의 요청은 모두 거절한다.
암호가 든 주소는 기록(로그)에 남기지 않는다.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import socket
import socketserver
import sys
import threading
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import BinaryIO
from urllib.parse import quote, unquote

from hwik.core.errors import (
    FileTooLargeError,
    IncompleteTransferError,
    NotEnoughSpaceError,
    PortUnavailableError,
    TransferError,
)
from hwik.core.events import (
    FileSent,
    Listener,
    TextReceived,
    TransferEvent,
    TransferFailed,
    TransferFinished,
    TransferProgress,
    TransferStarted,
)
from hwik.core.outbox import MAX_TEXT_CHARS, FileOffer, Offer, Outbox
from hwik.core.session import AttemptLimiter, Session
from hwik.core.transfer import (
    ProgressCallback,
    ReceiveLimits,
    receive_file,
    remove_stale_parts,
    safe_file_name,
)

logger = logging.getLogger(__name__)

DEFAULT_WEB_DIR = Path(__file__).resolve().parent.parent / "web"
REQUEST_TIMEOUT_SECONDS = 30
STOP_WAIT_SECONDS = 5
STOP_POLL_SECONDS = 0.1  # 끄라는 신호를 얼마나 자주 확인할지
PROGRESS_INTERVAL_SECONDS = 0.1  # 진행 알림을 너무 자주 보내지 않게
MAX_NAME_HEADER_LENGTH = 2000
MAX_UPCOMING_FILES = 10_000  # 휴대폰이 "뒤에 더 온다"고 알리는 값의 상한(화면 표시에만 쓴다)
MAX_UPCOMING_BYTES = 1024**4
HEADER_DEADLINE_SECONDS = 10.0  # 연결하고 요청 머리글을 다 보낼 때까지 주는 전체 시간
TEXT_BURST = 5  # 글자는 이 시간 안에 이만큼까지만 받는다(클립보드를 계속 덮어쓰지 못하게)
TEXT_WINDOW_SECONDS = 10.0
MAX_DRAIN_BYTES = 8 * 1024 * 1024
DRAIN_SECONDS = 2.0
MAX_LENGTH_DIGITS = 19
DEFAULT_MAX_ACTIVE_UPLOADS = 3  # 휴대폰 화면은 파일을 하나씩 차례로 보낸다
DISCARD_CHUNK_BYTES = 64 * 1024
SEND_CHUNK_BYTES = 256 * 1024
MAX_TEXT_BYTES = MAX_TEXT_CHARS * 4  # 한 글자는 많아야 4바이트
BINARY_TYPE = "application/octet-stream"
DEFAULT_MAX_CONNECTIONS = 32
DEFAULT_MAX_CONNECTIONS_PER_CLIENT = 8  # 휴대폰 브라우저는 한 번에 6개까지 연결한다
HTML_TYPE = "text/html; charset=utf-8"
CSS_TYPE = "text/css; charset=utf-8"
SCRIPT_TYPE = "text/javascript; charset=utf-8"
JSON_TYPE = "application/json; charset=utf-8"
TEXT_TYPE = "text/plain; charset=utf-8"
# 휴대폰에 내주는 화면 파일. 여기 적힌 것만 내준다(주소로 다른 파일을 꺼낼 수 없다).
PAGE_FILES: Mapping[str, tuple[str, str]] = {
    "": ("index.html", HTML_TYPE),
    "app.css": ("app.css", CSS_TYPE),
    "app.js": ("app.js", SCRIPT_TYPE),
}
SECURITY_HEADERS = (
    ("Cache-Control", "no-store"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),  # 주소에 든 암호가 다른 사이트로 새지 않게
    ("X-Frame-Options", "DENY"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    (
        "Content-Security-Policy",
        "default-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    ),
)
_ERROR_STATUS: Mapping[type[TransferError], HTTPStatus] = {
    FileTooLargeError: HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
    NotEnoughSpaceError: HTTPStatus.INSUFFICIENT_STORAGE,
}


@dataclass(frozen=True)
class ServerConfig:
    """서버를 어디에 열고 받은 파일을 어디에 둘지. port가 0이면 비어 있는 포트를 운영체제가 고른다."""

    host: str
    save_dir: Path
    port: int = 0
    web_dir: Path = DEFAULT_WEB_DIR
    limits: ReceiveLimits = field(default_factory=ReceiveLimits)
    max_connections: int = DEFAULT_MAX_CONNECTIONS
    max_connections_per_client: int = DEFAULT_MAX_CONNECTIONS_PER_CLIENT
    max_active_uploads: int = DEFAULT_MAX_ACTIVE_UPLOADS

    def __post_init__(self) -> None:
        # 휴대폰이 보내는 Host와 글자 그대로 비교하므로 이름이나 0.0.0.0이 아닌 실제 주소여야 한다.
        if ipaddress.ip_address(self.host).version != 4 or self.host == "0.0.0.0":
            raise ValueError("host는 이 PC의 IPv4 주소여야 합니다.")


@dataclass(frozen=True)
class _Context:
    """요청을 처리할 때 필요한 것들. 서버가 켜질 때 한 번 만들고 바꾸지 않는다."""

    session: Session
    limiter: AttemptLimiter
    pages: Mapping[str, tuple[bytes, str]]
    allowed_host: str
    save_dir: Path
    limits: ReceiveLimits
    listener: Listener | None
    outbox: Outbox


def _content_disposition(name: str) -> str:
    """내려받을 파일 이름을 알려 주는 머리글 값. 이름 속 글자가 머리글을 깨뜨리지 못하게 바꿔 넣는다."""
    plain = "".join(char if char.isascii() and (char.isalnum() or char in "._- ") else "_" for char in name)
    return f"attachment; filename=\"{plain or 'file'}\"; filename*=UTF-8''{quote(name, safe='')}"


def _describe(offer: Offer) -> dict[str, object]:
    """휴대폰에 알려 줄 내용. PC의 경로는 넣지 않는다."""
    if isinstance(offer, FileOffer):
        return {"id": offer.item_id, "kind": "file", "name": offer.name, "size": offer.size}
    return {"id": offer.item_id, "kind": "text", "text": offer.text}


class _HttpServer(ThreadingHTTPServer):
    allow_reuse_address = False  # 윈도우에서는 켜 두면 다른 프로그램이 같은 포트를 가로챌 수 있다
    daemon_threads = True
    context: _Context

    def __init__(self, config: ServerConfig) -> None:
        self._max_connections = config.max_connections
        self._max_connections_per_client = config.max_connections_per_client
        self._upload_slots = threading.BoundedSemaphore(config.max_active_uploads)
        self._connections: dict[socket.socket, str] = {}
        self._request_threads: set[threading.Thread] = set()
        self._connections_lock = threading.Lock()
        self._text_times: tuple[float, ...] = ()
        super().__init__((config.host, config.port), _Handler)

    def allow_text(self) -> bool:
        """글자를 지금 받아도 되는지. 짧은 시간에 너무 많이 오면 거절한다."""
        now = time.monotonic()
        with self._connections_lock:
            recent = tuple(moment for moment in self._text_times if now - moment < TEXT_WINDOW_SECONDS)
            if len(recent) >= TEXT_BURST:
                self._text_times = recent
                return False
            self._text_times = (*recent, now)
            return True

    def process_request_thread(  # type: ignore[override]
        self, request: socket.socket, client_address: tuple[str, int]
    ) -> None:
        """요청을 처리하는 스레드를 적어 둔다. 끌 때 이들이 정리를 마칠 때까지 기다리기 위해서다."""
        thread = threading.current_thread()
        with self._connections_lock:
            self._request_threads.add(thread)
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self._connections_lock:
                self._request_threads.discard(thread)

    def wait_for_requests(self, timeout: float) -> None:
        """처리 중이던 요청이 덜 받은 파일을 지우고 끝날 때까지 잠깐 기다린다."""
        deadline = time.monotonic() + timeout
        with self._connections_lock:
            threads = list(self._request_threads)
        for thread in threads:
            thread.join(max(deadline - time.monotonic(), 0))
        if any(thread.is_alive() for thread in threads):
            logger.warning("처리 중이던 요청이 제때 끝나지 않았습니다.")

    def try_begin_upload(self) -> bool:
        return self._upload_slots.acquire(blocking=False)

    def end_upload(self) -> None:
        self._upload_slots.release()

    def process_request(self, request: socket.socket, client_address: tuple[str, int]) -> None:  # type: ignore[override]
        """연결 수가 너무 많으면 받지 않고 바로 닫는다(느린 연결을 잔뜩 열어 서버를 지치게 하는 것을 막는다)."""
        if self._admit(request, client_address[0]):
            super().process_request(request, client_address)
        else:
            logger.info("%s 연결이 너무 많아 받지 않았습니다.", client_address[0])
            super().shutdown_request(request)

    def shutdown_request(self, request: socket.socket) -> None:  # type: ignore[override]
        with self._connections_lock:
            self._connections.pop(request, None)
        super().shutdown_request(request)

    def handle_error(self, request: object, client_address: tuple[str, int]) -> None:  # type: ignore[override]
        """기본 구현은 요청 내용이 섞일 수 있는 오류 글을 화면에 찍는다. 오류 종류만 기록한다."""
        error_type = sys.exc_info()[0]
        logger.warning("%s 요청 처리 중 오류: %s", client_address[0], getattr(error_type, "__name__", "?"))

    def close_open_connections(self) -> None:
        """서버를 끌 때 진행 중인 연결도 끊는다(끈 뒤에 전송이 계속되지 않게)."""
        with self._connections_lock:
            open_connections = list(self._connections)
        for connection in open_connections:
            _force_close(connection)

    def _admit(self, request: socket.socket, client: str) -> bool:
        with self._connections_lock:
            from_client = sum(1 for owner in self._connections.values() if owner == client)
            if len(self._connections) >= self._max_connections or from_client >= self._max_connections_per_client:
                return False
            self._connections[request] = client
            return True

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        # 기본 구현은 여기서 컴퓨터 이름을 찾느라 몇 초씩 멈출 수 있어 건너뛴다.
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = port


def _force_close(connection: socket.socket) -> None:
    """읽기를 기다리며 멈춰 있는 연결까지 확실히 끊는다."""
    try:
        connection.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass  # 이미 끊긴 연결
    # 윈도우에서는 끊는 신호만으로는 읽기를 기다리던 스레드가 깨어나지 않는다.
    # connection.close()는 읽는 쪽이 붙잡고 있는 동안 실제로 닫지 않으므로 직접 닫는다.
    try:
        socket.close(connection.detach())
    except OSError:
        pass  # 이미 닫힌 연결


def _parse_length(raw: str) -> int | None:
    """Content-Length 값. 숫자만으로 된 적당한 길이의 값이 아니면 None."""
    text = raw.strip()
    if len(text) > MAX_LENGTH_DIGITS or not (text.isascii() and text.isdigit()):
        return None
    return int(text)


class _Handler(BaseHTTPRequestHandler):
    server_version = "hwik"
    sys_version = ""
    timeout = REQUEST_TIMEOUT_SECONDS
    server: _HttpServer

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - 부모 클래스의 이름
        """기본 기록에는 암호가 든 주소가 들어가므로 쓰지 않는다. 기록은 _reply가 남긴다."""

    def handle_one_request(self) -> None:
        """요청 머리글을 다 받을 때까지 전체 기한을 둔다.

        timeout은 '한 번 읽을 때 기다리는 시간'일 뿐이라, 머리글을 한 글자씩 천천히 보내면 암호 없이도
        연결 칸을 끝없이 차지할 수 있다. 기한이 지나면 연결을 끊는다. 본문을 받는 시간은 여기에 들지 않는다.
        """
        self._header_timer = threading.Timer(HEADER_DEADLINE_SECONDS, _force_close, args=(self.connection,))
        self._header_timer.daemon = True
        self._header_timer.start()
        try:
            super().handle_one_request()
        except (OSError, ValueError):  # 기한이 지나 끊긴 연결에서 읽으려 했다
            self.close_connection = True
        finally:
            self._header_timer.cancel()

    def do_GET(self) -> None:  # noqa: N802 - http.server가 정한 이름
        self._header_timer.cancel()  # 머리글을 다 받았다
        sub_path = self._authorized_sub_path()
        if sub_path is None:
            return
        context = self.server.context
        if sub_path in context.pages:
            body, content_type = context.pages[sub_path]
            self._reply(HTTPStatus.OK, body, content_type, note="화면 파일")
        elif sub_path == "info":
            self._reply_json(HTTPStatus.OK, {"ok": True, "maxFileBytes": context.limits.max_file_bytes}, note="정보")
        elif sub_path == "state":
            version, items = context.outbox.snapshot()
            payload: dict[str, object] = {"ok": True, "version": version}
            if self.headers.get("X-Seen") != str(version):  # 휴대폰이 이미 가진 목록이면 다시 보내지 않는다
                payload["items"] = [_describe(item) for item in items]
            self._reply_json(HTTPStatus.OK, payload, note="")  # 휴대폰이 1~2초마다 묻는다. 기록하지 않는다
        elif sub_path.startswith("dl/"):
            self._handle_download(sub_path[len("dl/"):])
        else:
            self._reply(HTTPStatus.NOT_FOUND, note="없는 경로")

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        """형식이 잘못된 요청에 대한 응답. 기본 구현과 달리 받은 요청 내용을 되돌려 보내지 않는다."""
        try:
            status = HTTPStatus(code)
        except ValueError:
            status = HTTPStatus.INTERNAL_SERVER_ERROR
        self.close_connection = True
        self._reply(status, note="받을 수 없는 요청")

    def do_POST(self) -> None:  # noqa: N802 - http.server가 정한 이름
        self._header_timer.cancel()  # 머리글을 다 받았다. 파일을 받는 시간은 기한에 넣지 않는다
        sub_path = self._authorized_sub_path()
        if sub_path is None:
            return
        if not self._is_from_own_page():
            self._refuse(HTTPStatus.FORBIDDEN, note="다른 사이트에서 온 요청")
        elif sub_path == "up":
            self._handle_upload()
        elif sub_path == "text":
            self._handle_text()
        else:
            self._refuse(HTTPStatus.NOT_FOUND, note="없는 경로")

    def _authorized_sub_path(self) -> str | None:
        """암호가 맞으면 그 뒤 경로를 돌려준다. 아니면 거절 응답을 보내고 None을 돌려준다."""
        context = self.server.context
        hosts = self.headers.get_all("Host") or []
        if len(hosts) != 1 or hosts[0].strip().lower() != context.allowed_host:
            # 다른 사이트가 이름만 바꿔 이 서버를 부르는 수법(DNS 재결합)을 막는다.
            self._refuse(HTTPStatus.BAD_REQUEST, note="주소(Host)가 다름")
            return None
        if not self.path.startswith("/"):
            self._refuse(HTTPStatus.BAD_REQUEST, note="경로 형식이 다름")
            return None
        url_path = self.path.split("?", 1)[0].split("#", 1)[0]
        if not Session.is_token_path(url_path):
            self._refuse(HTTPStatus.NOT_FOUND, note="암호 없는 요청")
            return None
        sub_path = context.session.sub_path(url_path)
        if sub_path is not None:
            return sub_path
        client = self.client_address[0]
        if context.limiter.is_blocked(client):
            self._refuse(HTTPStatus.TOO_MANY_REQUESTS, note="틀린 암호가 너무 많음")
        else:
            context.limiter.record_failure(client)
            self._refuse(HTTPStatus.FORBIDDEN, note="틀린 암호")
        return None

    def _is_from_own_page(self) -> bool:
        """상태를 바꾸는 요청이 이 서버가 내준 화면에서 왔는지. 다른 사이트가 대신 보낸 요청을 막는다."""
        origin = self.headers.get("Origin")
        if origin is not None and origin.strip().lower() != f"http://{self.server.context.allowed_host}":
            return False
        return self.headers.get("Sec-Fetch-Site") in (None, "same-origin", "none")

    def _handle_upload(self) -> None:
        request = self._read_upload_headers()
        if request is None:
            return
        if not self.server.try_begin_upload():
            self._refuse_json(
                HTTPStatus.SERVICE_UNAVAILABLE, "PC가 다른 파일을 받고 있습니다. 잠시 뒤 다시 보내 주세요."
            )
            return
        try:
            self._receive(*request)
        finally:
            self.server.end_upload()

    def _read_upcoming(self, header: str, limit: int) -> int:
        """휴대폰이 알려 준 '뒤에 더 올 것'. 화면 표시에만 쓰므로 이상하면 0으로 보고, 큰 값은 자른다."""
        values = self.headers.get_all(header) or []
        parsed = _parse_length(values[0]) if len(values) == 1 else None
        return min(parsed, limit) if parsed is not None else 0

    def _read_upload_headers(self) -> tuple[int, str, int, int] | None:
        """올리기 요청의 크기와 이름. 형식이 이상하면 거절 응답을 보내고 None을 돌려준다."""
        lengths = self.headers.get_all("Content-Length") or []
        if not lengths:
            self._refuse_json(HTTPStatus.LENGTH_REQUIRED, "파일 크기를 알 수 없어 받지 않았습니다.")
            return None
        encoded_name = self.headers.get("X-Name") or ""
        length = _parse_length(lengths[0]) if len(lengths) == 1 else None
        # 크기를 두 가지로 말하는 요청, 휴대폰 화면이 보내지 않는 꼴의 이름은 받지 않는다.
        if length is None or self.headers.get("Transfer-Encoding") is not None or not encoded_name.isascii():
            self._refuse_json(HTTPStatus.BAD_REQUEST, "요청이 올바르지 않습니다.")
            return None
        name = unquote(encoded_name, errors="replace")[:MAX_NAME_HEADER_LENGTH]
        upcoming_files = self._read_upcoming("X-Left-Count", MAX_UPCOMING_FILES)
        return length, name, upcoming_files, self._read_upcoming("X-Left-Bytes", MAX_UPCOMING_BYTES)

    def _receive(self, length: int, raw_name: str, upcoming_files: int = 0, upcoming_bytes: int = 0) -> None:
        context = self.server.context
        name, transfer_id = safe_file_name(raw_name), uuid.uuid4().hex
        self._emit(TransferStarted(transfer_id, name, length, self.client_address[0], upcoming_files, upcoming_bytes))
        try:
            received = receive_file(
                self.rfile, length, context.save_dir, raw_name, context.limits, self._progress_reporter(transfer_id)
            )
        except IncompleteTransferError as err:
            logger.info("%s 받는 중 끊김", self.client_address[0])
            self._emit(TransferFailed(transfer_id, name, str(err)))
            self.close_connection = True  # 상대가 이미 끊었으니 응답하지 않는다
        except TransferError as err:
            self._emit(TransferFailed(transfer_id, name, str(err)))
            self._refuse_json(_ERROR_STATUS.get(type(err), HTTPStatus.INTERNAL_SERVER_ERROR), str(err))
        except Exception:
            # 예상하지 못한 오류여도 화면에 "받는 중"이 끝없이 남지 않게 알린 뒤 다시 올린다.
            self._emit(TransferFailed(transfer_id, name, "받는 중 문제가 생겼습니다."))
            raise
        else:
            self._emit(TransferFinished(transfer_id, received.path, received.size))
            self._reply_json(HTTPStatus.OK, {"ok": True, "name": received.path.name}, note="파일 받음")

    def _handle_download(self, item_id: str) -> None:
        """PC 사용자가 내주기로 한 파일을 휴대폰에 보낸다. 번호로만 찾고 경로는 받지 않는다."""
        offer = self.server.context.outbox.find_file(item_id)
        if offer is None:
            self._reply_json(HTTPStatus.NOT_FOUND, {"ok": False, "message": "PC가 이 파일을 내주고 있지 않습니다."}, "")
            return
        try:
            source = offer.path.open("rb")
        except OSError:
            self._reply_json(HTTPStatus.NOT_FOUND, {"ok": False, "message": "PC에서 파일을 찾을 수 없습니다."}, "")
            return
        with source:
            size = os.fstat(source.fileno()).st_size
            extra = (("Content-Disposition", _content_disposition(offer.name)),)
            if self._send_head(HTTPStatus.OK, BINARY_TYPE, size, extra, note="파일 보냄") and self._stream(source, size):
                self._emit(FileSent(offer.name, size, self.client_address[0]))

    def _stream(self, source: BinaryIO, size: int) -> bool:
        """파일 내용을 끝까지 보냈으면 True."""
        remaining = size
        try:
            while remaining > 0:
                piece = source.read(min(SEND_CHUNK_BYTES, remaining))
                if not piece:
                    break  # 보내는 사이에 파일이 줄었다
                self.wfile.write(piece)
                remaining -= len(piece)
        except OSError as err:
            logger.info("%s 파일을 보내는 중 끊김: %s", self.client_address[0], type(err).__name__)
        self.close_connection = True
        return remaining == 0

    def _handle_text(self) -> None:
        """휴대폰이 보낸 글자를 받아 화면 쪽에 알린다."""
        lengths = self.headers.get_all("Content-Length") or []
        if not lengths:
            self._refuse_json(HTTPStatus.LENGTH_REQUIRED, "글자를 받지 못했습니다.")
            return
        length = _parse_length(lengths[0]) if len(lengths) == 1 else None
        if length is None or self.headers.get("Transfer-Encoding") is not None:
            self._refuse_json(HTTPStatus.BAD_REQUEST, "요청이 올바르지 않습니다.")
            return
        if length > MAX_TEXT_BYTES:
            self._refuse_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "글자가 너무 깁니다.")
            return
        if not self.server.allow_text():
            self._refuse_json(HTTPStatus.TOO_MANY_REQUESTS, "글자를 너무 자주 보냈습니다. 잠시 뒤 다시 보내 주세요.")
            return
        try:
            raw = self.rfile.read(length)
        except OSError:
            raw = b""
        if len(raw) != length:  # 보내다 끊겼다: 잘린 글자를 받은 것처럼 넘기지 않는다
            self.close_connection = True
            logger.info("%s 글자 받는 중 끊김", self.client_address[0])
            return
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = ""
        if not text.strip() or len(text) > MAX_TEXT_CHARS:
            self._refuse_json(HTTPStatus.BAD_REQUEST, "보낼 글자가 없거나 읽을 수 없습니다.")
            return
        self._emit(TextReceived(text, self.client_address[0]))
        self._reply_json(HTTPStatus.OK, {"ok": True}, note="글자 받음")

    def _progress_reporter(self, transfer_id: str) -> ProgressCallback:
        last_sent = 0.0

        def report(received: int, total: int) -> None:
            nonlocal last_sent
            now = time.monotonic()
            if received < total and now - last_sent < PROGRESS_INTERVAL_SECONDS:
                return
            last_sent = now
            self._emit(TransferProgress(transfer_id, received, total))

        return report

    def _emit(self, event: TransferEvent) -> None:
        listener = self.server.context.listener
        if listener is None:
            return
        try:
            listener(event)
        except Exception:  # noqa: BLE001 - 화면 쪽 오류 때문에 전송이 깨지면 안 된다
            logger.exception("전송 알림을 받는 쪽에서 오류가 났습니다.")

    def _refuse(self, status: HTTPStatus, note: str) -> None:
        self._reply(status, note=note)
        self._drain_request_body()

    def _refuse_json(self, status: HTTPStatus, message: str) -> None:
        self._reply_json(status, {"ok": False, "message": message}, note="거절")
        self._drain_request_body()

    def _drain_request_body(self) -> None:
        """거절 응답을 보낸 뒤, 아직 오고 있는 본문을 잠깐 받아 버리고 닫는다.

        읽지 않은 본문이 남은 채 바로 닫으면 윈도우가 연결을 강제로 끊어, 휴대폰이 거절 이유 대신
        "연결 끊김"만 보게 된다. 전체 시간과 양에 상한을 둔다.
        """
        self.close_connection = True
        if self.headers.get("Content-Length") is None and self.headers.get("Transfer-Encoding") is None:
            return
        deadline, remaining = time.monotonic() + DRAIN_SECONDS, MAX_DRAIN_BYTES
        try:
            self.connection.shutdown(socket.SHUT_WR)  # 응답은 다 보냈다고 알린다
            while remaining > 0:
                seconds_left = deadline - time.monotonic()
                if seconds_left <= 0:
                    return
                self.connection.settimeout(seconds_left)
                piece = self.rfile.read1(DISCARD_CHUNK_BYTES)
                if not piece:
                    return
                remaining -= len(piece)
        except OSError:
            return  # 본문이 더 오지 않거나 끊겼다. 어차피 버리는 중이다

    def _reply_json(self, status: HTTPStatus, payload: Mapping[str, object], note: str) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._reply(status, body, JSON_TYPE, note=note)

    def _reply(self, status: HTTPStatus, body: bytes = b"", content_type: str = TEXT_TYPE, note: str = "") -> None:
        if not self._send_head(status, content_type, len(body), note=note):
            return
        try:
            self.wfile.write(body)
        except OSError as err:
            logger.info("응답을 보내는 중 연결이 끊겼습니다: %s", type(err).__name__)

    def _send_head(
        self,
        status: HTTPStatus,
        content_type: str,
        length: int,
        extra: tuple[tuple[str, str], ...] = (),
        note: str = "",
    ) -> bool:
        """응답 머리글을 보낸다. 보냈으면 True. note가 비면 기록하지 않는다."""
        if note:
            command = getattr(self, "command", None) or "?"
            logger.info("%s %s -> %d %s", self.client_address[0], command, status.value, note)
        try:
            self.send_response(status.value)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            for name, value in (*SECURITY_HEADERS, *extra):
                self.send_header(name, value)
            self.end_headers()
        except OSError as err:
            logger.info("응답을 보내는 중 연결이 끊겼습니다: %s", type(err).__name__)
            return False
        return True


class TransferServer:
    """서버를 켜고 끈다. 켜진 동안에는 별도 스레드에서 요청을 받는다."""

    def __init__(
        self,
        session: Session,
        config: ServerConfig,
        limiter: AttemptLimiter | None = None,
        listener: Listener | None = None,
        outbox: Outbox | None = None,
    ) -> None:
        self._session = session
        self._config = config
        self._limiter = AttemptLimiter() if limiter is None else limiter
        self._listener = listener
        self._outbox = Outbox() if outbox is None else outbox
        self._httpd: _HttpServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def outbox(self) -> Outbox:
        """PC가 휴대폰에 내줄 파일·글자를 올려 두는 상자."""
        return self._outbox

    @property
    def port(self) -> int:
        httpd = self._httpd
        if httpd is None:
            raise TransferError("서버가 켜져 있지 않습니다.")
        return httpd.server_port

    def start(self) -> None:
        with self._lock:
            if self._httpd is not None:
                raise TransferError("서버가 이미 켜져 있습니다.")
            pages = self._read_pages()
            remove_stale_parts(self._config.save_dir)
            httpd = self._open()
            httpd.context = _Context(
                session=self._session,
                limiter=self._limiter,
                pages=pages,
                allowed_host=f"{self._config.host}:{httpd.server_port}".lower(),
                save_dir=self._config.save_dir,
                limits=self._config.limits,
                listener=self._listener,
                outbox=self._outbox,
            )
            thread = threading.Thread(
                target=httpd.serve_forever,
                kwargs={"poll_interval": STOP_POLL_SECONDS},
                name="hwik-server",
                daemon=True,
            )
            try:
                thread.start()
            except BaseException:
                httpd.server_close()  # 스레드를 못 만들면 열어 둔 포트를 닫고 물러난다
                raise
            self._httpd, self._thread = httpd, thread
            logger.info("서버를 켰습니다: %s:%d", self._config.host, httpd.server_port)

    def stop(self) -> None:
        with self._lock:
            httpd, thread = self._httpd, self._thread
            if httpd is None:
                return
            self._httpd, self._thread = None, None
            httpd.shutdown()
            httpd.close_open_connections()
            httpd.wait_for_requests(STOP_WAIT_SECONDS)
            httpd.server_close()
            if thread is not None:
                thread.join(timeout=STOP_WAIT_SECONDS)
                if thread.is_alive():
                    logger.warning("서버 스레드가 제때 끝나지 않았습니다.")
            logger.info("서버를 껐습니다.")

    def _read_pages(self) -> Mapping[str, tuple[bytes, str]]:
        try:
            return {
                sub_path: ((self._config.web_dir / file_name).read_bytes(), content_type)
                for sub_path, (file_name, content_type) in PAGE_FILES.items()
            }
        except OSError as err:
            raise TransferError("휴대폰 화면 파일을 읽지 못했습니다. 프로그램을 다시 받아 주세요.") from err

    def _open(self) -> _HttpServer:
        try:
            return _HttpServer(self._config)
        except OSError as err:
            raise PortUnavailableError(
                "휴대폰 연결용 통로를 열지 못했습니다. 와이파이 연결을 확인한 뒤 다시 켜 주세요."
            ) from err
