#!/usr/bin/env python3
"""매대 점검 — 재고표.csv 와 매대표.csv 를 맞대어 이상한 칸을 찾는다.

사용: python3 .claude/skills/shelf-check/scripts/shelf_check.py output/매대/재고표.csv output/매대/<yyyymmdd>/매대표.csv [--low N]
표준 라이브러리만 쓴다. 인터넷·키 없음. 읽기만 하고 결과를 output/매대/<날짜>/결과.csv 로 저장한다.
"""
import argparse
import csv
import re
import sys
import unicodedata
from collections import OrderedDict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]  # scripts → shelf-check → skills → .claude → 루트 (루트 CLAUDE.md §5 표준 머리)
sys.path.insert(0, str(ROOT))
from shared import store_profile  # noqa: E402
from shared.paths import output_dir, show_path  # noqa: E402

DEFAULT_LOW = 10

EMOJI = {
    "oversell": "🆘",        # 재고 0인데 판매중 (계속 팔려서 마이너스)
    "vacant_anomaly": "🔴",  # 비정상 공실 (확인 필요)
    "intended_soldout": "🔴",  # 의도된 품절 (메모에 '의도')
    "low_stock": "🟠",
    "occupied": "🟢",
    "vacant_managed": "⚪",  # 단종
    "sealed": "⚫",          # 노출 꺼짐
    "qty_unknown": "❓",
    "ssot_extra": "🔵",      # 재고표에 없는데 열려 있음
    "not_listed": "·",
}
LABEL = {
    "oversell": "오버셀", "vacant_anomaly": "비정상 공실", "intended_soldout": "의도된 품절",
    "low_stock": "저재고", "occupied": "정상", "vacant_managed": "단종",
    "sealed": "미노출", "qty_unknown": "재고 확인불가", "ssot_extra": "재고표 밖 등록",
    "not_listed": "미등록",
}
YES = {"y", "yes", "예", "네", "o", "t", "true", "1", "판매", "노출"}
NO = {"n", "no", "아니오", "아니요", "x", "f", "false", "0", "중지", "숨김"}


def parse_yn(raw, default=None):
    s = (raw or "").strip().lower()
    if s in YES:
        return True
    if s in NO:
        return False
    return default


def parse_num(raw):
    """'12,000원' -> 12000. 못 읽으면 None."""
    s = re.sub(r"[,\s원₩]", "", str(raw or ""))
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def classify_state(cell_status, memo, listing, low):
    """한 칸(채널×제품×색×사이즈)의 상태를 판정한다. 네트워크 없음.

    cell_status: '판매' | '단종' | None(재고표에 없는 칸)
    memo: 재고표 메모(문자열). '의도'가 들어 있으면 의도된 품절.
    listing: None(매대에 없음) 또는 dict(qty:int|None, shown:bool, selling:bool, mark:bool|None)
             mark = 품절표시(True=품절로 표시 / False=표시 꺼짐 / None=열이 없거나 비어 있음)
    """
    if listing is None:
        return "not_listed"
    if not listing["shown"]:
        return "sealed"
    qty, selling, mark = listing["qty"], listing["selling"], listing["mark"]
    if selling and qty is None:
        return "qty_unknown"
    # 재고 0 이하인데 판매중이고 품절 표시가 안 켜져 있으면 계속 팔린다
    if selling and qty <= 0 and mark is not True:
        return "oversell"
    if not selling or qty <= 0:
        # 재고표에 없는 칸(None)이 닫혀 있는 건 맞는 상태 — 경보(🔴)가 아니다(실측: 안 만드는 색×사이즈 옵션을 닫아 둔 채널)
        if cell_status == "단종" or cell_status is None:
            return "vacant_managed"
        if cell_status == "판매" and "의도" in (memo or ""):
            return "intended_soldout"
        return "vacant_anomaly"
    if cell_status is None:
        return "ssot_extra"
    if cell_status == "판매" and qty < low:
        return "low_stock"
    return "occupied"


def price_gap(base, sale):
    """기준가와 판매가가 둘 다 숫자이고 다르면 (기준가, 판매가), 아니면 None."""
    if base is None or sale is None or base == sale:
        return None
    return (base, sale)


