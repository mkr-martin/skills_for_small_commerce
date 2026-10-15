"""문의함 공통 — 문의함.csv 읽고 쓰기 · 마스킹 · 시각. (키·채널 API 는 루트 shared/)

표준 라이브러리만 쓴다(맥 기본 python3 3.9 이상).
"""
from __future__ import annotations

import csv
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]   # scripts → inquiry-inbox → skills → .claude → 루트 (루트 CLAUDE.md §5 표준 머리)
sys.path.insert(0, str(ROOT))
from shared.paths import output_dir  # noqa: E402

KST = timezone(timedelta(hours=9))

# 문의함.csv 열 — 순서 고정. 사장님이 엑셀로 여는 표라 열 이름은 한국어.
# 답변·상태 열은 사장님 메모용(스크립트는 비워서 만들고 다시 건드리지 않는다).
COLUMNS = ["id", "채널", "종류", "접수일", "상품", "고객", "문의 원문", "답변", "상태"]
ST_NEW = "미답변"

INBOX_NAME = "문의함.csv"


# ---------------------------------------------------------------- 시각
def now_kst() -> datetime:
    return datetime.now(KST)


def stamp(dt: datetime | None = None) -> str:
    return (dt or now_kst()).strftime("%Y-%m-%d %H:%M")


def to_kst_text(value) -> str:
    """API 가 주는 ISO 시각 문자열을 'YYYY-MM-DD HH:MM'(한국시간)로. 못 읽으면 앞 16자."""
    if not value:
        return ""
    s = str(value).strip().replace("Z", "+00:00")
    # 파이썬 3.9 fromisoformat 은 소수점 3·6자리만 받는다 → 6자리로 맞춘다
    m = re.match(r"^(.*T\d{2}:\d{2}:\d{2})(\.\d+)?(.*)$", s)
    if m:
        frac = (m.group(2) or ".0")[1:]
        s = f"{m.group(1)}.{(frac + '000000')[:6]}{m.group(3)}"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return str(value)[:16].replace("T", " ")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return stamp(dt.astimezone(KST))


# ---------------------------------------------------------------- 마스킹
def mask_name(name) -> str:
    """홍길동 → 홍*동 · 홍길 → 홍* · 영문/아이디 → 앞 3자 + ***."""
    s = (name or "").strip()
    if not s:
        return ""
    if "*" in s:            # 채널이 이미 가려서 준 값
        return s
    if re.fullmatch(r"[가-힣]{2,5}", s):
        return s[0] + "*" * (len(s) - 2) + s[-1] if len(s) >= 3 else s[0] + "*"
    return s[:3] + "***"


# ---------------------------------------------------------------- 문의함.csv
def inbox_paths(work_dir: str | None) -> tuple:
    """기본 = 레포 맨 위 output/문의/(.gitignore 됨). --dir 로 바꿀 수 있다."""
    d = Path(work_dir) if work_dir else output_dir("문의")
    return d, d / INBOX_NAME


def _read_text_any(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp949"):   # 엑셀이 다른 인코딩으로 저장해도 읽는다
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"{path} 를 읽을 수 없습니다 — 엑셀에서 'CSV UTF-8' 로 다시 저장해 주세요.")


def read_inbox(path: Path) -> list:
    """표 전체. 사장님이 덧붙인 열(메모 등)도 그대로 들고 있다가 write_inbox 가 되살려 쓴다."""
    if not path.exists():
        return []
    import io
    reader = csv.DictReader(io.StringIO(_read_text_any(path)))
    if reader.fieldnames is not None and "id" not in reader.fieldnames:
        raise SystemExit(f"{path} 첫 줄에 'id' 열이 없습니다 — 열 이름을 지우거나 바꾸지 말아 주세요.")
    return [{k: (v or "") for k, v in r.items() if k is not None} for r in reader]


def write_inbox(path: Path, rows: list) -> None:
    """임시 파일에 쓰고 바꿔치기 — 중간에 끊겨도 표가 반쪽이 되지 않는다."""
    fields = list(COLUMNS)
    for r in rows:
        fields += [k for k in r if k not in fields]      # 사장님이 만든 열은 맨 뒤에 그대로
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:   # BOM → 엑셀에서 한글이 안 깨진다
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in fields})
    os.replace(tmp, path)
