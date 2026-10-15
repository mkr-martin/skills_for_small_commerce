"""레포 맨 위 위치 · 결과물 폴더 위치 — 경로는 여기 한 곳에서만 정한다.

스킬 스크립트(.claude/skills/<스킬>/scripts/<파일>.py)가 공통 부품을 부르는 표준 3줄:

    ROOT = Path(__file__).resolve().parents[4]   # scripts → <스킬> → skills → .claude → 루트
    sys.path.insert(0, str(ROOT))
    from shared import env, ledger, store_profile

(스크립트가 스킬 폴더 바로 아래에 있으면 parents[3]. 깊이가 다르면 숫자만 바꾼다.)

결과물은 전부 레포 맨 위 `output/` 한 폴더 아래(.gitignore · 업데이트 때 이 폴더만 옮기면 된다):
    output/수집/ · output/상세페이지/ · output/레퍼런스/ · output/문의/ · output/매대/ · output/dashboard.html
"""
from __future__ import annotations

from pathlib import Path

OUTPUT = "output"


def repo_root() -> Path:
    """레포 맨 위 = 이 파일(shared/paths.py)의 한 단계 위."""
    return Path(__file__).resolve().parents[1]


def output_dir(*parts: str) -> Path:
    """결과물 폴더(레포 맨 위 output/) 또는 그 아래 경로. 예: output_dir("매대", "매핑표.csv")."""
    return repo_root().joinpath(OUTPUT, *parts)


def show_path(path: Path | str) -> str:
    """사장님께 보여 줄 경로 — 레포 안이면 레포 맨 위 기준 상대경로, 밖이면 그대로."""
    p = Path(path)
    try:
        return str(p.resolve().relative_to(repo_root()))
    except ValueError:
        return str(p)