def read_csv(path, required):
    try:
        raw = Path(path).read_bytes()
    except FileNotFoundError:
        sys.exit(f"{path} 파일을 찾지 못했어요. 파일 이름과 위치를 확인해 주세요(엑셀 파일이면 'CSV UTF-8'로 저장한 것).")
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        sys.exit(f"{path}: 글자 인코딩을 읽지 못했어요. 엑셀에서 'CSV UTF-8'로 다시 저장해 주세요.")
    reader = csv.DictReader(text.splitlines())
    heads = [(h or "").strip() for h in (reader.fieldnames or [])]
    missing = [c for c in required if c not in heads]
    if missing:
        sys.exit(f"{path}: 필요한 열이 없어요 -> {', '.join(missing)}\n"
                 f"  지금 있는 열: {', '.join(heads)}")
    rows = []
    for r in reader:
        rows.append({(k or "").strip(): (v or "").strip() for k, v in r.items()})
    return heads, rows


def load_low_default():
    """브랜드_SSOT.md 의 저재고 기준(레포 공통 shared/store_profile.low_stock()), 없으면 10."""
    return store_profile.low_stock(DEFAULT_LOW)


def key_of(prod, color, size):
    return (prod, color, size)


def analyze(stock_rows, shelf_rows, low, has_mark_col):
    stock = OrderedDict()
    for r in stock_rows:
        stock[key_of(r["제품"], r["색"], r["사이즈"])] = r
    channels = list(OrderedDict.fromkeys(r["채널"] for r in shelf_rows))
    shelf = {}
    for r in shelf_rows:
        shelf[(r["채널"],) + key_of(r["제품"], r["색"], r["사이즈"])] = r

    results = []  # dict per (채널, 제품, 색, 사이즈)
    cells = OrderedDict()
    for ch in channels:
        for k in stock:
            cells[(ch,) + k] = True
        for ck in shelf:
            if ck[0] == ch:
                cells[ck] = True
    for ck in cells:
        ch, prod, color, size = ck
        srow = stock.get(ck[1:])
        status = srow["상태"] if srow else None
        if status not in ("판매", "단종"):
            status = "판매" if srow else None
        memo = srow.get("메모", "") if srow else ""
        base = parse_num(srow.get("기준가")) if srow else None
        sh = shelf.get(ck)
        listing = None
        sale = None
        if sh:
            sale = parse_num(sh.get("판매가"))
            listing = {
                "qty": parse_num(sh.get("재고수량")),
                "shown": parse_yn(sh.get("노출(Y/N)", sh.get("노출")), True),
                "selling": parse_yn(sh.get("판매중(Y/N)", sh.get("판매중")), True),
                "mark": parse_yn(sh.get("품절표시(Y/N)", sh.get("품절표시")), None) if has_mark_col else None,
            }
        state = classify_state(status, memo, listing, low)
        results.append({
            "채널": ch, "제품": prod, "색": color, "사이즈": size, "상태": state,
            "재고수량": "" if not listing or listing["qty"] is None else listing["qty"],
            "판매가": "" if sale is None else sale, "기준가": "" if base is None else base,
            "가격": "어긋남" if sh and price_gap(base, sale) else "",
            "메모": memo,
        })
    return channels, results


def _width(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _pad(s, n):
    return s + " " * max(0, n - _width(s))


LETTER_SIZES = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "FREE", "F"]


def _size_key(s):
    if s.isdigit():
        return (0, int(s), "")
    if s.upper() in LETTER_SIZES:
        return (1, LETTER_SIZES.index(s.upper()), "")
    return (2, 0, s)


def render_heatmap(channels, results):
    out = []
    for ch in channels:
        by_prod = OrderedDict()
        for r in results:
            if r["채널"] == ch:
                by_prod.setdefault(r["제품"], []).append(r)
        for prod, rs in by_prod.items():
            sizes = sorted({r["사이즈"] for r in rs}, key=_size_key)
            colors = list(OrderedDict.fromkeys(r["색"] for r in rs))
            idx = {(r["색"], r["사이즈"]): r["상태"] for r in rs}
            out.append(f"\n  ▮ {ch} / {prod}")
            cw = max(8, max(_width(c) for c in colors) + 1)
            out.append("    " + _pad("", cw) + "".join(f"{s:>6}" for s in sizes))
            for c in colors:
                cells = ""
                for s in sizes:
                    e = EMOJI[idx.get((c, s), "not_listed")]
                    cells += (" " * 5 + e) if e == "·" else (" " * 3 + e + " ")
                out.append("    " + _pad(c, cw) + cells)
    return "\n".join(out)


