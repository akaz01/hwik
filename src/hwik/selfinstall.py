"""설치 파일(Setup.exe) 없이 앱이 스스로 설치·업데이트·제거한다.

Windows의 스마트 앱 컨트롤은 서명도 평판도 없는 exe를 막는다. 그래서 배포본은 직접 만든 exe 대신
Python 재단이 서명한 pythonw.exe를 이름만 Hwik.exe로 바꿔 넣는다(내용·서명 그대로).
내려받아 푼 폴더에서 처음 실행하면 이 모듈이 사용자 폴더(%LOCALAPPDATA%\\Programs\\Hwik)에 복사하고 등록한다.
관리자 권한은 쓰지 않는다(사용자 레지스트리 HKCU와 사용자 폴더만).
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import winreg
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from hwik import APP_NAME, AUTHOR, DISPLAY_NAME, TASKBAR_ID, __version__, settings

logger = logging.getLogger(__name__)

UNINSTALL_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_NAME}"
TASKBAR_KEY = rf"Software\Classes\AppUserModelId\{TASKBAR_ID}"  # 알림에 보이는 앱 이름·아이콘
RETRIES = 20  # 방금 닫은 앱이나 백신이 파일을 놓을 때까지 다시 시도
RETRY_WAIT_SECONDS = 0.25
SHELL_TIMEOUT_SECONDS = 30
REMOVE_TRIES = 60
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# 바로가기는 Windows에 들어 있는 PowerShell로 만든다(추가 부품 없이). 경로는 명령 글자에 끼워 넣지 않고
# 환경 변수로만 넘긴다: 폴더 이름에 따옴표 같은 글자가 있어도 명령이 달라지지 않는다.
MAKE_SHORTCUTS = """
$shell = New-Object -ComObject WScript.Shell
$folders = @([Environment]::GetFolderPath('Programs'))
if ($env:HWIK_DESKTOP -eq '1') { $folders += [Environment]::GetFolderPath('DesktopDirectory') }
foreach ($folder in $folders) {
    $link = $shell.CreateShortcut((Join-Path $folder ($env:HWIK_NAME + '.lnk')))
    $link.TargetPath = $env:HWIK_EXE
    $link.WorkingDirectory = Split-Path -Parent $env:HWIK_EXE
    $link.IconLocation = $env:HWIK_ICON + ',0'
    $link.Description = $env:HWIK_NAME
    $link.Save()
}
"""
REMOVE_SHORTCUTS = """
$shell = New-Object -ComObject WScript.Shell
foreach ($kind in 'Programs', 'DesktopDirectory') {
    $path = Join-Path ([Environment]::GetFolderPath($kind)) ($env:HWIK_NAME + '.lnk')
    if ((Test-Path -LiteralPath $path) -and ($shell.CreateShortcut($path).TargetPath -ieq $env:HWIK_EXE)) {
        Remove-Item -LiteralPath $path -Force
    }
}
"""

ProgressFn = Callable[[int, int], None]


@dataclass(frozen=True)
class Installed:
    folder: Path
    warnings: tuple[str, ...] = ()  # 설치는 됐지만 하지 못한 일(바로가기 등)


def exe_name() -> str:
    return f"{APP_NAME}.exe"


def install_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "Programs" / APP_NAME


def running_dir() -> Path:
    return Path(sys.executable).resolve().parent


def _same(first: Path, second: Path) -> bool:
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(os.path.abspath(second))


def needs_install() -> bool:
    """내려받아 푼 폴더에서 실행했는지(설치 폴더 밖). 설치 폴더에서 실행하면 바로 앱을 띄운다."""
    return not _same(running_dir(), install_dir())


def is_installed() -> bool:
    return (install_dir() / exe_name()).is_file()


def icon_path(folder: Path) -> Path:
    return folder / "assets" / "hwik.ico"


def uninstall_command(folder: Path) -> str:
    return f'"{folder / exe_name()}" -m hwik --uninstall'


# ── 파일 ──


def stop_running() -> None:
    """설치 폴더의 파일을 바꾸기 전에 실행 중인 Hwik을 닫는다(지금 이 설치 과정은 빼고)."""
    taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
    subprocess.run(
        [str(taskkill), "/F", "/IM", exe_name(), "/FI", f"PID ne {os.getpid()}"],
        capture_output=True,
        creationflags=NO_WINDOW,
        check=False,
        timeout=SHELL_TIMEOUT_SECONDS,
    )


def _retry(action: Callable[[], None], what: str) -> None:
    for _ in range(RETRIES - 1):
        try:
            action()
            return
        except OSError:
            time.sleep(RETRY_WAIT_SECONDS)
    try:
        action()
    except OSError as err:
        raise OSError(f"{what} ({type(err).__name__})") from None


def clear_old_files(folder: Path) -> None:
    """예전 판 프로그램 파일을 지운다(새 판에서 빠진 파일이 남지 않게). 설정은 %APPDATA%에 있어 그대로다."""
    if not _same(folder, install_dir()):
        raise ValueError(f"설치 폴더가 아닌 곳은 지우지 않습니다: {folder}")

    def remove() -> None:
        if folder.exists():
            shutil.rmtree(folder)

    _retry(remove, "예전 프로그램 파일을 지우지 못했습니다. 컴퓨터를 다시 시작한 뒤 다시 실행해 주세요")


def _files(folder: Path) -> list[Path]:
    return [path for path in folder.rglob("*") if path.is_file() and "__pycache__" not in path.parts]


def copy_tree(src: Path, dst: Path, progress: ProgressFn | None = None) -> None:
    """내용만 복사한다(인터넷에서 받은 파일이라는 표시는 옮기지 않는다)."""
    files = _files(src)
    for done, source in enumerate(files, 1):
        target = dst / source.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        _retry(lambda source=source, target=target: shutil.copyfile(source, target), f"파일을 복사하지 못했습니다: {source.name}")
        if progress:
            progress(done, len(files))


# ── 등록 ──


def _set(path: str, name: str, value: str | int) -> None:
    kind = winreg.REG_DWORD if isinstance(value, int) else winreg.REG_SZ
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as key:
        winreg.SetValueEx(key, name, 0, kind, value)


def _delete_key(path: str) -> None:
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except FileNotFoundError:
        pass
    except OSError as err:
        logger.warning("레지스트리 항목을 지우지 못했습니다: %s", type(err).__name__)


def register(folder: Path) -> None:
    """Windows '설치된 앱' 목록에 올리고, 알림에 Python 대신 Hwik 이름·아이콘이 보이게 한다."""
    icon = str(icon_path(folder))
    size_kb = sum(path.stat().st_size for path in _files(folder)) // 1024
    values: dict[str, str | int] = {
        "DisplayName": DISPLAY_NAME,
        "DisplayVersion": __version__,
        "Publisher": AUTHOR,
        "DisplayIcon": icon,
        "InstallLocation": str(folder),
        "UninstallString": uninstall_command(folder),
        "NoModify": 1,
        "NoRepair": 1,
        "EstimatedSize": size_kb,
    }
    for name, value in values.items():
        _set(UNINSTALL_KEY, name, value)
    _set(TASKBAR_KEY, "DisplayName", DISPLAY_NAME)
    _set(TASKBAR_KEY, "IconUri", icon)


def shortcut_environment(folder: Path, desktop: bool) -> dict[str, str]:
    return {
        "HWIK_EXE": str(folder / exe_name()),
        "HWIK_ICON": str(icon_path(folder)),
        "HWIK_NAME": DISPLAY_NAME,
        "HWIK_DESKTOP": "1" if desktop else "0",
    }


def _run_powershell(script: str, extra_env: dict[str, str]) -> None:
    root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    powershell = root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    result = subprocess.run(
        [str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
        env={**os.environ, **extra_env},
        capture_output=True,
        creationflags=NO_WINDOW,
        check=False,
        timeout=SHELL_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise OSError(f"PowerShell이 {result.returncode}로 끝났습니다")


def install(desktop: bool, progress: ProgressFn | None = None) -> Installed:
    src, dst = running_dir(), install_dir()
    stop_running()
    clear_old_files(dst)
    copy_tree(src, dst, progress)
    register(dst)
    warnings: list[str] = []
    try:
        _run_powershell(MAKE_SHORTCUTS, shortcut_environment(dst, desktop))
    except (OSError, subprocess.SubprocessError) as err:  # 정책으로 막힌 PC 등: 설치 자체는 끝났다
        logger.warning("바로가기를 만들지 못했습니다: %s", type(err).__name__)
        warnings.append("바로가기를 만들지 못했습니다. 설치 폴더의 Hwik.exe로 실행할 수 있습니다.")
    return Installed(dst, tuple(warnings))


def launch_installed(folder: Path) -> None:
    subprocess.Popen(
        [str(folder / exe_name())],
        cwd=folder,
        close_fds=True,
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
    )


# ── 제거 ──


def uninstall() -> None:
    """'설치된 앱'의 제거 → `Hwik.exe -m hwik --uninstall`. 받은 파일은 건드리지 않는다."""
    folder = install_dir()
    stop_running()
    try:
        _run_powershell(REMOVE_SHORTCUTS, shortcut_environment(folder, desktop=True))
    except (OSError, subprocess.SubprocessError) as err:
        logger.warning("바로가기를 지우지 못했습니다: %s", type(err).__name__)
    _delete_key(UNINSTALL_KEY)
    _delete_key(TASKBAR_KEY)
    shutil.rmtree(settings.settings_path().parent, ignore_errors=True)
    # 프로그램 폴더는 이 프로세스가 끝난 뒤 remove_after_exit()가 지운다.


def removal_command(folder: Path) -> str:
    root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    cmd = os.environ.get("ComSpec") or str(root / "System32" / "cmd.exe")
    return (
        f'"{cmd}" /c for /l %i in (1,1,{REMOVE_TRIES}) do @(ping -n 2 127.0.0.1 >nul'
        f' & rmdir /s /q "{folder}" 2>nul & if not exist "{folder}" exit)'
    )


def remove_after_exit() -> None:
    """실행 중인 자기 파일은 지울 수 없으므로, 이 프로세스가 끝난 뒤 Windows 명령 창이 설치 폴더를 지운다."""
    subprocess.Popen(removal_command(install_dir()), cwd=tempfile.gettempdir(), close_fds=True, creationflags=NO_WINDOW)
