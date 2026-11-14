# Hwik (휙)

휴대폰과 PC 사이에 사진·파일·글자를 **QR 하나로** 주고받는 Windows 프로그램입니다.
휴대폰에는 아무것도 설치하지 않습니다. PC 창에 뜬 QR을 휴대폰 카메라로 찍으면 끝입니다.

<img src="assets/hwik.png" width="96" alt="Hwik 아이콘">

## 할 수 있는 일

- **휴대폰 → PC**: 사진·영상·문서를 골라 보내면 PC 폴더에 저장되고, 사진은 바로 `Ctrl+V`로 붙여넣을 수 있습니다.
- **PC → 휴대폰**: 파일을 창에 끌어다 놓으면 휴대폰에서 받을 수 있습니다.
- **글자**: PC에서 복사한 글자를 휴대폰으로, 휴대폰 글자를 PC 클립보드로 보냅니다.
- 사진과 파일은 다시 압축하거나 줄이지 않고 **원본 그대로** 옮깁니다.
- 아이폰 사진(HEIC)도 받자마자 `Ctrl+V`로 붙여넣을 수 있습니다. 저장되는 파일은 원본 그대로 두고, 붙여넣을 그림만 따로 풀어 넣습니다.
- 받는 동안 몇 번째 파일인지, 얼마나 남았는지 보여 줍니다.
- 인터넷의 다른 곳으로는 아무것도 보내지 않습니다. PC와 휴대폰 사이에서만 오갑니다.

## 설치

1. [Releases](../../releases)에서 `Hwik_win.zip`을 내려받습니다.
2. zip을 마우스 오른쪽 단추 > **압축 풀기**로 먼저 풉니다.
3. 풀린 `Hwik` 폴더 안의 `Hwik.exe`를 실행하고 **설치**를 누릅니다.

- Windows 10(1809 이상) 또는 Windows 11에서 동작합니다. 관리자 권한은 필요 없습니다.
- `Hwik.exe`는 Python 재단이 서명한 실행 파일(`pythonw.exe`)을 이름만 바꾼 것이라, 탐색기에서는 Python 아이콘으로 보입니다.
- 처음 실행하면 Windows 방화벽이 접근 허용을 묻습니다. **허용**을 눌러야 휴대폰이 PC에 접속할 수 있습니다.
  이 창에는 앱 이름이 Hwik이 아니라 **Python**(게시자: Python Software Foundation)으로 나옵니다. 같은 이유(서명된 Python 실행 파일)이며, 그 창이 Hwik의 것이 맞습니다.
- 지우기: 설정 > 앱 > 설치된 앱 > Hwik > 제거

## 쓰는 법

1. PC와 휴대폰을 같은 와이파이에 연결합니다. 와이파이가 없으면 PC를 휴대폰 핫스팟에 연결해도 됩니다.
2. Hwik을 켜고 창의 QR을 휴대폰 카메라로 찍습니다.
3. 휴대폰 화면에서 **사진·파일 고르기**를 누르면 PC로 옵니다.

## 꼭 알아 두세요

- **집·사무실처럼 믿을 수 있는 와이파이나 내 휴대폰 핫스팟에서만 쓰세요.** 주고받는 내용은 암호화되지 않습니다(HTTP).
  카페·공항 같은 공용 와이파이에서는 같은 와이파이의 다른 사람이 내용을 엿볼 수 있습니다.
- QR에는 이번 연결에만 쓰는 암호가 들어 있습니다. QR 화면을 다른 사람에게 보여 주거나 찍어 올리지 마세요.
- 창을 닫으면 연결이 끊기고, 다시 열면 새 암호의 QR이 나옵니다.

## 직접 실행·개발

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest -q        # 시험
$env:PYTHONPATH = "src"; .venv\Scripts\python -m hwik   # 실행
```

배포본은 `build.ps1`로 만듭니다(서명된 임베디드 Python 3.12 런타임이 따로 필요합니다).

## 함께 쓴 오픈소스

Python(PSF License), Qt 6 / PySide6(LGPL-3.0), segno(BSD-3-Clause), pi-heif(BSD-3-Clause) / libheif·libde265(LGPL-3.0), Pillow(MIT-CMU). 자세한 내용은 [licenses/THIRD_PARTY_NOTICES.txt](licenses/THIRD_PARTY_NOTICES.txt)에 있습니다.
