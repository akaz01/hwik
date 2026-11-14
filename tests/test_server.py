"""전송 서버 뼈대 시험: 암호가 맞을 때만 열리고, 그 밖의 요청은 모두 거절한다."""
from __future__ import annotations

import http.client
import logging
import socket
import time
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

import pytest

from hwik.core.errors import PortUnavailableError, TransferError
from hwik.core.server import ServerConfig, TransferServer
from hwik.core.session import AttemptLimiter, Session

TOKEN = "test-token-0123456789"
PAGE_TEXT = "<!doctype html><title>시험 화면</title>"
LOOPBACK = "127.0.0.1"
MAX_FAILURES = 3


class Reply(NamedTuple):
    status: int
    headers: dict[str, str]
    body: bytes


@pytest.fixture
def web_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "web"
    folder.mkdir()
    (folder / "index.html").write_text(PAGE_TEXT, encoding="utf-8")
    (folder / "app.css").write_text("body{}", encoding="utf-8")
    (folder / "app.js").write_text("'use strict';", encoding="utf-8")
    return folder


def make_server(web_dir: Path, port: int = 0) -> TransferServer:
    return TransferServer(
        Session(token=TOKEN),
        ServerConfig(host=LOOPBACK, save_dir=web_dir.parent / "received", port=port, web_dir=web_dir),
        limiter=AttemptLimiter(max_failures=MAX_FAILURES, window_seconds=60),
    )


@pytest.fixture
def server(web_dir: Path) -> Iterator[TransferServer]:
    running = make_server(web_dir)
    running.start()
    yield running
    running.stop()


def ask(server: TransferServer, path: str, method: str = "GET", host: str | None = "") -> Reply:
    """host가 ""이면 올바른 Host, None이면 Host 없음, 그 밖에는 그 값을 보낸다."""
    connection = http.client.HTTPConnection(LOOPBACK, server.port, timeout=5)
    try:
        connection.putrequest(method, path, skip_host=True)
        if host is not None:
            connection.putheader("Host", host or f"{LOOPBACK}:{server.port}")
        if method == "POST":
            connection.putheader("Content-Length", "0")
        connection.endheaders()
        response = connection.getresponse()
        headers = {name.lower(): value for name, value in response.getheaders()}
        return Reply(response.status, headers, response.read())
    finally:
        connection.close()


def test_phone_page_opens_with_correct_token(server: TransferServer) -> None:
    reply = ask(server, f"/t/{TOKEN}/")

    assert reply.status == 200
    assert reply.headers["content-type"] == "text/html; charset=utf-8"
    assert reply.body.decode("utf-8") == PAGE_TEXT


def test_replies_carry_security_headers(server: TransferServer) -> None:
    reply = ask(server, f"/t/{TOKEN}/")

    assert reply.headers["cache-control"] == "no-store"
    assert reply.headers["x-content-type-options"] == "nosniff"
    assert reply.headers["referrer-policy"] == "no-referrer"
    assert reply.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in reply.headers["content-security-policy"]


def test_server_header_does_not_reveal_python(server: TransferServer) -> None:
    reply = ask(server, f"/t/{TOKEN}/")

    assert "python" not in reply.headers.get("server", "").lower()


def test_wrong_token_is_refused(server: TransferServer) -> None:
    reply = ask(server, "/t/wrong-token/")

    assert reply.status == 403
    assert TOKEN.encode() not in reply.body


@pytest.mark.parametrize("path", ["/", "/favicon.ico", "/index.html", "/pc", "/../index.html"])
def test_paths_without_token_are_not_found(server: TransferServer, path: str) -> None:
    assert ask(server, path).status == 404


@pytest.mark.parametrize("sub_path", ["nope", "../index.html", "index.html", "..%2Findex.html"])
def test_unknown_path_under_token_is_not_found(server: TransferServer, sub_path: str) -> None:
    assert ask(server, f"/t/{TOKEN}/{sub_path}").status == 404


@pytest.mark.parametrize("host", ["evil.example", "evil.example:80", f"{LOOPBACK}:1", None])
def test_request_with_wrong_or_missing_host_is_refused(server: TransferServer, host: str | None) -> None:
    assert ask(server, f"/t/{TOKEN}/", host=host).status == 400


def test_repeated_wrong_tokens_are_slowed_down_but_right_token_still_works(server: TransferServer) -> None:
    for _ in range(MAX_FAILURES):
        assert ask(server, "/t/guess/").status == 403

    assert ask(server, "/t/guess/").status == 429
    assert ask(server, f"/t/{TOKEN}/").status == 200


def test_requests_without_token_do_not_count_as_guesses(server: TransferServer) -> None:
    for _ in range(MAX_FAILURES + 2):
        ask(server, "/favicon.ico")

    assert ask(server, "/t/guess/").status == 403


def test_post_needs_token_too(server: TransferServer) -> None:
    assert ask(server, "/t/guess/up", method="POST").status == 403
    assert ask(server, f"/t/{TOKEN}/nope", method="POST").status == 404
    assert ask(server, "/up", method="POST").status == 404


def test_unsupported_method_is_refused(server: TransferServer) -> None:
    reply = ask(server, f"/t/{TOKEN}/", method="DELETE")

    assert reply.status == 501
    assert reply.headers["x-content-type-options"] == "nosniff"
    assert TOKEN.encode() not in reply.body


def test_token_never_appears_in_logs(server: TransferServer, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)

    ask(server, f"/t/{TOKEN}/")
    ask(server, f"/t/{TOKEN}/nope")
    ask(server, "/t/guess/")

    assert caplog.records, "요청 기록이 남아야 한다"
    assert TOKEN not in caplog.text


