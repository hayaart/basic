"""설치 스크립트가 각 OS 에서 실제로 읽히는 형식인지 검사한다.

install.ps1 이 BOM 없는 UTF-8 이면 윈도우 PowerShell 5.1 이 CP949 로 읽어
한글이 깨지고, 깨진 바이트가 따옴표를 망가뜨려 문법 오류가 줄줄이 난다.
겉보기에는 멀쩡하므로 리눅스/맥에서는 알아채기 어렵다.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UTF8_BOM = b"\xef\xbb\xbf"


def test_powershell_installer_has_utf8_bom():
    raw = (ROOT / "install.ps1").read_bytes()
    assert raw.startswith(UTF8_BOM), (
        "install.ps1 에 UTF-8 BOM 이 없습니다. "
        "윈도우 PowerShell 5.1 이 CP949 로 읽어 한글이 깨지고 문법 오류가 납니다."
    )


def test_powershell_installer_uses_crlf():
    raw = (ROOT / "install.ps1").read_bytes()
    lf_only = raw.count(b"\n") - raw.count(b"\r\n")
    assert lf_only == 0, f"install.ps1 에 CRLF 가 아닌 줄이 {lf_only}개 있습니다."


def test_powershell_installer_avoids_tokens_that_break_in_powershell():
    """PowerShell 문자열 안에서 오해를 부르는 기호를 쓰지 않는지 확인."""
    text = (ROOT / "install.ps1").read_bytes().decode("utf-8-sig")
    probe = [line for line in text.splitlines() if "$versionProbe" in line and "=" in line]
    assert probe, "파이썬 버전 확인용 한 줄 프로그램을 찾지 못했습니다."
    # '%' 는 PowerShell 에서 ForEach-Object 의 별칭이라 파싱을 흔들 수 있다.
    assert "%" not in probe[0]


def test_shell_installer_has_no_carriage_returns():
    raw = (ROOT / "install.sh").read_bytes()
    assert b"\r" not in raw, "install.sh 에 CR 이 있으면 bash 가 실행하지 못합니다."


def test_both_installers_exist_and_are_referenced_in_the_guide():
    guide = (ROOT / "사용설명서.md").read_text(encoding="utf-8")
    assert "install.sh" in guide
    assert "install.ps1" in guide
