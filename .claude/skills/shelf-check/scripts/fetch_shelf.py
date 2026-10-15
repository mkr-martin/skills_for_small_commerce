#!/usr/bin/env python3
"""매대 가져오기 — 채널 API 에서 상품·옵션·재고를 읽어 매대표.csv 를 만든다. 읽기만 한다.

사용:
  (S = .claude/skills/shelf-check/scripts · 결과물은 어느 폴더에서 실행해도 레포 맨 위 output_shelf-check/ 에 쓴다)
  처음 한 번(상품이 바뀌었을 때도):  python3 $S/fetch_shelf.py --map      -> output_shelf-check/매핑표.csv
  매일:                              python3 $S/fetch_shelf.py            -> output_shelf-check/<yyyymmdd_hhmm>/매대표.csv
  그다음:                            python3 $S/shelf_check.py            (재고표·가장 최근 매대표를 알아서 씀)

- 채널 옵션(예: "색상:블랙 / 사이즈:M")을 재고표의 (제품·색·사이즈)에 잇는 장부 = output_shelf-check/매핑표.csv.
  --map 이 자동 추정으로 채우고, 사장님이 확인 칸에 Y(쓰기)·N(빼기)를 적는다.
- 평소 실행은 확인=Y 줄만 매대표에 넣는다. 매핑표에 없는 옵션은 넣지 않고 🔵 새 옵션으로 알린다.
- 한 채널에 같은 칸(제품·색·사이즈)을 여러 상품으로 올렸으면(예: 일반 판매 + 공동구매) 그 상품들은 채널 이름에
  상품명을 붙여 따로 센다(예: "스마트스토어 · 하루양말 데일리 3켤레") — 매대표 열은 그대로.
- 인증·요청·상품 조회는 레포 루트 shared/channels/<채널>.py 의 configured()·products() 를 쓴다
  (여기엔 인증·HTTP 코드 없음 — 이 파일은 응답을 매대표 줄로 바꾸고 매핑표를 다룬다).
- 쓰기·수정 API 는 하나도 부르지 않는다. 네이버 상품 목록 조회만 POST 인데, 문서상 조회 API 다.
"""
import argparse
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]  # scripts → shelf-check → skills → .claude → 루트 (루트 CLAUDE.md §5 표준 머리)
sys.path.insert(0, str(ROOT))
from shared import store_profile  # noqa: E402
from shared.paths import run_dir, show_path, skill_root  # noqa: E402
from shared.channels import cafe24, coupang, naver  # noqa: E402

import shelf_check  # noqa: E402  같은 폴더 — csv 읽기·숫자 읽기를 그대로 쓴다

SHELF_COLS = ["채널", "제품", "색", "사이즈", "재고수량", "노출(Y/N)", "판매중(Y/N)", "품절표시(Y/N)", "판매가"]
MAP_COLS = ["채널", "상품번호", "채널 상품명", "채널 옵션명", "제품", "색", "사이즈", "확인"]
MAP_PATH = skill_root("shelf-check") / "매핑표.csv"
STOCK_PATH = skill_root("shelf-check") / "재고표.csv" # 사장님이 채우는 재고표 — 양식 templates/재고표.csv
PRODUCT_LABEL_LEN = 20                         # 채널 이름에 붙이는 상품명 앞 글자 수

# (shared/channels 모듈 이름, 매대표에 적을 채널 이름)
CHANNELS = [("cafe24", "카페24"), ("naver", "스마트스토어"), ("coupang", "쿠팡")]
NO_KEY = "키 없음 — 루트 README '키 발급'"


def _yn(b):
    return "Y" if b else "N"


def _int(v):
    n = shelf_check.parse_num(v)
    return n if n is not None else 0


# ================================================================== 공통 모듈(shared) 부르기
CHANNEL_MODULES = {"cafe24": cafe24, "naver": naver, "coupang": coupang}


def _channel_module(key):
    return CHANNEL_MODULES[key]   # 테스트가 가짜 모듈로 바꿔 끼우는 자리


# ================================================================== 색 별칭 정규화
def _norm(s):
    return re.sub(r"\s+", "", str(s or "")).lower()


def alias_groups(aliases):
    """store_profile.color_aliases() 의 {별칭: 대표색} → [[대표색, 별칭…], …] 묶음 목록."""
    by_main = {}
    for alias, main in (aliases or {}).items():
        by_main.setdefault(main, [main]).append(alias)
    return list(by_main.values())


