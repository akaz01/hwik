"""휴대폰 → PC 파일 올리기와 휴대폰 화면 파일 내주기 시험."""
from __future__ import annotations

import http.client
import json
import socket
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import quote

import pytest

from hwik.core.events import (
    TransferEvent,
    TransferFailed,
    TransferFinished,
    TransferProgress,
    TransferStarted,
)
from hwik.core.server import ServerConfig, TransferServer
from hwik.core.session import AttemptLimiter, Session
from hwik.core.transfer import ReceiveLimits

TOKEN = "test-token-0123456789"
LOOPBACK = "127.0.0.1"
MAX_FILE_BYTES = 1024 * 1024
WAIT_SECONDS = 3.0


class Reply(NamedTuple):
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> dict[str, Any]:
        return json.loads(self.body.decode("utf-8"))


class Recorder:
    def __init__(self) -> None:
        self.events: list[TransferEvent] = []

    def __call__(self, event: TransferEvent) -> None:
        self.events.append(event)

    def of(self, kind: type) -> list[Any]:
        return [event for event in self.events if isinstance(event, kind)]


@pytest.fixture
def save_dir(tmp_path: Path) -> Path:
    return tmp_path / "받은 파일"


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


def start_server(save_dir: Path, listener: Callable[[TransferEvent], None] | None) -> TransferServer:
    server = TransferServer(
        Session(token=TOKEN),
        ServerConfig(
            host=LOOPBACK,
            save_dir=save_dir,
            limits=ReceiveLimits(max_file_bytes=MAX_FILE_BYTES, free_space_margin_bytes=0),
        ),
        limiter=AttemptLimiter(max_failures=3, window_seconds=60),
        listener=listener,
    )
    server.start()
    return server


@pytest.fixture
def server(save_dir: Path, recorder: Recorder) -> Iterator[TransferServer]:
    running = start_server(save_dir, recorder)
    yield running
    running.stop()


def send(
    server: TransferServer,
    method: str,
    sub_path: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    token: str = TOKEN,
) -> Reply:
    connection = http.client.HTTPConnection(LOOPBACK, server.port, timeout=5)
    try:
        connection.putrequest(method, f"/t/{token}/{sub_path}")
        for name, value in (headers or {}).items():
            connection.putheader(name, value)
        connection.endheaders(body)
        response = connection.getresponse()
        reply_headers = {name.lower(): value for name, value in response.getheaders()}
        return Reply(response.status, reply_headers, response.read())
    finally:
        connection.close()


def upload(server: TransferServer, name: str | None, data: bytes, token: str = TOKEN) -> Reply:
    headers = {"Content-Length": str(len(data))}
    if name is not None:
        headers["X-Name"] = quote(name, safe="")
    return send(server, "POST", "up", data, headers, token)


def saved_names(save_dir: Path) -> list[str]:
    return sorted(path.name for path in save_dir.iterdir()) if save_dir.exists() else []


