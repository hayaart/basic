# 웨딩홀 빈자리 알림 - 윈도우 설치 스크립트
# PowerShell 에서:  powershell -ExecutionPolicy Bypass -File .\install.ps1

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host ""
Write-Host "=================================================="
Write-Host " 웨딩홀 빈자리 알림 - 설치를 시작합니다"
Write-Host "=================================================="
Write-Host ""

function Show-PythonHelp {
    Write-Host "[X] 쓸 수 있는 파이썬(3.10 이상)을 찾지 못했습니다." -ForegroundColor Red
    Write-Host "    https://www.python.org/downloads/ 에서 내려받아 설치하세요."
    Write-Host ""
    Write-Host "    설치 화면 맨 아래 'Add python.exe to PATH' 를 꼭 체크하세요!" -ForegroundColor Yellow
    Write-Host "    설치한 뒤 PowerShell 창을 껐다 켜고 다시 실행하세요."
}

# 파이썬 찾기. 윈도우는 py / python / python3 중 무엇이 있을지 모르고,
# 파이썬이 없으면 'python' 이 마이크로소프트 스토어 안내창으로 연결되기도 한다.
# 그래서 이름만 보지 않고 실제로 버전을 물어봐서 3.10 이상인 것만 고른다.
$pythonExe = $null
$pythonPrefix = @()
$candidates = @(
    , @("py", "-3")
    , @("python")
    , @("python3")
)
foreach ($candidate in $candidates) {
    $name = $candidate[0]
    $prefix = @($candidate | Select-Object -Skip 1)
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) { continue }
    try {
        $reported = & $name @prefix -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    } catch { continue }
    if ($LASTEXITCODE -ne 0 -or -not $reported) { continue }
    $parts = "$reported".Trim().Split(".")
    if ([int]$parts[0] -gt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 10)) {
        $pythonExe = $name
        $pythonPrefix = $prefix
        Write-Host "파이썬 $reported 을(를) 찾았습니다."
        break
    }
}

if (-not $pythonExe) { Show-PythonHelp; exit 1 }

Write-Host "[1/3] 프로그램을 설치하는 중... (1~2분 걸립니다)"
& $pythonExe @pythonPrefix -m venv .venv
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "[X] 가상환경 만들기에 실패했습니다: $venvPython" -ForegroundColor Red
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