def normalize_color(value, groups, known=None):
    """채널마다 다르게 적힌 색 이름을 하나로. 별칭 묶음 안에 재고표 색(known)이 있으면 그 이름,
    없으면 묶음의 첫 이름, 별칭에 없으면 원문 그대로(앞뒤 공백만 뗌)."""
    v = str(value or "").strip()
    known_n = {_norm(k): k for k in (known or [])}
    if _norm(v) in known_n:
        return known_n[_norm(v)]
    for g in groups:
        if _norm(v) in {_norm(n) for n in g}:
            for n in g:
                if _norm(n) in known_n:
                    return known_n[_norm(n)]
            return g[0]
    return v


# ================================================================== API 응답 → 한 줄(listing)
# listing = {채널, 상품번호, 채널 상품명, 채널 옵션명, opts, 재고수량, 노출, 판매중, 품절표시, 판매가}
def _listing(ch, no, name, opts, qty, shown, selling, mark, price):
    opt_name = " / ".join(f"{k}:{v}" if k else str(v) for k, v in opts.items() if str(v).strip())
    return {"채널": ch, "상품번호": str(no), "채널 상품명": str(name or "").strip(),
            "채널 옵션명": opt_name, "opts": opts, "재고수량": qty,
            "노출": shown, "판매중": selling, "품절표시": mark, "판매가": price}


def cafe24_rows(product, variants, ch="카페24"):
    """카페24 상품 1개 + 품목(variants) 목록 → listing 목록.
    문서(02_Product.md Products·Products variants 속성표): product_no·product_name·price·display·selling /
    variant: options·quantity·display·selling·display_soldout·use_inventory·additional_amount."""
    out = []
    p_shown = product.get("display") == "T"
    p_selling = product.get("selling") == "T"
    base = _int(product.get("price"))
    for v in variants:
        # 미확인 — 실측 필요: options 원소의 모양 {name, value} — 문서 속성표엔 "옵션"으로만 적혀 있다(참고 구현 기준).
        opts = {str(o.get("name", "")).strip(): str(o.get("value", "")).strip() for o in v.get("options") or []}
        # 재고 사용 안 함(use_inventory=F)이면 수량이 판매와 무관 → 칸을 비워 ❓로 보이게 한다
        qty = _int(v.get("quantity")) if v.get("use_inventory") != "F" else None
        out.append(_listing(
            ch, product.get("product_no"), product.get("product_name"), opts, qty,
            p_shown and v.get("display") == "T", p_selling and v.get("selling") == "T",
            v.get("display_soldout") == "T", base + _int(v.get("additional_amount"))))
    return out


def naver_rows(item, origin, ch="스마트스토어"):
    """네이버 상품 목록 1건(contents[]) + 원상품 조회 응답 → listing 목록.
    문서 086(상품 목록 조회): originProductNo·channelProducts[].name·statusType·channelProductDisplayStatusType·
    salePrice·discountedPrice(할인가). 실측(2026-10-14): channelProducts 는 스마트스토어 1개뿐인 가게에선 1건 ·
    salePrice = 할인 전 정가, discountedPrice = 즉시할인 적용가(고객이 내는 값).
    문서 070(원상품 조회) 응답 예시: originProduct.salePrice·stockQuantity·detailAttribute.optionInfo
    (optionCombinationGroupNames·optionCombinations[optionName1~4·stockQuantity·price·usable]·
     standardOptionGroups[groupName]·optionStandards[optionName1~2·stockQuantity·usable])."""
    cps = item.get("channelProducts") or [{}]
    cp = cps[0]
    op = (origin or {}).get("originProduct") or {}
    no = item.get("originProductNo") or cp.get("originProductNo")
    name = cp.get("name") or op.get("name")
    shown = cp.get("channelProductDisplayStatusType") == "ON"
    on_sale = (op.get("statusType") or cp.get("statusType")) == "SALE"
    # 판매가 = 고객이 내는 값. 즉시할인이 걸린 상품을 salePrice(정가)로 비교하면 전부 💰 가 뜬다(실측).
    if cp.get("discountedPrice") is not None:
        base = _int(cp.get("discountedPrice"))
    else:
        base = _int(op.get("salePrice") if op.get("salePrice") is not None else cp.get("salePrice"))
    info = (op.get("detailAttribute") or {}).get("optionInfo") or {}
    # 품절표시: 네이버는 재고 0 이면 스스로 품절로 막는다(추측 — 문서로 확인 못 함). 그래서 Y.
    out = []
    names = info.get("optionCombinationGroupNames") or {}
    for c in info.get("optionCombinations") or []:
        opts = {}
        for i in range(1, 5):
            if c.get(f"optionName{i}"):
                opts[names.get(f"optionGroupName{i}") or f"옵션{i}"] = c[f"optionName{i}"]
        out.append(_listing(ch, no, name, opts, _int(c.get("stockQuantity")), shown,
                            on_sale and c.get("usable", True) is not False, True,
                            base + _int(c.get("price"))))
    std_groups = [g.get("groupName") for g in info.get("standardOptionGroups") or []]
    for s in info.get("optionStandards") or []:
        opts = {}
        for i in range(1, 3):
            if s.get(f"optionName{i}"):
                # standardOptionGroups 순서 = optionName1·2 순서(실측 2026-10-14: 상품 2개에서 값이 각 그룹 안에 듦)
                g = std_groups[i - 1] if len(std_groups) >= i and std_groups[i - 1] else f"옵션{i}"
                opts[g] = s[f"optionName{i}"]
        out.append(_listing(ch, no, name, opts, _int(s.get("stockQuantity")), shown,
                            on_sale and s.get("usable", True) is not False, True, base))
    if not out:  # 옵션 없는 단일 상품
        qty = op.get("stockQuantity") if op.get("stockQuantity") is not None else cp.get("stockQuantity")
        out.append(_listing(ch, no, name, {}, _int(qty), shown, on_sale, True, base))
    return out


