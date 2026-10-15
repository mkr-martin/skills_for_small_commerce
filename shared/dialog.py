"""맥 기본 입력 창(osascript display dialog) — 사장님 화면에 창을 띄워 값을 받는다. 표준 라이브러리만.

    from shared import dialog
    v = dialog.ask("…를 붙여넣으세요", hidden=True)   # 취소 → None
    ok = dialog.confirm("덮어쓸까요?", yes="덮어쓰기", no="그대로 두기")
    dialog.show("끝났습니다")

받은 값은 돌려주기만 한다 — 이 모듈은 값을 화면·로그에 찍지 않는다.
문구는 osascript 인자(argv)로 넘겨 따옴표·특수문자에 안전하다.
창은 10분까지 기다린다(AppleScript 기본 2분 제한을 넘겨 천천히 붙여넣어도 되게).
"""
from __future__ import annotations

import subprocess

TITLE = "스몰 커머스 스킬"
WAIT_SEC = 600

_ASK = """on run argv
  with timeout of {wait} seconds
    set r to display dialog (item 1 of argv) default answer "" {hidden}buttons {{"건너뛰기", "확인"}} default button "확인" cancel button "건너뛰기" with title "{title}"
  end timeout
  return text returned of r
end run"""

_CONFIRM = """on run argv
  with timeout of {wait} seconds
    set r to display dialog (item 1 of argv) buttons {{(item 2 of argv), (item 3 of argv)}} default button 1 cancel button 1 with title "{title}"
  end timeout
  return button returned of r
end run"""

_SHOW = """on run argv
  with timeout of {wait} seconds
    display dialog (item 1 of argv) buttons {{"확인"}} default button "확인" with title "{title}"
  end timeout
end run"""


def _run(script: str, *args: str) -> str | None:
    """osascript 실행 → 표준출력(끝 줄바꿈 뺀 것). 취소·오류면 None. 출력은 여기서 찍지 않는다."""
    r = subprocess.run(["osascript", "-e", script, "--", *args], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return r.stdout[:-1] if r.stdout.endswith("\n") else r.stdout


def ask(message: str, hidden: bool = False) -> str | None:
    """입력 창 하나. 확인 → 입력한 글자 · 건너뛰기(취소) → None."""
    script = _ASK.format(wait=WAIT_SEC, title=TITLE, hidden="with hidden answer " if hidden else "")
    return _run(script, message)


def confirm(message: str, yes: str = "예", no: str = "아니오") -> bool:
    """두 단추 창. yes 를 눌렀을 때만 True(기본 단추 = no)."""
    return _run(_CONFIRM.format(wait=WAIT_SEC, title=TITLE), message, no, yes) == yes


def show(message: str) -> None:
    """알림 창(확인 단추 하나)."""
    _run(_SHOW.format(wait=WAIT_SEC, title=TITLE), message)
