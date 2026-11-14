"""한 번만 실행: 이미 켜져 있으면 두 번째 실행은 켜진 쪽 창을 띄워 달라고만 하고 끝난다."""
from __future__ import annotations

import ctypes
import logging
import os
from collections.abc import Callable

from PySide6.QtNetwork import QLocalServer, QLocalSocket

from hwik import APP_NAME

logger = logging.getLogger(__name__)

ERROR_ALREADY_EXISTS = 183
CONNECT_WAIT_MS = 1500
SHOW_MESSAGE = b"show"

_mutex_handle: int | None = None  # 프로세스가 끝날 때까지 쥐고 있어야 한다


def _session_id() -> int:
    """같은 PC에 여러 사용자가 로그인해 있어도 서로의 통로가 겹치지 않게."""
    session = ctypes.c_ulong(0)
    ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session))
    return session.value


def _channel_name() -> str:
    return f"{APP_NAME}_show_{_session_id()}"


def already_running() -> bool:
    """중복 실행 이름표를 잡아 본다. 이미 누가 잡고 있으면 True."""
    global _mutex_handle
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    _mutex_handle = kernel32.CreateMutexW(None, False, f"Local\\{APP_NAME}SingleInstance")
    error = ctypes.get_last_error()
    if not _mutex_handle:
        logger.warning("중복 실행 이름표를 만들지 못했습니다(오류 %d). 그대로 실행합니다.", error)
        return False
    return error == ERROR_ALREADY_EXISTS


def ask_running_instance_to_show() -> bool:
    socket = QLocalSocket()
    socket.connectToServer(_channel_name())
    if not socket.waitForConnected(CONNECT_WAIT_MS):
        return False
    socket.write(SHOW_MESSAGE)
    socket.waitForBytesWritten(CONNECT_WAIT_MS)
    socket.disconnectFromServer()
    return True


def listen_for_show_requests(on_show: Callable[[], None]) -> QLocalServer:
    """두 번째 실행이 보내는 "창을 띄워 달라"를 듣는다. 돌려준 서버를 쥐고 있어야 계속 듣는다."""
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)  # 같은 사용자만 접근

    def accept() -> None:
        connection = server.nextPendingConnection()
        if connection is None:
            return
        connection.disconnected.connect(connection.deleteLater)
        on_show()  # 내용은 읽지 않는다. 연결이 왔다는 것 자체가 신호다

    server.newConnection.connect(accept)
    QLocalServer.removeServer(_channel_name())
    if not server.listen(_channel_name()):
        logger.warning("두 번째 실행을 알아채는 통로를 열지 못했습니다: %s", server.errorString())
    return server