def wait_until(condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + WAIT_SECONDS
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("기다린 일이 일어나지 않았다")
        time.sleep(0.02)


def test_upload_saves_file_and_replies_with_saved_name(server: TransferServer, save_dir: Path) -> None:
    reply = upload(server, "겨울 사진.png", b"picture-bytes")

    assert reply.status == 200
    assert reply.headers["content-type"] == "application/json; charset=utf-8"
    assert reply.json() == {"ok": True, "name": "겨울 사진.png"}
    assert (save_dir / "겨울 사진.png").read_bytes() == b"picture-bytes"


def test_upload_passes_on_how_much_the_phone_still_has_to_send(server: TransferServer, recorder: Recorder) -> None:
    headers = {"Content-Length": "1", "X-Name": "a.png", "X-Left-Count": "3", "X-Left-Bytes": "5000"}

    assert send(server, "POST", "up", b"x", headers).status == 200

    begun = recorder.of(TransferStarted)[0]
    assert (begun.upcoming_files, begun.upcoming_bytes) == (3, 5000)


@pytest.mark.parametrize("value", ["-1", "많이", "1e9", "9" * 40, ""])
def test_upload_ignores_nonsense_about_what_is_still_to_come(
    server: TransferServer, recorder: Recorder, value: str
) -> None:
    headers = {"Content-Length": "1", "X-Name": "a.png", "X-Left-Count": value, "X-Left-Bytes": value}
    headers = {name: text.encode("utf-8").decode("latin-1") for name, text in headers.items()}

    assert send(server, "POST", "up", b"x", headers).status == 200

    begun = recorder.of(TransferStarted)[0]
    assert (begun.upcoming_files, begun.upcoming_bytes) == (0, 0)


def test_upload_caps_huge_claims_about_what_is_still_to_come(server: TransferServer, recorder: Recorder) -> None:
    headers = {"Content-Length": "1", "X-Name": "a.png", "X-Left-Count": "9" * 15, "X-Left-Bytes": "9" * 19}

    send(server, "POST", "up", b"x", headers)

    begun = recorder.of(TransferStarted)[0]
    assert begun.upcoming_files <= 100_000
    assert begun.upcoming_bytes <= 1024**5


def test_upload_cannot_escape_save_folder(server: TransferServer, save_dir: Path, tmp_path: Path) -> None:
    reply = upload(server, "../../evil.bin", b"x")

    assert reply.json()["name"] == "evil.bin"
    assert saved_names(save_dir) == ["evil.bin"]
    assert not (tmp_path / "evil.bin").exists()


def test_upload_with_same_name_gets_number(server: TransferServer, save_dir: Path) -> None:
    upload(server, "a.png", b"1")

    assert upload(server, "a.png", b"2").json()["name"] == "a (1).png"
    assert (save_dir / "a.png").read_bytes() == b"1"


def test_upload_without_name_uses_fallback_name(server: TransferServer, save_dir: Path) -> None:
    assert upload(server, None, b"x").status == 200
    assert saved_names(save_dir) == ["파일"]


def test_upload_with_wrong_token_saves_nothing(server: TransferServer, save_dir: Path) -> None:
    assert upload(server, "a.png", b"x", token="guess").status == 403
    assert saved_names(save_dir) == []


def test_upload_over_limit_is_refused_with_readable_message(server: TransferServer, save_dir: Path) -> None:
    reply = send(server, "POST", "up", b"", {"Content-Length": str(MAX_FILE_BYTES + 1), "X-Name": "big.bin"})

    assert reply.status == 413
    assert reply.json()["ok"] is False
    assert "너무 커서" in reply.json()["message"]
    assert saved_names(save_dir) == []


def test_upload_without_length_is_refused(server: TransferServer, save_dir: Path) -> None:
    assert send(server, "POST", "up", None, {"X-Name": "a.bin"}).status == 411
    assert saved_names(save_dir) == []


@pytest.mark.parametrize("length", ["abc", "-5", "1.5", ""])
def test_upload_with_broken_length_is_refused(server: TransferServer, save_dir: Path, length: str) -> None:
    assert send(server, "POST", "up", None, {"Content-Length": length, "X-Name": "a.bin"}).status == 400
    assert saved_names(save_dir) == []


def test_upload_tells_listener_start_progress_and_finish(
    server: TransferServer, save_dir: Path, recorder: Recorder
) -> None:
    data = b"x" * 300_000

    upload(server, "a.bin", data)

    wait_until(lambda: bool(recorder.of(TransferFinished)))
    started, finished = recorder.of(TransferStarted)[0], recorder.of(TransferFinished)[0]
    assert (started.name, started.size, started.client) == ("a.bin", len(data), LOOPBACK)
    assert (finished.path, finished.size) == (save_dir / "a.bin", len(data))
    assert recorder.of(TransferProgress)[-1].received == len(data)
    assert {event.transfer_id for event in recorder.events} == {started.transfer_id}
    assert isinstance(recorder.events[0], TransferStarted)
    assert isinstance(recorder.events[-1], TransferFinished)


def test_each_upload_gets_its_own_id(server: TransferServer, recorder: Recorder) -> None:
    upload(server, "a.bin", b"1")
    upload(server, "b.bin", b"2")

    wait_until(lambda: len(recorder.of(TransferFinished)) == 2)
    first, second = recorder.of(TransferStarted)
    assert first.transfer_id != second.transfer_id


def test_refused_upload_tells_listener_it_failed(server: TransferServer, recorder: Recorder) -> None:
    send(server, "POST", "up", b"", {"Content-Length": str(MAX_FILE_BYTES + 1), "X-Name": "big.bin"})

    wait_until(lambda: bool(recorder.of(TransferFailed)))
    failed = recorder.of(TransferFailed)[0]
    assert failed.name == "big.bin"
    assert "너무 커서" in failed.message


def test_upload_cut_off_midway_leaves_no_file_and_reports_failure(
    server: TransferServer, save_dir: Path, recorder: Recorder
) -> None:
    head = (
        f"POST /t/{TOKEN}/up HTTP/1.1\r\nHost: {LOOPBACK}:{server.port}\r\n"
        "Content-Length: 1000\r\nX-Name: cut.bin\r\n\r\n"
    ).encode()
    with socket.create_connection((LOOPBACK, server.port), timeout=5) as raw:
        raw.sendall(head + b"x" * 10)

    wait_until(lambda: bool(recorder.of(TransferFailed)))
    assert saved_names(save_dir) == []


def test_broken_listener_does_not_break_upload(save_dir: Path) -> None:
    def broken(event: TransferEvent) -> None:
        raise RuntimeError("화면 오류")

    running = start_server(save_dir, broken)
    try:
        assert upload(running, "a.bin", b"x").status == 200
    finally:
        running.stop()
    assert saved_names(save_dir) == ["a.bin"]


def test_upload_works_without_listener(save_dir: Path) -> None:
    running = start_server(save_dir, None)
    try:
        assert upload(running, "a.bin", b"x").status == 200
    finally:
        running.stop()


def test_wrong_token_with_body_still_gets_a_readable_refusal(server: TransferServer) -> None:
    reply = upload(server, "a.bin", b"x" * 200_000, token="guess")

    assert reply.status == 403


@pytest.mark.parametrize(
    ("sub_path", "content_type", "marker"),
    [
        ("app.css", "text/css; charset=utf-8", b".stage"),
        ("app.js", "text/javascript; charset=utf-8", b"use strict"),
    ],
)
def test_phone_screen_files_are_served(
    server: TransferServer, sub_path: str, content_type: str, marker: bytes
) -> None:
    reply = send(server, "GET", sub_path)

    assert reply.status == 200
    assert reply.headers["content-type"] == content_type
    assert marker in reply.body


def test_info_tells_phone_the_size_limit(server: TransferServer) -> None:
    reply = send(server, "GET", "info")

    assert reply.status == 200
    assert reply.json() == {"ok": True, "maxFileBytes": MAX_FILE_BYTES}


def test_get_on_upload_path_is_not_found(server: TransferServer) -> None:
    assert send(server, "GET", "up").status == 404


def test_upload_from_another_site_is_refused(server: TransferServer, save_dir: Path) -> None:
    headers = {"Content-Length": "1", "X-Name": "a.bin", "Origin": "http://evil.example"}

    assert send(server, "POST", "up", b"x", headers).status == 403
    assert saved_names(save_dir) == []


def test_upload_marked_cross_site_by_browser_is_refused(server: TransferServer, save_dir: Path) -> None:
    headers = {"Content-Length": "1", "X-Name": "a.bin", "Sec-Fetch-Site": "cross-site"}

    assert send(server, "POST", "up", b"x", headers).status == 403
    assert saved_names(save_dir) == []


def test_upload_from_own_page_is_accepted(server: TransferServer, save_dir: Path) -> None:
    headers = {"Content-Length": "1", "X-Name": "a.bin", "Origin": f"http://{LOOPBACK}:{server.port}"}

    assert send(server, "POST", "up", b"x", headers).status == 200


def test_stop_during_upload_leaves_no_partial_file(save_dir: Path, recorder: Recorder) -> None:
    running = start_server(save_dir, recorder)
    head = (
        f"POST /t/{TOKEN}/up HTTP/1.1\r\nHost: {LOOPBACK}:{running.port}\r\n"
        "Content-Length: 1000\r\nX-Name: cut.bin\r\n\r\n"
    ).encode()
    with socket.create_connection((LOOPBACK, running.port), timeout=5) as raw:
        raw.sendall(head + b"x" * 10)
        wait_until(lambda: bool(recorder.of(TransferStarted)))

        try:
            running.stop()
        finally:
            running.stop()

        # 기다리지 않고 바로 확인한다: 끄기가 끝났으면 정리도 끝나 있어야 한다.
        assert recorder.of(TransferFailed)
        assert saved_names(save_dir) == []


def test_reply_to_oversized_upload_arrives_even_when_body_is_already_on_its_way(server: TransferServer) -> None:
    reply = upload(server, "big.bin", b"x" * (MAX_FILE_BYTES * 3))

    assert reply.status == 413
    assert "너무 커서" in reply.json()["message"]


def raw_post(server: TransferServer, extra_headers: str, body: bytes = b"x") -> bytes:
    head = f"POST /t/{TOKEN}/up HTTP/1.1\r\nHost: {LOOPBACK}:{server.port}\r\n{extra_headers}\r\n".encode()
    with socket.create_connection((LOOPBACK, server.port), timeout=5) as raw:
        raw.sendall(head + body)
        chunks = []
        while piece := raw.recv(65536):
            chunks.append(piece)
    return b"".join(chunks).split(b"\r\n", 1)[0]


@pytest.mark.parametrize(
    "headers",
    [
        "Content-Length: 1\r\nContent-Length: 1\r\nX-Name: a.bin\r\n",
        "Content-Length: 1\r\nTransfer-Encoding: chunked\r\nX-Name: a.bin\r\n",
        "Content-Length: " + "9" * 30 + "\r\nX-Name: a.bin\r\n",
        "Content-Length: 1\r\nX-Name: \xed\x95\x9c.bin\r\n",
    ],
)
def test_upload_with_ambiguous_or_odd_headers_is_refused(
    server: TransferServer, save_dir: Path, headers: str
) -> None:
    assert b" 400 " in raw_post(server, headers) + b" "
    assert saved_names(save_dir) == []


def test_only_a_few_uploads_run_at_the_same_time(save_dir: Path, recorder: Recorder) -> None:
    running = TransferServer(
        Session(token=TOKEN),
        ServerConfig(host=LOOPBACK, save_dir=save_dir, max_active_uploads=1),
        listener=recorder,
    )
    running.start()
    head = (
        f"POST /t/{TOKEN}/up HTTP/1.1\r\nHost: {LOOPBACK}:{running.port}\r\n"
        "Content-Length: 1000\r\nX-Name: slow.bin\r\n\r\n"
    ).encode()
    try:
        with socket.create_connection((LOOPBACK, running.port), timeout=5) as held:
            held.sendall(head + b"x")
            wait_until(lambda: bool(recorder.of(TransferStarted)))

            assert upload(running, "second.bin", b"y").status == 503
        wait_until(lambda: bool(recorder.of(TransferFailed)))
        assert upload(running, "third.bin", b"z").status == 200
    finally:
        running.stop()


def test_part_files_left_by_a_crash_are_cleaned_when_server_starts(save_dir: Path) -> None:
    save_dir.mkdir(parents=True)
    leftover = save_dir / f".{'0f' * 16}.part"
    leftover.write_bytes(b"half")

    running = start_server(save_dir, None)
    running.stop()

    assert not leftover.exists()
