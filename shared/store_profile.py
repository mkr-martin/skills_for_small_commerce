"""브랜드_SSOT.md 읽기 — 스크립트가 필요한 값만 꺼낸다(나머지는 클로드가 문서로 읽는다).

    from shared import store_profile
    n = store_profile.low_stock()          # "- 저재고 기준: 10개" → 10 (없으면 default)
    a = store_profile.color_aliases()      # "- 색 별칭: 블랙 = 검정 = black · ..." → {"검정": "블랙", ...}
    store_profile.is_filled()              # 템플릿 그대로면 False — 스킬은 파일 존재가 아니라 이것으로 판단

브랜드_SSOT.md 는 레포에 늘 있고 처음엔 빈 템플릿이다. 채우는 건 선택 — 비어 있어도 모든 스킬이 돈다.
터미널: python3 shared/store_profile.py   → "채워짐" 또는 "비어 있음(템플릿 그대로)"
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

if __name__ == "__main__":   # 파일로 직접 실행 — 어느 폴더에서든 shared 를 찾게(루트 CLAUDE.md §5 표준 머리)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.paths import repo_root  # noqa: E402

# 템플릿에 처음부터 적혀 있는 기본값 — 이것만 있으면 '채워짐'으로 치지 않는다 (라벨 일부, 값)
TEMPLATE_DEFAULTS = {("저재고 기준", "10개")}
_MARK_RE = re.compile(r"^(?:[-*+]|\d+\.)\s*")
LOW_STOCK_RE = re.compile(r"저재고[^0-9\n]*(\d+)")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def read(path: Path | None = None) -> str:
    """브랜드_SSOT.md 본문(HTML 주석 <!-- --> 은 뺀다 — 템플릿 안내 문구가 값으로 읽히지 않게).

    브랜드_SSOT.md 는 선택이다 — 없거나 · 비었거나 · 못 읽으면(폴더·인코딩 깨짐) 빈 문자열(예외 없음).
    그러면 low_stock() = default · color_aliases() = {}."""
    p = path or (repo_root() / "브랜드_SSOT.md")
    try:
        text = p.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return ""
    return _COMMENT_RE.sub("", text)


def low_stock(default: int = 10, path: Path | None = None) -> int:
    m = LOW_STOCK_RE.search(read(path))
    return int(m.group(1)) if m else default


def color_aliases(path: Path | None = None) -> dict[str, str]:
    """'색 별칭' 이 들어간 줄들 → {별칭: 대표색}. 대표색 = 각 묶음의 첫 이름(자기 자신도 포함).

    한 줄 형식: `- 색 별칭(설명): 블랙 = 검정 = black · 베이지 = 살구`
    묶음 구분 = `·` 또는 `,` 또는 `;` · 이름 구분 = `=`. 비교는 소문자·앞뒤 공백 제거 키로.
    """
    out: dict[str, str] = {}
    for line in read(path).splitlines():
        if "색 별칭" not in line or ":" not in line:
            continue
        body = line.split(":", 1)[1]
        for group in re.split(r"[·,;]", body):
            names = [n.strip() for n in group.split("=") if n.strip()]
            if len(names) < 2:
                continue
            canon = names[0]
            for n in names:
                out[n.lower()] = canon
    return out


def _is_sep(cells: list[str]) -> bool:
    return bool(cells) and all(c and set(c.replace(":", "")) <= {"-"} for c in cells)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def is_filled(path: Path | None = None) -> bool:
    """사장님이 적은 값이 하나라도 있으면 True. 템플릿 그대로 · 빈 파일 · 파일 없음이면 False.

    값으로 치지 않는 것: 안내 주석(<!-- -->) · 제목(#) · 인용 안내(>) · html 태그 줄(<details> 등) ·
    표 머리줄·구분줄·빈 칸 줄 · `- 라벨:` 처럼 콜론 뒤가 빈 줄 · 목록 기호만 있는 줄 · TEMPLATE_DEFAULTS.
    """
    lines = read(path).splitlines()
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line or line[0] in "#><":
            continue
        if line.startswith("|"):
            cells = _cells(line)
            if _is_sep(cells):
                continue
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if nxt.startswith("|") and _is_sep(_cells(nxt)):
                continue                                  # 표 머리줄
            if any(cells):
                return True
            continue
        body = _MARK_RE.sub("", line)
        label, colon, value = body.partition(":")
        value = (value if colon else body).strip()
        if not value:
            continue
        if colon and any(k in label and value == v for k, v in TEMPLATE_DEFAULTS):
            continue
        return True
    return False


if __name__ == "__main__":
    print("채워짐" if is_filled() else "비어 있음(템플릿 그대로)")
