"""원장.md — 스킬 결과물 폴더 맨 위(output_<스킬>/원장.md)의 마크다운 표 한 장. 맨 아래 한 줄 추가만 한다(전체 재작성 금지).

    from shared import ledger
    from shared.paths import skill_root
    ledger.append(skill_root("detail-page") / "원장.md", {"날짜": "2026-10-14", "가게": "하루양말", ...})
    rows = ledger.read(skill_root("detail-page") / "원장.md")   # → [{"날짜": …, "가게": …}, …]

세션에서 한 줄 붙일 때(스크립트 밖) — 같은 append 를 터미널로:
    python3 shared/ledger.py output_detail-page/원장.md '{"날짜": "2026-10-14", "가게": "하루양말", ...}'

- 파일이 없으면: 첫 row 의 키 순서로 헤더를 만들고 한 줄 쓴다.
- 파일이 있으면: 기존 헤더의 열 순서를 지킨다. 헤더에 없는 키가 오면 오류(열 고정).
  빠진 열은 빈 칸.
- 셀 안의 `|` 는 `\\|`, 줄바꿈은 `<br>` 로 바꾼다.
- 표 아래에 다른 글이 있으면 오류(표가 끊긴다 — 사람이 정리한다).
"""
from __future__ import annotations

import os
from pathlib import Path


class LedgerError(ValueError):
    pass


def _cell(v: object) -> str:
    s = "" if v is None else str(v)
    s = s.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")
    return s.replace("|", "\\|").strip()


def _split_header(line: str) -> list[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [c.strip() for c in inner.split("|")]


def _row(cols: list[str], row: dict) -> str:
    return "| " + " | ".join(_cell(row.get(c, "")) for c in cols) + " |"


def header(path: Path) -> list[str]:
    """원장의 열 이름들(첫 번째 `|` 줄)."""
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if line.strip().startswith("|"):
            return _split_header(line)
    raise LedgerError(f"{path}: 표 머리줄(| 로 시작)을 찾지 못했습니다.")


def _split_cells(line: str) -> list[str]:
    """표 한 줄 → 칸들. `\\|` 는 칸 경계가 아니라 글자 | 이고, `<br>` 은 줄바꿈으로 되돌린다(append 의 역변환)."""
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|") and not inner.endswith("\\|"):
        inner = inner[:-1]
    cells, buf, i = [], [], 0
    while i < len(inner):
        ch = inner[i]
        if ch == "\\" and i + 1 < len(inner) and inner[i + 1] == "|":
            buf.append("|"); i += 2; continue
        if ch == "|":
            cells.append("".join(buf)); buf = []
        else:
            buf.append(ch)
        i += 1
    cells.append("".join(buf))
    return [c.strip().replace("<br>", "\n") for c in cells]


def _is_sep(cells: list[str]) -> bool:
    return bool(cells) and all(c and set(c.replace(":", "")) == {"-"} for c in cells)


def read(ledger_path: Path | str) -> list[dict]:
    """원장의 줄들 → [{열 이름: 값}, …] (원장 순서 그대로 · 열 순서 = 머리줄 순서).

    - 파일이 없으면 빈 목록.
    - 첫 `|` 줄 = 머리줄, 다음 줄 = 구분줄(---). 그 뒤로 이어지는 `|` 줄만 읽는다.
    - 칸이 모자란 줄은 빈 칸으로 채운다. 칸이 넘치는 줄은 LedgerError(손으로 고치다 `|` 가 들어간 것 — 사람이 고친다).
    """
    path = Path(ledger_path)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.strip().startswith("|")), None)
    if start is None:
        return []
    cols = _split_cells(lines[start])
    if start + 1 >= len(lines) or not _is_sep(_split_cells(lines[start + 1])):
        raise LedgerError(f"{path}: 머리줄 다음에 구분줄(|---|)이 없습니다.")
    rows = []
    for n, ln in enumerate(lines[start + 2:], start + 3):
        if not ln.strip().startswith("|"):
            break
        cells = _split_cells(ln)
        if len(cells) > len(cols):
            raise LedgerError(f"{path} {n}행: 칸이 {len(cells)}개(열은 {len(cols)}개) — 칸 안의 | 는 \\| 로 적어야 합니다.")
        cells += [""] * (len(cols) - len(cells))
        rows.append(dict(zip(cols, cells)))
    return rows


def append(ledger_path: Path | str, row: dict) -> None:
    path = Path(ledger_path)
    if not row:
        raise LedgerError("빈 row 는 쓰지 않습니다.")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        cols = list(row.keys())
        text = ("| " + " | ".join(_cell(c) for c in cols) + " |\n"
                + "|" + "---|" * len(cols) + "\n"
                + _row(cols, row) + "\n")
        path.write_text(text, encoding="utf-8")
        return

    cols = header(path)
    extra = [k for k in row if k not in cols]
    if extra:
        raise LedgerError(f"{path}: 원장에 없는 열 {extra} — 열은 고정입니다(있는 열: {cols}).")
    raw = path.read_bytes()                       # 바이트 기준 — CRLF 파일에서도 자를 위치가 정확하다
    body = raw.rstrip(b" \t\r\n")
    last = body.splitlines()[-1].decode("utf-8") if body else ""
    if not last.strip().startswith("|"):
        raise LedgerError(f"{path}: 표 아래에 다른 글이 있어 한 줄을 붙이면 표가 끊깁니다. 표를 파일 맨 아래로 정리해 주세요.")
    nl = b"\r\n" if b"\r\n" in raw else b"\n"
    with open(path, "r+b") as f:                  # 끝 빈 줄만 잘라 내고 한 줄 덧붙인다
        f.seek(len(body))
        f.truncate()
        f.write(nl + _row(cols, row).encode("utf-8") + nl)
        f.flush()
        os.fsync(f.fileno())


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) != 3:
        sys.exit("사용법: python3 shared/ledger.py <원장.md 경로> '<한 줄 JSON>'")
    try:
        new_row = json.loads(sys.argv[2])
        if not isinstance(new_row, dict):
            raise LedgerError('한 줄은 {"열": "값", …} 꼴의 JSON 이어야 합니다.')
        append(sys.argv[1], new_row)
    except ValueError as e:     # JSON 오류 · 열 고정 위반 · 표 아래 다른 글(LedgerError 도 ValueError)
        sys.exit(f"원장에 붙이지 못했습니다 — {e}")
    print(f"원장 맨 아래에 한 줄 추가: {sys.argv[1]}")
