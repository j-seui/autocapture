param([string]$Python = "python")
$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot
try {
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "가상환경 생성 실패" }
    & .\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw "패키지 설치 실패" }
    & .\.venv\Scripts\python.exe -c "import tkinter as t; r=t.Tk(); r.withdraw(); r.destroy()"
    if ($LASTEXITCODE -ne 0) { throw "Tcl/Tk 초기화 실패: Tcl/Tk가 포함된 Python 환경에서 빌드하세요." }
    & .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name BloombergAutoCapture main.py
    if ($LASTEXITCODE -ne 0) { throw "EXE 빌드 실패" }
    Write-Host "완료: $PSScriptRoot\dist\BloombergAutoCapture.exe"
} finally {
    Pop-Location
}
