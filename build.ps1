# Hwik 배포본 만들기 (Windows PowerShell 5.1 / 7)
#   .\build.ps1  →  dist\Hwik\  +  dist\Hwik_win.zip
# 직접 만든 exe(PyInstaller 등)를 쓰지 않는다: 스마트 앱 컨트롤이 서명·평판 없는 exe를 막는다.
# 배포본 = Python 재단이 서명한 실행 파일 + 앱. zip을 풀고 Hwik.exe를 실행하면 스스로 설치한다(selfinstall.py).
param(
    # 준비해 둔 임베디드 Python 3.12(서명된 pythonw.exe가 든 폴더). 읽기만 하고 고치지 않는다.
    # 여기서는 Python 본체만 가져오고, 패키지는 이 프로젝트의 .venv에서 필요한 것만 골라 담는다.
    [string]$RuntimeDir = (Join-Path $PSScriptRoot "..\Converter\transformer\vendor\python-runtime"),
    [switch]$SkipTests
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$name = "Hwik"
$py = ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "가상 환경(.venv)이 없습니다" }
if (-not (Test-Path "$RuntimeDir\pythonw.exe")) { throw "Python 런타임이 없습니다: $RuntimeDir" }

if (-not $SkipTests) {
    $env:PYTHONUTF8 = "1"
    & $py -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "시험 실패: 만들기를 중단합니다" }
}

$env:PYTHONPATH = "src"
& $py scripts\make_icon_files.py
if ($LASTEXITCODE -ne 0) { throw "아이콘 만들기 실패" }
Remove-Item Env:PYTHONPATH

function Assert-Signed([string]$Path, [string]$Signer) {
    $sig = Get-AuthenticodeSignature $Path
    if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notlike "*$Signer*") {
        throw "$Path 의 서명을 확인할 수 없습니다: 만들기를 중단합니다"
    }
}

$stage = "dist\$name"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force "$stage\runtime\Lib\site-packages" | Out-Null

# 1) Python 본체: 런타임 폴더 맨 위의 파일만(표준 라이브러리 zip, 확장 모듈, DLL). 다른 앱용 패키지(Lib)는 담지 않는다.
Get-ChildItem $RuntimeDir -File | Where-Object { $_.Name -notin "python.exe", "pythonw.exe", "python312._pth" } |
    Copy-Item -Destination "$stage\runtime" -Force
Copy-Item "$RuntimeDir\pythonw.exe" "$stage\$name.exe"
Assert-Signed "$stage\$name.exe" "Python Software Foundation"
Copy-Item "$RuntimeDir\python312.dll", "$RuntimeDir\python3.dll", "$RuntimeDir\vcruntime140.dll", "$RuntimeDir\vcruntime140_1.dll" $stage -Force
# 맨 위 exe가 쓰는 경로: 표준 라이브러리·확장 모듈은 runtime, 패키지는 site-packages, 앱은 app
@("runtime\python312.zip", "runtime", "runtime\Lib\site-packages", "app", "import site") |
    Set-Content "$stage\python312._pth" -Encoding ascii