COUPANG_SHOWN = {"승인완료", "부분승인완료"}


def coupang_rows(detail, inventories, ch="쿠팡"):
    """쿠팡 상품 조회 data + {vendorItemId: 아이템별 수량/가격/상태 data} → listing 목록.
    문서(상품 조회): sellerProductId·sellerProductName·statusName·items[vendorItemId·itemName·salePrice·
    attributes[attributeTypeName·attributeValueName·exposed]] /
    문서(상품 아이템별 수량/가격/상태 조회): amountInStock·salePrice·onSale."""
    out = []
    shown = detail.get("statusName") in COUPANG_SHOWN
    for it in detail.get("items") or []:
        vid = it.get("vendorItemId")
        if not vid:  # 임시저장 상태 = 아직 옵션ID 없음(문서)
            continue
        inv = inventories.get(vid) or inventories.get(str(vid)) or {}
        opts = {a.get("attributeTypeName", ""): a.get("attributeValueName", "")
                for a in it.get("attributes") or []
                if a.get("exposed") == "EXPOSED" and str(a.get("attributeValueName") or "").strip()}
        if not opts:
            opts = {"": it.get("itemName", "")}
        qty = inv.get("amountInStock")
        price = inv.get("salePrice") if inv.get("salePrice") is not None else it.get("salePrice")
        # 품절표시: 쿠팡은 재고 0 이면 스스로 품절로 막는다(추측 — 문서로 확인 못 함). 그래서 Y.
        out.append(_listing(ch, detail.get("sellerProductId"), detail.get("sellerProductName"), opts,
                            None if qty is None else _int(qty), shown, bool(inv.get("onSale")), True,
                            _int(price)))
    return out


# ================================================================== 채널 묶어 읽기
def fetch_all():
    """키 있는 채널만 읽는다. (listing 목록, 사장님께 보일 안내 줄 목록)."""
    listings, notes = [], []
    for key, label in CHANNELS:
        mod = _channel_module(key)
        if not mod.configured():
            notes.append(f"{label}: {NO_KEY}")
            continue
        try:
            to_rows = {"cafe24": cafe24_rows, "naver": naver_rows, "coupang": coupang_rows}[key]
            rows = [r for a, b in mod.products() for r in to_rows(a, b, label)]
        except Exception as e:  # 한 채널이 실패해도 나머지는 계속
            notes.append(f"{label}: 읽기 실패 — {e}")
            continue
        listings += rows
        notes.append(f"{label}: 옵션 {len(rows)}줄 읽음")
    return listings, notes


# ================================================================== 매핑표
def map_key(row):
    return (row["채널"], str(row["상품번호"]), row["채널 옵션명"])


def guess(listing, stock_rows, groups):
    """채널 상품명·옵션값으로 재고표의 (제품, 색, 사이즈)를 추정한다. 못 찾은 칸은 ''."""
    name = _norm(listing["채널 상품명"])
    products = list(dict.fromkeys(r["제품"] for r in stock_rows))
    cands = [p for p in products if _norm(p) and _norm(p) in name]
    prod = max(cands, key=lambda p: len(_norm(p))) if cands else ""
    pool = [r for r in stock_rows if r["제품"] == prod] if prod else stock_rows
    colors = list(dict.fromkeys(r["색"] for r in pool))
    sizes = {_norm(r["사이즈"]): r["사이즈"] for r in pool}
    tokens = []
    for v in listing["opts"].values():
        tokens.append(str(v))
        tokens += [t for t in re.split(r"[\s_/,()\[\]]+", str(v)) if t]
    color = size = ""
    for t in tokens:
        c = normalize_color(t, groups, colors)
        if not color and c in colors:
            color = c
        elif not size and _norm(t) in sizes:
            size = sizes[_norm(t)]
    return prod, color, size


