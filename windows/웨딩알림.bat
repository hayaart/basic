@echo off
chcp 65001 >nul
rem 작업 등록이 권한 때문에 막히는 일이 있어 관리자로 올린다. 같은 계정으로 올라가야 한다.
net session >nul 2>&1 || (powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs" & exit /b)
cd /d "%~dp0"
:menu
cls
echo ==================================
echo    삼성 웨딩홀 빈자리 알림
echo ==================================
echo   1. 테스트 (지금 한 번 확인 + 텔레그램 테스트)
echo   2. 전체 설치 (자동감시 + 상태/버튼 대화봇)
echo   3. 전체 해제
echo   0. 종료
echo ----------------------------------
set /p sel=번호 입력 후 Enter:
if "%sel%"=="1" ( powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0wedding.ps1" test & pause )
if "%sel%"=="2" ( powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0wedding.ps1" install & pause )
if "%sel%"=="3" ( powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0wedding.ps1" uninstall & pause )
if "%sel%"=="0" exit
goto menu
