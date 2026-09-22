#!/usr/bin/env bash
# 웨딩홀 빈자리 알림 - 설치 스크립트
# 터미널에서:  bash install.sh
set -euo pipefail

cd "$(dirname "$0")"

echo
echo "=================================================="
echo " 웨딩홀 빈자리 알림 - 설치를 시작합니다"
echo "=================================================="
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "❌ python3 이 없습니다."
  echo "   https://www.python.org/downloads/ 에서 설치한 뒤 다시 실행하세요."
  exit 1
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    sys.exit(f"❌ Python 3.10 이상이 필요합니다 (지금: {sys.version.split()[0]})")
PY

echo "[1/3] 프로그램을 설치하는 중... (1~2분 걸립니다)"
python3 -m venv .venv
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -e ".[browser]"

echo "[2/3] 브라우저를 준비하는 중... (2~3분 걸립니다)"
./.venv/bin/playwright install chromium >/dev/null

echo "[3/3] 설치 완료!"
echo
echo "=================================================="
echo " 이제 아래 명령을 순서대로 실행하세요."
echo " (복사해서 터미널에 붙여넣고 Enter)"
echo
echo "   ./.venv/bin/wedding-watch setup"
echo "   ./.venv/bin/wedding-watch test-notify"
echo "   ./.venv/bin/wedding-watch discover"
echo "   ./.venv/bin/wedding-watch run"
echo "=================================================="
