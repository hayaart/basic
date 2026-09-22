# 웨딩홀 빈자리 알림 - 윈도우 설치 스크립트
# PowerShell 에서:  powershell -ExecutionPolicy Bypass -File .\install.ps1
#
# 주의: 이 파일은 반드시 'UTF-8 with BOM' 으로 저장해야 합니다.
# 윈도우 PowerShell 5.1 은 BOM 이 없으면 이 파일을 CP949 로 읽어서 한글이 깨지고,
# 깨진 바이트가 따옴표를 망가뜨려 문법 오류가 줄줄이 발생합니다.

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host ""
Write-Host "=================================================="
Write-Host " 웨딩홀 빈자리 알림 - 설치를 시작합니다"
Write-Host "=================================================="
Write-Host ""

# 파이썬 버전을 물어보는 한 줄짜리 프로그램.
# PowerShell 이 오해할 만한 기호(%, 중괄호)를 쓰지 않는다.
$versionProbe = "import sys; v = sys.version_info; print(str(v[0]) + '.' + str(v[1]))"

# 파이썬 찾기. 윈도우는 py / python / python3 중 무엇이 있을지 모르고,
# 파이썬이 설치돼 있지 않으면 'python' 이 마이크로소프트 스토어 안내창으로
# 연결되기도 한다. 그래서 이름만 보지 않고 실제로 버전을 물어본다.
$pythonExe = $null
$usePyLauncher = $false

foreach ($name in @("py", "python", "python3")) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) { continue }

    $reported = $null
    try {
        if ($name -eq "py") {
            $reported = & $name -3 -c $versionProbe 2>$null
        } else {
            $reported = & $name -c $versionProbe 2>$null
        }
    } catch {
        continue
    }
    if ($LASTEXITCODE -ne 0) { continue }
    if (-not $reported) { continue }

    $text = [string]$reported
    $parts = $text.Trim().Split(".")
    if ($parts.Length -lt 2) { continue }

    $major = 0
    $minor = 0
    if (-not [int]::TryParse($parts[0], [ref]$major)) { continue }
    if (-not [int]::TryParse($parts[1], [ref]$minor)) { continue }

    if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 10)) {
        $pythonExe = $name
        $usePyLauncher = ($name -eq "py")
        Write-Host ("파이썬 " + $text.Trim() + " 을(를) 찾았습니다.")
        break
    }
}

if (-not $pythonExe) {
    Write-Host "[X] 쓸 수 있는 파이썬(3.10 이상)을 찾지 못했습니다." -ForegroundColor Red
    Write-Host "    https://www.python.org/downloads/ 에서 내려받아 설치하세요."
    Write-Host ""
    Write-Host "    설치 화면 맨 아래 'Add python.exe to PATH' 를 꼭 체크하세요!" -ForegroundColor Yellow
    Write-Host "    설치한 뒤 PowerShell 창을 껐다 켜고 다시 실행하세요."
    exit 1
}

Write-Host "[1/3] 프로그램을 설치하는 중... (1~2분 걸립니다)"
if ($usePyLauncher) {
    & $pythonExe -3 -m venv .venv
} else {
    & $pythonExe -m venv .venv
}

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "[X] 가상환경을 만들지 못했습니다." -ForegroundColor Red
    Write-Host "    찾는 위치: $venvPython"
    exit 1
}

& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install --quiet -e ".[browser]"

Write-Host "[2/3] 브라우저를 준비하는 중... (2~3분 걸립니다)"
& $venvPython -m playwright install chromium | Out-Null

Write-Host "[3/3] 설치 완료!"
Write-Host ""
Write-Host "=================================================="
Write-Host " 이제 아래 명령을 순서대로 실행하세요."
Write-Host " (복사해서 붙여넣고 Enter)"
Write-Host ""
Write-Host "   .venv\Scripts\wedding-watch setup"
Write-Host "   .venv\Scripts\wedding-watch test-notify"
Write-Host "   .venv\Scripts\wedding-watch discover"
Write-Host "   .venv\Scripts\wedding-watch run"
Write-Host "=================================================="
