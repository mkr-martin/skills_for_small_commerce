"""레포 루트 `.env` 읽기 — 표준 라이브러리만(외부 dotenv 패키지 없이).

    from shared import env
    key = env.get("GEMINI_API_KEY", required=True)

규칙: 셸 환경변수에 값이 있으면 그것을, 없으면 루트 `.env` 를 쓴다.
값은 화면에 찍지 않는다(오류 문장에도 키 이름만).
"""
from __future__ import annotations

import os
from pathlib import Path

from .paths import repo_root

HELP = "클로드 코드에 '키 넣어줘' 라고 하면 창이 뜹니다(= python3 shared/setup_keys.py) · 발급 방법은 README '키 발급' 절(채팅창에 키를 붙여넣지 마세요)."


class MissingKeyError(RuntimeError):
    """필요한 키가 비어 있다 — 사장님이 읽을 문장을 담는다."""


def _parse_line(line: str) -> tuple[str, str] | None:
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    if line.startswith("export "):
        line = line[len("export "):].lstrip()
    name, _, value = line.partition("=")
    name, value = name.strip(), value.strip()
    if not name:
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]                 # 따옴표 안의 # 은 값의 일부
    else:
        cut = value.find(" #")              # 따옴표 없는 값 뒤 주석은 떼어 낸다
        if cut != -1:
            value = value[:cut].rstrip()
    return name, value


def load(path: Path | None = None) -> dict[str, str]:
    """`.env` 전체를 dict 로. 파일이 없으면 빈 dict."""
    p = path or (repo_root() / ".env")
    if not p.exists():
        return {}
    out: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        kv = _parse_line(line)
        if kv:
            out[kv[0]] = kv[1]
    return out


def get(name: str, required: bool = False, path: Path | None = None) -> str | None:
    """키 값. 없거나 비었으면 None — required=True 면 MissingKeyError."""
    value = os.environ.get(name) or load(path).get(name) or None
    if value is None and required:
        where = path or (repo_root() / ".env")
        raise MissingKeyError(f"{name} 가 비어 있습니다({where}). {HELP}")
    return value
