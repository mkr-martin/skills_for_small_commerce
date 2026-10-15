"""미답변 문의 모으기 — 채널 API 로 읽어 output/문의/문의함.csv 맨 아래에 덧붙인다. (읽기만 · 고객에게 아무것도 안 보냄)

    python3 .claude/skills/inquiry-inbox/scripts/fetch.py                  # 키가 있는 채널 전부 · 최근 7일
    python3 .claude/skills/inquiry-inbox/scripts/fetch.py --days 14        # 최근 14일
    python3 .claude/skills/inquiry-inbox/scripts/fetch.py --channel naver  # 한 채널만 (naver · coupang · cafe24)
    python3 .claude/skills/inquiry-inbox/scripts/fetch.py --cafe24-boards  # 카페24 게시판 번호 목록만 보기

이미 표에 있는 id 는 건너뛴다 — 사장님이 써 둔 답변·상태는 그대로 남는다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]   # scripts → inquiry-inbox → skills → .claude → 루트 (루트 CLAUDE.md §5 표준 머리)
sys.path.insert(0, str(ROOT))
from shared.channels import ChannelError  # noqa: E402
from shared.env import MissingKeyError  # noqa: E402
from shared.paths import show_path  # noqa: E402

from common import inbox_paths, read_inbox, write_inbox  # noqa: E402  같은 폴더
from inquiries import FETCH, LABEL, MODULE, cafe24_boards  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="미답변 문의를 문의함.csv 로 모은다")
    ap.add_argument("--days", type=int, default=7, help="며칠 전 문의까지 (기본 7)")
    ap.add_argument("--channel", choices=sorted(FETCH), help="이 채널만")
    ap.add_argument("--dir", default=None, help="문의함 폴더 (기본 = 레포 맨 위 output/문의/)")
    ap.add_argument("--cafe24-boards", action="store_true", help="카페24 게시판 번호 목록만 출력")
    args = ap.parse_args()

    if args.cafe24_boards:
        if not MODULE["cafe24"].configured():
            print("카페24: 키 없음 (" + ", ".join(MODULE["cafe24"].KEYS) + ")")
            return 1
        try:
            for b in cafe24_boards():
                print(f"  {b.get('board_no')}\t{b.get('board_name')}\t(분류 {b.get('board_type')})")
        except (ChannelError, MissingKeyError) as e:
            print(f"카페24: 실패 — {e}")
            return 1
        print("→ 문의 게시판 번호를 넣으려면: python3 shared/setup_keys.py --key CAFE24_INQUIRY_BOARDS (창에 쉼표로, 예: 6,9)")
        return 0

    _, inbox = inbox_paths(args.dir)
    rows = read_inbox(inbox)
    known = {r["id"] for r in rows}
    total_new = 0
    for key, fetch in FETCH.items():
        if args.channel and key != args.channel:
            continue
        if not MODULE[key].configured():
            print(f"{LABEL[key]}: 키 없음 — 건너뜀 ({', '.join(MODULE[key].KEYS)} 중 빈 칸)")
            continue
        try:
            got = fetch(args.days)
        except (ChannelError, MissingKeyError) as e:
            print(f"{LABEL[key]}: 실패 — {e}")
            continue
        except (KeyError, TypeError, ValueError) as e:   # 응답 모양이 문서와 다름 — 이 채널만 건너뛴다
            print(f"{LABEL[key]}: 실패 — 응답 모양이 예상과 다릅니다({type(e).__name__}: {e}). 이 채널은 건너뜁니다.")
            continue
        new = []
        for r in got:
            if r["id"] not in known:     # 표에 있던 것 · 이번에 겹쳐 온 것 모두 한 번만
                known.add(r["id"])
                new.append(r)
        rows += new
        total_new += len(new)
        print(f"{LABEL[key]}: 미답변 {len(got)}건 중 새로 {len(new)}건 추가")

    write_inbox(inbox, rows)
    waiting = sum(1 for r in rows if r.get("상태", "") == "미답변")
    print(f"\n문의함: {show_path(inbox)}  (새로 {total_new}건 · 상태가 미답변인 문의 {waiting}건)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