# 2) 패키지: 화면 부품(PySide6)에서 Hwik이 쓰는 것만 골라 담는다(전체 215MB 중 일부). 빠진 것이 있으면 아래 점검에서 걸린다.
$venvSite = ".venv\Lib\site-packages"
$site = "$stage\runtime\Lib\site-packages"
$qtSrc = "$venvSite\PySide6"
$qtDst = "$site\PySide6"
New-Item -ItemType Directory -Force $qtDst | Out-Null
$qtFiles = @(
    "__init__.py", "_config.py", "_git_pyside_version.py", "pyside6.abi3.dll",
    "Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll", "Qt6Network.dll",
    "QtCore.pyd", "QtGui.pyd", "QtWidgets.pyd", "QtNetwork.pyd",
    "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "vcruntime140.dll", "vcruntime140_1.dll"
)
foreach ($file in $qtFiles) { Copy-Item "$qtSrc\$file" $qtDst -Force }
foreach ($dll in "Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll", "Qt6Network.dll") { Assert-Signed "$qtDst\$dll" "The Qt Company" }
$plugins = @{ "platforms" = @("qwindows.dll"); "styles" = @("qmodernwindowsstyle.dll"); "imageformats" = @("qjpeg.dll", "qico.dll") }
foreach ($folder in $plugins.Keys) {
    New-Item -ItemType Directory -Force "$qtDst\plugins\$folder" | Out-Null
    foreach ($file in $plugins[$folder]) { Copy-Item "$qtSrc\plugins\$folder\$file" "$qtDst\plugins\$folder" -Force }
}
if (Test-Path "$qtSrc\support") { robocopy "$qtSrc\support" "$qtDst\support" /E /XD __pycache__ /XF *.pyc /NJH /NJS /NP | Out-Null }
foreach ($pkg in "shiboken6", "segno") {
    robocopy "$venvSite\$pkg" "$site\$pkg" /E /XD __pycache__ /XF *.pyc *.pyi *.lib /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "$pkg 복사 실패" }
}
# 아이폰 사진(HEIC)을 붙여넣을 그림으로 푸는 부품: pi_heif와 그것이 쓰는 Pillow.
foreach ($pkg in "PIL", "pi_heif") {
    robocopy "$venvSite\$pkg" "$site\$pkg" /E /XD __pycache__ /XF *.pyc *.pyi /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "$pkg 복사 실패" }
}
# pi_heif의 해독 라이브러리(DLL)는 패키지 폴더 밖에 놓인다. 설치 기록에 적힌 것만 골라 담는다(개발용 부품의 DLL이 섞이지 않게).
$heifRecord = (Get-ChildItem "$venvSite\pi_heif-*.dist-info\RECORD").FullName
$heifFiles = @(Get-Content $heifRecord | ForEach-Object { ($_ -split ",")[0] } | Where-Object { $_ -match '^[^/\\]+\.(dll|pyd)$' })
if ($heifFiles.Count -lt 2) { throw "pi_heif의 해독 라이브러리를 찾지 못했습니다" }
foreach ($file in $heifFiles) { Copy-Item "$venvSite\$file" $site -Force }
$global:LASTEXITCODE = 0

# 3) 앱과 그림, 라이선스
robocopy "src\hwik" "$stage\app\hwik" /MIR /XD __pycache__ /XF *.pyc /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "앱 복사 실패" }
$global:LASTEXITCODE = 0
Copy-Item "installer\sitecustomize.py" "$stage\app\" -Force
New-Item -ItemType Directory -Force "$stage\assets", "$stage\licenses\packages" | Out-Null
Copy-Item "assets\hwik.ico" "$stage\assets\" -Force
Copy-Item "licenses\*" "$stage\licenses\" -Force
if (Test-Path "LICENSE") { Copy-Item "LICENSE" "$stage\licenses\Hwik-LICENSE.txt" -Force }
Copy-Item "$RuntimeDir\LICENSE.txt" "$stage\licenses\packages\Python-LICENSE.txt" -Force
Get-ChildItem "$venvSite\*.dist-info" -Directory | Where-Object { $_.Name -match '^(pyside6_essentials|shiboken6|segno|pillow|pi_heif)-' } | ForEach-Object {
    $files = @(Get-ChildItem $_.FullName -Recurse -File | Where-Object { $_.Name -match '^(LICEN[CS]E|COPYING|NOTICE|AUTHORS)' -or $_.DirectoryName -like '*\licenses*' })
    if ($files) {
        $dst = New-Item -ItemType Directory -Force "$stage\licenses\packages\$($_.Name -replace '\.dist-info$', '')"
        $files | Copy-Item -Destination $dst -Force
    }
}

# 4) 만든 배포본을 직접 실행해 점검한다(빠진 파일은 다른 사람 PC가 아니라 여기서 드러나게)
$report = "$env:TEMP\${name}_selftest.txt"
Remove-Item $report -ErrorAction SilentlyContinue
$check = Start-Process "$stage\$name.exe" -ArgumentList "-m hwik --selftest" -WorkingDirectory $stage -PassThru
if (-not $check.WaitForExit(120000)) { $check.Kill(); throw "자체 점검이 끝나지 않았습니다" }
if (Test-Path $report) { Get-Content $report -Encoding UTF8 | Write-Host }
if ($check.ExitCode -ne 0) { throw "자체 점검 실패(종료 코드 $($check.ExitCode))" }

# 5) zip으로 묶기
& $py scripts\package.py $name
if ($LASTEXITCODE -ne 0) { throw "zip 만들기 실패" }
Write-Host "완료: $stage\$name.exe"