def read_map(path=None):
    path = Path(path or MAP_PATH)
    if not path.exists():
        return []
    _, rows = shelf_check.read_csv(path, MAP_COLS)
    return rows


def write_csv(path, cols, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def build_map(listings, old_rows, stock_rows, groups):
    """기존 매핑표 줄은 그대로 두고(사장님이 채운 것), 처음 보는 옵션만 추정해 덧붙인다.
    (새 매핑표 줄 목록, 덧붙인 수, 채널에서 사라진 줄 수)."""
    rows = [dict(r) for r in old_rows]
    seen = {map_key(r) for r in rows}
    added = 0
    for li in listings:
        k = map_key(li)
        if k in seen:
            continue
        seen.add(k)
        prod, color, size = guess(li, stock_rows, groups)
        rows.append({"채널": li["채널"], "상품번호": li["상품번호"], "채널 상품명": li["채널 상품명"],
                     "채널 옵션명": li["채널 옵션명"], "제품": prod, "색": color, "사이즈": size, "확인": ""})
        added += 1
    live = {map_key(li) for li in listings}
    read_ch = {li["채널"] for li in listings}  # 이번에 읽기 실패한 채널의 줄은 '사라짐'으로 세지 않는다
    gone = sum(1 for r in old_rows if r["채널"] in read_ch and map_key(r) not in live)
    return rows, added, gone


def channel_labels(listings, yes):
    """매대표 '채널' 칸 이름 — 보통은 채널 이름 그대로.
    한 채널 안에서 같은 칸(제품·색·사이즈)을 서로 다른 상품 둘 이상이 차지하면(예: 일반 판매 + 공동구매),
    그 상품들만 "채널 · 상품명 앞 20자" 로 나눠 센다(상품명 앞 20자까지 같으면 끝에 #상품번호).
    {(채널, 상품번호): 이름} 을 돌려준다."""
    owners = {}   # (채널, 제품, 색, 사이즈) → {상품번호: 상품명}
    for li in listings:
        k = map_key(li)
        if k in yes:
            owners.setdefault((li["채널"],) + yes[k], {})[li["상품번호"]] = li["채널 상품명"]
    split = {}
    for (ch, *_), prods in owners.items():
        if len(prods) > 1:
            for no, name in prods.items():
                split[(ch, no)] = name
    labels = {(ch, no): f"{ch} · {name[:PRODUCT_LABEL_LEN].strip() or '#' + no}" for (ch, no), name in split.items()}
    seen = {}
    for key, lab in labels.items():
        seen.setdefault(lab, []).append(key)
    for lab, keys in seen.items():
        if len(keys) > 1:                       # 상품명 앞부분까지 같은 상품 — 상품번호로 가른다
            for ch, no in keys:
                labels[(ch, no)] = f"{lab} #{no}"
    return labels


def build_shelf(listings, map_rows):
    """확인=Y 매핑만 써서 매대표 줄을 만든다. (매대표 줄, 새 옵션 listing, 확인 안 된 수, 중복 목록).
    중복 = 같은 상품 안에서 옵션 둘 이상이 같은 칸으로 이어진 것(첫 줄만 쓴다). 서로 다른 상품이면 channel_labels 로 가른다."""
    yes, known, pending = {}, set(), 0
    for r in map_rows:
        k = map_key(r)
        known.add(k)
        if r.get("확인", "").strip().upper() == "Y" and r["제품"] and r["색"] and r["사이즈"]:
            yes[k] = (r["제품"], r["색"], r["사이즈"])
    labels = channel_labels(listings, yes)
    shelf, new, dup, used = [], [], [], set()
    for li in listings:
        k = map_key(li)
        if k not in known:
            new.append(li)
            continue
        if k not in yes:
            pending += 1  # 확인 칸이 비었거나 N, 또는 제품·색·사이즈가 비었음
            continue
        prod, color, size = yes[k]
        ch = labels.get((li["채널"], li["상품번호"]), li["채널"])
        cell = (ch, prod, color, size)
        if cell in used:
            dup.append(f"{ch} / {prod} {color} {size} ← {li['채널 상품명']} {li['채널 옵션명']}")
            continue
        used.add(cell)
        shelf.append({"채널": ch, "제품": prod, "색": color, "사이즈": size,
                      "재고수량": "" if li["재고수량"] is None else li["재고수량"],
                      "노출(Y/N)": _yn(li["노출"]), "판매중(Y/N)": _yn(li["판매중"]),
                      "품절표시(Y/N)": _yn(li["품절표시"]), "판매가": li["판매가"]})
    return shelf, new, pending, dup


# ================================================================== 실행
def run_map(listings, stock_path):
    stock_rows = []
    if Path(stock_path).exists():
        _, stock_rows = shelf_check.read_csv(stock_path, ["제품", "색", "사이즈"])
    else:
        print(f"※ {show_path(stock_path)} 이 없어 추정 없이 제품·색·사이즈 칸을 비워 둡니다.")
    rows, added, gone = build_map(listings, read_map(), stock_rows, alias_groups(store_profile.color_aliases()))
    write_csv(MAP_PATH, MAP_COLS, rows)
    blank = sum(1 for r in rows if not (r["제품"] and r["색"] and r["사이즈"]))
    todo = sum(1 for r in rows if not r.get("확인", "").strip())
    print(f"\n매핑표: {show_path(MAP_PATH)}  (새로 추가 {added}줄 · 전체 {len(rows)}줄)")
    print(f"  - 제품·색·사이즈 중 빈 칸이 있는 줄 {blank}건 — 채워 주세요")
    print(f"  - 확인 칸이 빈 줄 {todo}건 — 맞으면 Y, 매대 점검에서 뺄 줄이면 N")
    if gone:
        print(f"  - 채널에서 더 안 보이는 줄 {gone}건은 그대로 두었어요(지워도 됩니다)")


def run_daily(listings):
    map_rows = read_map()
    if not map_rows:
        sys.exit(f"{show_path(MAP_PATH)} 이 없어요. 처음 한 번은 `python3 .claude/skills/shelf-check/scripts/fetch_shelf.py --map` 으로 매핑표부터 만들어 주세요.")
    shelf, new, pending, dup = build_shelf(listings, map_rows)
    if not shelf:
        sys.exit(f"매핑표에 확인=Y 이고 제품·색·사이즈가 다 찬 줄이 없어요 — {show_path(MAP_PATH)} 부터 채워 주세요"
                 f"(확인 안 된 줄 {pending}건 · 새 옵션 {len(new)}건).")
    out = run_dir("shelf-check") / "매대표.csv"
    write_csv(out, SHELF_COLS, shelf)
    print(f"\n매대표: {show_path(out)}  ({len(shelf)}줄)")
    if new:
        print(f"\n🔵 새 옵션 {len(new)}건 — 매핑표에 없어 매대표에 넣지 않았어요. `fetch_shelf.py --map` 다시")
        for li in new[:10]:
            print(f"   - {li['채널']} / {li['채널 상품명']}  {li['채널 옵션명'] or '(옵션 없음)'}")
        if len(new) > 10:
            print(f"   … 외 {len(new) - 10}건")
    if pending:
        print(f"\n※ 매핑표에서 확인=Y 가 아니거나 칸이 빈 줄 {pending}건은 넣지 않았어요.")
    if dup:
        print(f"\n※ 한 상품 안에서 옵션 둘 이상이 같은 칸으로 이어져 첫 줄만 썼어요 {len(dup)}건 — 매핑표에서 하나만 Y 로:")
        for d in dup[:10]:
            print(f"   - {d}")
    if any(r["재고수량"] == "" for r in shelf):
        print("\n※ 재고수량을 못 받은 옵션(카페24 '재고 사용 안 함' 등)은 칸을 비웠어요(점검에서 ❓로 보입니다).")
    print(f"\n다음: python3 .claude/skills/shelf-check/scripts/shelf_check.py")


def main(argv=None):
    ap = argparse.ArgumentParser(description="채널 API 에서 매대표.csv 를 만듭니다(읽기만).")
    ap.add_argument("--map", action="store_true", help="매핑표(output_shelf-check/매핑표.csv)를 만들거나 새 옵션을 덧붙입니다")
    ap.add_argument("--stock", default=str(STOCK_PATH), help="--map 때 추정에 쓸 재고표(기본: output_shelf-check/재고표.csv)")
    a = ap.parse_args(argv)
    listings, notes = fetch_all()
    for n in notes:
        print(n)
    if not listings:
        sys.exit("\n읽어 온 옵션이 없어요. 키가 없으면 매대표.csv 를 직접 채워도 됩니다(양식 .claude/skills/shelf-check/templates/매대표.csv).")
    if a.map:
        run_map(listings, a.stock)
    else:
        run_daily(listings)


if __name__ == "__main__":
    main()