def test_port_is_closed_after_stop(web_dir: Path) -> None:
    running = make_server(web_dir)
    running.start()
    port = running.port
    running.stop()

    with pytest.raises(OSError):
        socket.create_connection((LOOPBACK, port), timeout=1).close()


def test_stop_is_safe_to_call_twice_or_before_start(web_dir: Path) -> None:
    idle = make_server(web_dir)
    idle.stop()

    running = make_server(web_dir)
    running.start()
    running.stop()
    running.stop()


def test_starting_twice_is_an_error(server: TransferServer) -> None:
    with pytest.raises(TransferError):
        server.start()


def test_port_already_in_use_raises_clear_error(server: TransferServer, web_dir: Path) -> None:
    second = make_server(web_dir, port=server.port)

    with pytest.raises(PortUnavailableError):
        second.start()


def test_missing_phone_page_raises_clear_error(tmp_path: Path) -> None:
    broken = make_server(tmp_path)

    with pytest.raises(TransferError):
        broken.start()


@pytest.mark.parametrize("host", ["0.0.0.0", "localhost", "::1", ""])
def test_config_refuses_host_that_is_not_a_real_ipv4_address(tmp_path: Path, host: str) -> None:
    with pytest.raises(ValueError):
        ServerConfig(host=host, save_dir=tmp_path)


def test_server_can_be_started_again_after_stop(web_dir: Path) -> None:
    running = make_server(web_dir)
    running.start()
    running.stop()
    running.start()
    try:
        assert ask(running, f"/t/{TOKEN}/").status == 200
    finally:
        running.stop()


def test_port_is_unknown_before_start(web_dir: Path) -> None:
    with pytest.raises(TransferError):
        _ = make_server(web_dir).port


def raw_exchange(server: TransferServer, request_text: str) -> bytes:
    """http.client가 만들지 못하는 이상한 요청을 그대로 보내고 응답 전체를 받는다."""
    with socket.create_connection((LOOPBACK, server.port), timeout=5) as raw:
        raw.sendall(request_text.encode("latin-1"))
        chunks = []
        while piece := raw.recv(65536):
            chunks.append(piece)
    return b"".join(chunks)


def test_malformed_request_reply_does_not_echo_request_and_has_security_headers(server: TransferServer) -> None:
    reply = raw_exchange(server, f"GET /t/{TOKEN}/ HTTP/1.1 extra words\r\n\r\n")

    # 요청 줄이 깨져 있으면 아주 옛 방식(HTTP/0.9)으로 다뤄져 머리글 없이 빈 응답이 나간다.
    assert TOKEN.encode() not in reply
    assert b"Bad request" not in reply


def test_request_target_that_is_not_a_path_is_refused_without_crash(server: TransferServer) -> None:
    host = f"{LOOPBACK}:{server.port}"

    reply = raw_exchange(server, f"GET http://[/t/{TOKEN}/ HTTP/1.1\r\nHost: {host}\r\n\r\n")

    assert b" 400 " in reply.split(b"\r\n", 1)[0]


def test_request_with_two_host_headers_is_refused(server: TransferServer) -> None:
    host = f"{LOOPBACK}:{server.port}"

    reply = raw_exchange(server, f"GET /t/{TOKEN}/ HTTP/1.1\r\nHost: {host}\r\nHost: evil.example\r\n\r\n")

    assert b" 400 " in reply.split(b"\r\n", 1)[0]


def test_query_string_does_not_change_which_page_is_served(server: TransferServer) -> None:
    assert ask(server, f"/t/{TOKEN}/?x=1").status == 200


def test_connections_beyond_per_client_limit_are_closed_at_once(web_dir: Path) -> None:
    limited = TransferServer(
        Session(token=TOKEN),
        ServerConfig(
            host=LOOPBACK, save_dir=web_dir.parent / "received", web_dir=web_dir, max_connections_per_client=2
        ),
    )
    limited.start()
    idle = [socket.create_connection((LOOPBACK, limited.port), timeout=5) for _ in range(2)]
    try:
        for held in idle:
            held.sendall(b"GET /t/")  # 요청을 끝내지 않고 붙잡아 둔다
        deadline = time.monotonic() + 3
        refused = False
        while not refused and time.monotonic() < deadline:
            try:
                ask(limited, f"/t/{TOKEN}/")
            except (ConnectionError, http.client.HTTPException):
                refused = True
        assert refused, "한도를 넘은 연결은 응답 없이 닫혀야 한다"

        for held in idle:
            held.close()
        deadline = time.monotonic() + 3
        status = 0
        while status != 200 and time.monotonic() < deadline:
            try:
                status = ask(limited, f"/t/{TOKEN}/").status
            except (ConnectionError, http.client.HTTPException):
                time.sleep(0.05)
        assert status == 200, "붙잡던 연결이 끝나면 다시 받아야 한다"
    finally:
        for held in idle:
            held.close()
        limited.stop()


def test_stop_cuts_connections_that_are_still_open(web_dir: Path) -> None:
    running = make_server(web_dir)
    running.start()
    port = running.port
    with socket.create_connection((LOOPBACK, port), timeout=5) as held:
        held.sendall(f"GET /t/{TOKEN}/ HTTP/1.1\r\n".encode())  # 요청을 반만 보낸 상태
        time.sleep(0.2)

        running.stop()

        try:
            held.sendall(f"Host: {LOOPBACK}:{port}\r\n\r\n".encode())
            answer = held.recv(65536)
        except OSError:
            answer = b""
    assert not answer.startswith(b"HTTP/1.0 200"), "끈 뒤에는 응답하지 않아야 한다"