def _name(r):
    return f"{r['채널']} / {r['제품']} {r['색']} {r['사이즈']}"


def render(channels, results, low, has_mark_col):
    L = []
    if not has_mark_col:
        L.append("※ 매대표에 '품절표시' 열이 없어 '재고 0 & 판매중'이면 오버셀로 단순 판정했어요.")
    pick = lambda st: [r for r in results if r["상태"] == st]
    over, anom, lowl = pick("oversell"), pick("vacant_anomaly"), pick("low_stock")
    gaps = [r for r in results if r["가격"]]
    unk = pick("qty_unknown")

    L.append(f"\n🆘 오버셀 {len(over)}건 — 재고 0인데 판매중 (가장 급함: 계속 팔려서 마이너스가 됩니다)")
    L += [f"   - {_name(r)}  (재고 {r['재고수량']})" for r in over] or ["   없음"]
    L.append(f"\n🔴 비정상 공실 {len(anom)}건 — 닫혀 있는데 단종도 의도된 품절도 아님 (확인 필요)")
    L += [f"   - {_name(r)}  (재고 {r['재고수량'] if r['재고수량'] != '' else '-'})" for r in anom] or ["   없음"]
    L.append(f"\n🟠 저재고 {len(lowl)}건 — 재고 {low}개 미만 (판매중)")
    L += [f"   - {_name(r)}  (재고 {r['재고수량']})" for r in lowl] or ["   없음"]
    L.append(f"\n💰 가격 어긋남 {len(gaps)}건 — 기준가와 판매가가 다름")
    L += [f"   - {_name(r)}  기준가 {r['기준가']:,} / 판매가 {r['판매가']:,}" for r in gaps] or ["   없음"]
    if unk:
        L.append(f"\n❓ 재고 확인불가 {len(unk)}건 — 재고수량 칸이 비었거나 숫자가 아님")
        L += [f"   - {_name(r)}" for r in unk]
    intended = pick("intended_soldout")
    if intended:
        L.append(f"\n(참고) 의도된 품절 {len(intended)}건은 경보에서 뺐어요.")

    L.append("\n===== 채널별 히트맵 =====")
    L.append(render_heatmap(channels, results))
    L.append(f"\n범례:  🟢 정상 | 🟠 재고<{low} | 🔴 품절 | ⚪ 단종 | 🆘 오버셀 | ⚫ 미노출 | ❓ 확인불가 | 🔵 재고표 밖 | · 미등록")
    return "\n".join(L)


def save_csv(results, base_dir=None):
    """결과.csv → <base_dir>/<yyyymmdd>/결과.csv (기본 base_dir = output/매대)."""
    d = Path(base_dir or output_dir("매대")) / date.today().strftime("%Y%m%d")
    d.mkdir(parents=True, exist_ok=True)
    path = d / "결과.csv"
    cols = ["채널", "제품", "색", "사이즈", "상태", "재고수량", "판매가", "기준가", "가격", "메모"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in results:
            row = [r[c] for c in cols]
            row[4] = f"{EMOJI[r['상태']]} {LABEL[r['상태']]}"
            w.writerow(row)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="재고표와 매대표를 맞대어 이상한 칸을 찾습니다.")
    ap.add_argument("재고표")
    ap.add_argument("매대표")
    ap.add_argument("--low", type=int, default=None, help="저재고 기준(기본: 브랜드_SSOT.md 값, 없으면 10)")
    a = ap.parse_args(argv)
    low = a.low if a.low is not None else load_low_default()
    _, stock_rows = read_csv(a.재고표, ["제품", "색", "사이즈", "상태"])
    heads, shelf_rows = read_csv(a.매대표, ["채널", "제품", "색", "사이즈", "재고수량"])
    for col in ("노출", "판매중"):
        if col + "(Y/N)" not in heads and col not in heads:
            sys.exit(f"{a.매대표}: '{col}(Y/N)' 열이 없어요. ({col} 여부를 Y/N 으로)")
    has_mark = any(h in heads for h in ("품절표시(Y/N)", "품절표시")) and any(
        (r.get("품절표시(Y/N)") or r.get("품절표시")) for r in shelf_rows)
    channels, results = analyze(stock_rows, shelf_rows, low, has_mark)
    print(render(channels, results, low, has_mark))
    path = save_csv(results)
    print(f"\n저장: {show_path(path)}")


if __name__ == "__main__":
    main()
