"""배포 zip 만들기: 배포본 폴더(dist/Hwik)와 사용법을 dist/Hwik_win.zip 하나로 묶는다.

배포본에는 직접 만든 exe가 없다. 폴더 안 Hwik.exe는 Python 재단이 서명한 pythonw.exe를 이름만 바꾼 것이고,
압축을 푼 폴더에서 처음 실행하면 스스로 설치한다(hwik/selfinstall.py).

백신이 방금 만든 DLL을 검사하느라 잠깐 잠그면 압축이 실패하므로, 잠금이 풀릴 때까지 잠시 기다렸다 다시 시도한다.
사용: python scripts/package.py Hwik
"""
from __future__ import annotations

import logging
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_NAME = "Hwik"
GUIDE = ROOT / "installer" / "사용법.txt"
LOCK_RETRIES = 15

logger = logging.getLogger("package")


def add(archive: zipfile.ZipFile, source: Path, name_in_zip: str) -> None:
    for _ in range(LOCK_RETRIES):
        try:
            archive.write(source, name_in_zip)
            return
        except PermissionError:
            time.sleep(1)
    raise SystemExit(f"파일이 잠겨 있어 압축하지 못했습니다: {source}")


def main(name: str) -> None:
    stage = ROOT / "dist" / name
    for need in (stage / f"{name}.exe", GUIDE):
        if not need.exists():
            raise SystemExit(f"없음: {need}")
    out = ROOT / "dist" / f"{name}_win.zip"
    part = out.with_suffix(".zip.part")
    files = sorted(path for path in stage.rglob("*") if path.is_file() and "__pycache__" not in path.parts)
    with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        add(archive, GUIDE, GUIDE.name)
        for path in files:
            add(archive, path, f"{name}/{path.relative_to(stage).as_posix()}")
    part.replace(out)
    logger.info("배포용: %s (%.0f MB, 파일 %d개)", out, out.stat().st_size / 1048576, len(files) + 1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_NAME)
