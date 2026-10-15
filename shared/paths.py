"""레포 맨 위 위치 · 결과물 폴더 위치 — 경로는 여기 한 곳에서만 정한다.

스킬 스크립트(.claude/skills/<스킬>/scripts/<파일>.py)가 공통 부품을 부르는 표준 3줄:

    ROOT = Path(__file__).resolve().parents[4]   # scripts → <스킬> → skills → .claude → 루트
    sys.path.insert(0, str(ROOT))
    from shared import env, ledger, store_profile

(스크립트가 스킬 폴더 바로 아래에 있으면 parents[3]. 깊이가 다르면 숫자만 바꾼다.)

결과물은 스킬마다 레포 맨 위 `output_<스킬>/` 한 폴더(.gitignore 의 `output_*/`):
    output_<스킬>/<yyyymmdd_hhmm>_<이름>/   ← 한 번 실행 = 폴더 하나   run_dir("detail-page", "하루양말")
    output_<스킬>/원장.md · 재고표.csv …    ← 계속 쌓는 장부는 맨 위     skill_root("shelf-check") / "재고표.csv"
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
NAME_MAX = 40


def repo_root() -> Path:
    """레포 맨 위 = 이 파일(shared/paths.py)의 한 단계 위."""
    return Path(__file__).resolve().parents[1]


def skill_root(skill: str, *, root: Path | None = None) -> Path:
    """스킬 결과물 폴더 `<레포 맨 위>/output_<skill>/` — 없으면 만든다. root 는 테스트용(기본 = 레포 맨 위)."""
    d = Path(root or repo_root()) / f"output_{skill}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def clean_name(name: str) -> str:
    """폴더 이름에 넣을 수 있게 — / \\ : 제거, 공백 → _, 40자에서 자름. 한글은 그대로."""
    s = re.sub(r"[/\\:]", "", name or "")
    s = re.sub(r"\s+", "_", s.strip())
    return s[:NAME_MAX].strip("_")


def run_dir(skill: str, name: str = "", *, root: Path | None = None, now: datetime | None = None) -> Path:
    """한 번 실행의 결과물 폴더 `output_<skill>/<yyyymmdd_hhmm>_<name>/`(name 이 비면 `<yyyymmdd_hhmm>`)를 만들어 돌려준다.

    시각은 KST. 같은 분에 같은 이름이 이미 있으면 `_2`, `_3` … 을 붙여 새로 만든다(앞 결과를 덮지 않는다).
    root · now 는 테스트용.
    """
    stamp = (now or datetime.now(KST)).astimezone(KST).strftime("%Y%m%d_%H%M")
    n = clean_name(name)
    base = f"{stamp}_{n}" if n else stamp
    parent = skill_root(skill, root=root)
    i = 1
    while True:
        d = parent / (base if i == 1 else f"{base}_{i}")
        try:
            d.mkdir()
            return d
        except FileExistsError:
            i += 1


def show_path(path: Path | str) -> str:
    """사장님께 보여 줄 경로 — 레포 안이면 레포 맨 위 기준 상대경로, 밖이면 그대로."""
    p = Path(path)
    try:
        return str(p.resolve().relative_to(repo_root()))
    except ValueError:
        return str(p)
