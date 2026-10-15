"""fetch_shelf 단위 테스트 — 네트워크 0. 응답은 각 채널 공식 문서의 속성표·응답 예시 모양을 본뜬 가짜다."""
import csv
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sc = _load("shelf_check")
fs = _load("fetch_shelf")

# ---------------------------------------------------------------- 가짜 응답
# 카페24 — 02_Product.md Products / Products variants 속성표
CAFE24_PRODUCT = {"product_no": 11, "product_name": "하루양말 데일리 3켤레", "price": "5900.00",
                  "display": "T", "selling": "T"}
CAFE24_VARIANTS = [
    {"variant_code": "P000000K000A", "options": [{"name": "색상", "value": "블랙"}, {"name": "사이즈", "value": "M"}],
     "display": "T", "selling": "T", "use_inventory": "T", "display_soldout": "F", "quantity": 0,
     "additional_amount": "0.00"},
    {"variant_code": "P000000K000B", "options": [{"name": "색상", "value": "화이트"}, {"name": "사이즈", "value": "L"}],
     "display": "T", "selling": "T", "use_inventory": "T", "display_soldout": "T", "quantity": 4,
     "additional_amount": "500.00"},
    {"variant_code": "P000000K000C", "options": [{"name": "색상", "value": "형광"}, {"name": "사이즈", "value": "M"}],
     "display": "F", "selling": "T", "use_inventory": "F", "display_soldout": "F", "quantity": 0,
     "additional_amount": "0.00"},
]

# 네이버 — 086 상품 목록 조회 응답 스키마 · 070 원상품 조회 응답 예시
NAVER_ITEM = {"originProductNo": 900, "channelProducts": [
    {"originProductNo": 900, "channelProductNo": 901, "name": "하루양말 울 2켤레", "statusType": "SALE",
     "channelProductDisplayStatusType": "ON", "salePrice": 9900, "stockQuantity": 75}]}
NAVER_ORIGIN = {"originProduct": {"statusType": "SALE", "name": "하루양말 울 2켤레", "salePrice": 9900,
                                  "stockQuantity": 75, "detailAttribute": {"optionInfo": {
    "optionCombinationGroupNames": {"optionGroupName1": "컬러", "optionGroupName2": "사이즈"},
    "optionCombinations": [
        {"id": 1, "stockQuantity": 40, "price": 0, "usable": True, "optionName1": "베이지", "optionName2": "M"},
        {"id": 2, "stockQuantity": 35, "price": 1000, "usable": False, "optionName1": "베이지", "optionName2": "L"},
    ]}}}}

# 쿠팡 — 상품 조회 응답 예시(data.items[].attributes) · 아이템별 수량/가격/상태 조회 응답 예시
COUPANG_DETAIL = {"sellerProductId": 123459542, "sellerProductName": "하루양말 데일리", "statusName": "승인완료",
                  "items": [
                      {"vendorItemId": 4279191312, "itemName": "검정_M", "salePrice": 5900, "attributes": [
                          {"attributeTypeName": "색상", "attributeValueName": "검정", "exposed": "EXPOSED"},
                          {"attributeTypeName": "사이즈", "attributeValueName": "M", "exposed": "EXPOSED"},
                          {"attributeTypeName": "소재", "attributeValueName": "", "exposed": "NONE"}]},
                      {"vendorItemId": None, "itemName": "임시저장", "salePrice": 5900, "attributes": []},
                  ]}
COUPANG_INV = {4279191312: {"sellerItemId": 3000000000, "amountInStock": 9, "salePrice": 5800, "onSale": True}}

STOCK = [
    {"제품": "하루양말 데일리", "색": "검정", "사이즈": "M", "상태": "판매"},
    {"제품": "하루양말 데일리", "색": "흰색", "사이즈": "L", "상태": "판매"},
    {"제품": "하루양말 울", "색": "베이지", "사이즈": "M", "상태": "판매"},
    {"제품": "하루양말 울", "색": "베이지", "사이즈": "L", "상태": "판매"},
]
# store_profile.color_aliases() 모양 = {별칭(소문자): 대표색}
GROUPS = fs.alias_groups({"검정": "검정", "블랙": "검정", "black": "검정", "흰색": "흰색", "화이트": "흰색"})


def all_listings():
    return (fs.cafe24_rows(CAFE24_PRODUCT, CAFE24_VARIANTS)
            + fs.naver_rows(NAVER_ITEM, NAVER_ORIGIN)
            + fs.coupang_rows(COUPANG_DETAIL, COUPANG_INV))


class Converters(unittest.TestCase):
    def test_cafe24(self):
        rows = fs.cafe24_rows(CAFE24_PRODUCT, CAFE24_VARIANTS)
        self.assertEqual([r["채널 옵션명"] for r in rows], ["색상:블랙 / 사이즈:M", "색상:화이트 / 사이즈:L", "색상:형광 / 사이즈:M"])
        a, b, c = rows
        self.assertEqual((a["재고수량"], a["판매중"], a["품절표시"], a["판매가"]), (0, True, False, 5900))
        self.assertEqual((b["품절표시"], b["판매가"]), (True, 6400))       # 판매가 + 추가금액
        self.assertIsNone(c["재고수량"])                                   # 재고 사용 안 함 → ❓
        self.assertFalse(c["노출"])

    def test_naver(self):
        rows = fs.naver_rows(NAVER_ITEM, NAVER_ORIGIN)
        self.assertEqual(rows[0]["채널 옵션명"], "컬러:베이지 / 사이즈:M")
        self.assertEqual((rows[0]["재고수량"], rows[0]["판매중"], rows[0]["노출"]), (40, True, True))
        self.assertEqual((rows[1]["판매중"], rows[1]["판매가"]), (False, 10900))  # usable=false · 옵션가
        self.assertEqual(rows[0]["상품번호"], "900")

    def test_naver_discounted_price_is_sale_price(self):
        # 실측(2026-10-14): salePrice = 할인 전 정가 · discountedPrice = 즉시할인 적용가(고객이 내는 값)
        item = {"originProductNo": 900, "channelProducts": [
            dict(NAVER_ITEM["channelProducts"][0], salePrice=69000, discountedPrice=49000)]}
        origin = {"originProduct": dict(NAVER_ORIGIN["originProduct"], salePrice=69000)}
        rows = fs.naver_rows(item, origin)
        self.assertEqual([r["판매가"] for r in rows], [49000, 50000])      # 할인가 + 조합형 옵션가

    def test_naver_no_option(self):
        origin = {"originProduct": {"statusType": "OUTOFSTOCK", "salePrice": 3000, "stockQuantity": 0}}
        rows = fs.naver_rows(NAVER_ITEM, origin)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["채널 옵션명"], rows[0]["판매중"], rows[0]["재고수량"]), ("", False, 0))

    def test_coupang(self):
        rows = fs.coupang_rows(COUPANG_DETAIL, COUPANG_INV)
        self.assertEqual(len(rows), 1)                                     # 옵션ID 없는 임시저장은 뺀다
        r = rows[0]
        self.assertEqual(r["채널 옵션명"], "색상:검정 / 사이즈:M")           # EXPOSED + 값 있는 것만
        self.assertEqual((r["재고수량"], r["판매가"], r["판매중"], r["노출"]), (9, 5800, True, True))


try:
    from shared.channels import cafe24 as sh_cafe24, coupang as sh_coupang, naver as sh_naver
except ImportError:  # 공통 모듈 없이도 나머지 테스트는 돈다
    sh_cafe24 = sh_coupang = sh_naver = None


@unittest.skipIf(sh_naver is None, "shared/channels 없음")
class Fetchers(unittest.TestCase):
    """shared/channels/<채널>.products() 의 조회 순서·페이지 넘김 — request 는 가짜(네트워크 0).
    GET/POST 외(PUT·DELETE)가 나오면 실패."""

    def run_with(self, mod, routes, **extra):
        calls = []

        def request(method, path, params=None, body=None):
            self.assertIn(method, ("GET", "POST"))
            calls.append((method, path, params, body))
            for key, val in routes:
                if key(method, path, params, body):
                    return val
            raise AssertionError(f"예상 못 한 호출 {method} {path} {params}")
        saved = {"request": mod.request, **{k: getattr(mod, k) for k in extra}}
        mod.request = request
        for k, v in extra.items():
            setattr(mod, k, v)
        try:
            return mod.products(), calls
        finally:
            for k, v in saved.items():
                setattr(mod, k, v)

    def test_cafe24(self):
        pairs, _ = self.run_with(sh_cafe24, [
            (lambda m, p, q, b: p == "/products", {"products": [CAFE24_PRODUCT]}),
            (lambda m, p, q, b: p == "/products/11/variants", {"variants": CAFE24_VARIANTS}),
        ])
        self.assertEqual(len(pairs), 1)
        self.assertEqual(len(pairs[0][1]), 3)

    def test_naver_pages(self):
        pairs, calls = self.run_with(sh_naver, [
            (lambda m, p, q, b: p == "/v1/products/search" and b["page"] == 1,
             {"contents": [NAVER_ITEM], "page": 1, "totalPages": 2}),
            (lambda m, p, q, b: p == "/v1/products/search" and b["page"] == 2,
             {"contents": [], "page": 2, "totalPages": 2}),
            (lambda m, p, q, b: p == "/v2/products/origin-products/900", NAVER_ORIGIN),
        ])
        self.assertEqual(len(pairs), 1)
        self.assertEqual(sum(1 for c in calls if c[1] == "/v1/products/search"), 2)

    def test_coupang(self):
        base = sh_coupang.SELLER_API
        pairs, calls = self.run_with(sh_coupang, [
            (lambda m, p, q, b: p == f"{base}/seller-products" and "nextToken" not in q,
             {"code": "SUCCESS", "nextToken": "2", "data": [{"sellerProductId": 123459542, "statusName": "승인완료"}]}),
            (lambda m, p, q, b: p == f"{base}/seller-products" and q.get("nextToken") == "2",
             {"code": "SUCCESS", "nextToken": "", "data": [{"sellerProductId": 5, "statusName": "상품삭제"}]}),
            (lambda m, p, q, b: p == f"{base}/seller-products/123459542", {"code": "SUCCESS", "data": COUPANG_DETAIL}),
            (lambda m, p, q, b: p == f"{base}/vendor-items/4279191312/inventories",
             {"code": "SUCCESS", "data": COUPANG_INV[4279191312]}),
        ], vendor_id=lambda: "A00012345")
        self.assertEqual(len(pairs), 1)
        self.assertEqual(calls[0][2]["vendorId"], "A00012345")
        self.assertEqual(pairs[0][1][4279191312]["amountInStock"], 9)

    def test_coupang_error_code(self):
        with self.assertRaises(Exception):
            self.run_with(sh_coupang, [(lambda *a: True, {"code": "ERROR", "message": "x"})],
                          vendor_id=lambda: "A00012345")


class Colors(unittest.TestCase):
    def test_alias_groups(self):
        self.assertEqual(fs.alias_groups({"블랙": "검정", "black": "검정", "차콜": "먹색"}),
                         [["검정", "블랙", "black"], ["먹색", "차콜"]])
        self.assertEqual(fs.alias_groups({}), [])

    def test_normalize(self):
        self.assertEqual(fs.normalize_color("블랙", GROUPS, ["검정"]), "검정")
        self.assertEqual(fs.normalize_color(" Black ", GROUPS), "검정")    # 재고표 없으면 묶음 첫 이름
        self.assertEqual(fs.normalize_color("형광", GROUPS, ["검정"]), "형광")  # 별칭에 없으면 원문


class MappingFlow(unittest.TestCase):
    """가짜 응답 → --map 매핑표 → 확인=Y → 매대표 → 새 옵션 경고까지."""

    def test_flow(self):
        listings = all_listings()
        rows, added, gone = fs.build_map(listings, [], STOCK, GROUPS)
        self.assertEqual((added, gone), (len(listings), 0))
        by = {(r["채널"], r["채널 옵션명"]): r for r in rows}
        # 자동 추정이 맞는 줄
        self.assertEqual(tuple(by[("카페24", "색상:블랙 / 사이즈:M")][c] for c in ("제품", "색", "사이즈")),
                         ("하루양말 데일리", "검정", "M"))
        self.assertEqual(tuple(by[("카페24", "색상:화이트 / 사이즈:L")][c] for c in ("제품", "색", "사이즈")),
                         ("하루양말 데일리", "흰색", "L"))
        self.assertEqual(tuple(by[("스마트스토어", "컬러:베이지 / 사이즈:M")][c] for c in ("제품", "색", "사이즈")),
                         ("하루양말 울", "베이지", "M"))
        self.assertEqual(tuple(by[("쿠팡", "색상:검정 / 사이즈:M")][c] for c in ("제품", "색", "사이즈")),
                         ("하루양말 데일리", "검정", "M"))
        # 추정 못 한 칸은 비운다(재고표에 없는 색)
        self.assertEqual(by[("카페24", "색상:형광 / 사이즈:M")]["색"], "")
        self.assertTrue(all(r["확인"] == "" for r in rows))

        # 확인 칸 비어 있으면 매대표에 하나도 안 들어간다
        shelf, new, pending, dup = fs.build_shelf(listings, rows)
        self.assertEqual((len(shelf), len(new), pending), (0, 0, len(listings)))

        # 사장님 확인: 형광 줄은 N(빼기), 나머지 Y
        for r in rows:
            r["확인"] = "N" if r["채널 옵션명"].startswith("색상:형광") else "Y"
        shelf, new, pending, dup = fs.build_shelf(listings, rows)
        self.assertEqual((len(shelf), len(new), pending, dup), (5, 0, 1, []))
        self.assertEqual(list(shelf[0].keys()), fs.SHELF_COLS)
        black = next(s for s in shelf if s["채널"] == "카페24" and s["색"] == "검정")
        self.assertEqual((black["재고수량"], black["판매중(Y/N)"], black["품절표시(Y/N)"]), (0, "Y", "N"))

        # 채널에 새 옵션이 생김 → 매대표에 넣지 않고 새 옵션으로
        extra = dict(listings[0], **{"채널 옵션명": "색상:블랙 / 사이즈:L", "opts": {"색상": "블랙", "사이즈": "L"}})
        shelf2, new2, _, _ = fs.build_shelf(listings + [extra], rows)
        self.assertEqual(len(shelf2), 5)
        self.assertEqual([n["채널 옵션명"] for n in new2], ["색상:블랙 / 사이즈:L"])

        # --map 다시: 사장님이 채운 줄은 그대로, 새 옵션만 덧붙음
        rows2, added2, _ = fs.build_map(listings + [extra], rows, STOCK, GROUPS)
        self.assertEqual(added2, 1)
        self.assertEqual(rows2[:len(rows)], rows)
        self.assertEqual(rows2[-1]["확인"], "")

        # 한 채널(쿠팡)만 읽혔을 때: 다른 채널 줄은 '사라짐'으로 세지 않는다
        only = [li for li in listings if li["채널"] == "쿠팡"]
        _, _, gone3 = fs.build_map(only, rows, STOCK, GROUPS)
        self.assertEqual(gone3, 0)

    def test_shelf_csv_feeds_shelf_check(self):
        """만든 매대표.csv 를 shelf_check 가 그대로 읽어 판정한다(파일 왕복)."""
        listings = all_listings()
        rows, _, _ = fs.build_map(listings, [], STOCK, GROUPS)
        for r in rows:
            r["확인"] = "Y" if r["색"] else "N"
        shelf, _, _, _ = fs.build_shelf(listings, rows)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "매대표.csv"
            fs.write_csv(p, fs.SHELF_COLS, shelf)
            heads, back = sc.read_csv(p, ["채널", "제품", "색", "사이즈", "재고수량"])
            self.assertEqual(heads, fs.SHELF_COLS)
            stock = [dict(s, 기준가="5900" if s["제품"] == "하루양말 데일리" else "9900", 메모="") for s in STOCK]
            _, res = sc.analyze(stock, back, 10, has_mark_col=True)
            st = {(r["채널"], r["색"], r["사이즈"]): r["상태"] for r in res}
            self.assertEqual(st[("카페24", "검정", "M")], "oversell")       # 재고 0·판매중·품절표시 꺼짐
            self.assertEqual(st[("카페24", "흰색", "L")], "low_stock")
            self.assertEqual(st[("스마트스토어", "베이지", "L")], "vacant_anomaly")  # usable=false
            self.assertEqual(st[("쿠팡", "검정", "M")], "low_stock")

    def test_map_file_roundtrip(self):
        """매핑표는 스킬 결과 폴더 맨 위에 쓴다 — 테스트는 MAP_PATH 를 임시 폴더로 바꿔 끼운다(레포 결과 폴더를 건드리지 않게)."""
        self.assertEqual(fs.MAP_PATH.parts[-2:], ("output_shelf-check", "매핑표.csv"))
        listings = all_listings()
        rows, _, _ = fs.build_map(listings, [], STOCK, GROUPS)
        orig = fs.MAP_PATH
        with tempfile.TemporaryDirectory() as d:
            fs.MAP_PATH = Path(d) / "매핑표.csv"
            try:
                fs.write_csv(fs.MAP_PATH, fs.MAP_COLS, rows)
                back = fs.read_map()
                self.assertEqual([fs.map_key(r) for r in back], [fs.map_key(r) for r in rows])
                with fs.MAP_PATH.open(encoding="utf-8-sig") as f:
                    self.assertEqual(next(csv.reader(f)), fs.MAP_COLS)
            finally:
                fs.MAP_PATH = orig


class SameSkuManyProducts(unittest.TestCase):
    """한 채널에 같은 SKU 를 상품 둘(일반 + 공구)로 올린 가게 — 채널 이름에 상품명을 붙여 둘 다 매대표에 싣는다."""

    def _two_products(self):
        general = dict(NAVER_ITEM, originProductNo=900)
        group = {"originProductNo": 950, "channelProducts": [
            dict(NAVER_ITEM["channelProducts"][0], originProductNo=950, channelProductNo=951,
                 name="[공구] 하루양말 울 2켤레 특가 세트")]}
        listings = fs.naver_rows(general, NAVER_ORIGIN) + fs.naver_rows(group, NAVER_ORIGIN)
        rows, _, _ = fs.build_map(listings, [], STOCK, GROUPS)
        for r in rows:
            r["확인"] = "Y"
        return listings, rows

    def test_split_by_product_no_dup_warning(self):
        listings, rows = self._two_products()
        shelf, new, pending, dup = fs.build_shelf(listings, rows)
        self.assertEqual(dup, [])                                   # "같은 칸 중복 — 첫 줄만" 경고가 없어야 한다
        self.assertEqual((len(shelf), len(new), pending), (4, 0, 0))
        self.assertEqual(list(shelf[0].keys()), fs.SHELF_COLS)       # 매대표 양식 그대로
        chans = sorted({s["채널"] for s in shelf})
        self.assertEqual(chans, ["스마트스토어 · [공구] 하루양말 울 2켤레 특가 세", "스마트스토어 · 하루양말 울 2켤레"])
        # shelf_check 가 갈라진 채널을 각각 판정한다
        stock = [dict(s, 기준가="", 메모="") for s in STOCK]
        channels, res = sc.analyze(stock, shelf, 10, has_mark_col=True)
        self.assertEqual(len(channels), 2)
        st = {(r["채널"], r["색"], r["사이즈"]): r["상태"] for r in res if r["제품"] == "하루양말 울"}
        self.assertEqual(st[("스마트스토어 · 하루양말 울 2켤레", "베이지", "L")], "vacant_anomaly")
        self.assertEqual(st[("스마트스토어 · [공구] 하루양말 울 2켤레 특가 세", "베이지", "L")], "vacant_anomaly")

    def test_other_products_keep_plain_channel(self):
        """겹치지 않는 상품(쿠팡 · 카페24)은 채널 이름 그대로."""
        listings, rows = self._two_products()
        extra = fs.coupang_rows(COUPANG_DETAIL, COUPANG_INV)
        rows2, _, _ = fs.build_map(listings + extra, rows, STOCK, GROUPS)
        for r in rows2:
            r["확인"] = "Y"
        shelf, _, _, dup = fs.build_shelf(listings + extra, rows2)
        self.assertEqual(dup, [])
        self.assertIn("쿠팡", {s["채널"] for s in shelf})

    def test_same_name_prefix_falls_back_to_product_no(self):
        listings, rows = self._two_products()
        for li in listings:
            li["채널 상품명"] = "하루양말 울 2켤레 묶음 특가 판매 상품 " + li["상품번호"]   # 앞 20자가 같다
        shelf, _, _, dup = fs.build_shelf(listings, rows)
        self.assertEqual(dup, [])
        self.assertEqual(sorted({s["채널"] for s in shelf}),
                         ["스마트스토어 · 하루양말 울 2켤레 묶음 특가 판매 #900", "스마트스토어 · 하루양말 울 2켤레 묶음 특가 판매 #950"])

    def test_same_product_two_options_still_warns(self):
        """한 상품 안에서 옵션 둘이 같은 칸이면 여전히 첫 줄만 쓰고 알린다."""
        listings = fs.naver_rows(NAVER_ITEM, NAVER_ORIGIN)
        rows, _, _ = fs.build_map(listings, [], STOCK, GROUPS)
        for r in rows:
            r.update(색="베이지", 사이즈="M", 확인="Y")
        shelf, _, _, dup = fs.build_shelf(listings, rows)
        self.assertEqual((len(shelf), len(dup)), (1, 1))
        self.assertEqual(shelf[0]["채널"], "스마트스토어")


class FetchAll(unittest.TestCase):
    """키 없는 채널은 건너뛰고 한 줄 안내 — shared 모듈은 가짜로 끼운다."""

    def test_no_key_and_failure(self):
        def mod(configured, products=None):
            return types.SimpleNamespace(configured=lambda: configured, products=products)

        def boom():
            raise RuntimeError("HTTP 401")
        fakes = {"cafe24": mod(False), "naver": mod(True, boom), "coupang": mod(False)}
        orig = fs._channel_module
        fs._channel_module = lambda key: fakes[key]
        try:
            listings, notes = fs.fetch_all()
        finally:
            fs._channel_module = orig
        self.assertEqual(listings, [])
        self.assertIn(f"카페24: {fs.NO_KEY}", notes)
        self.assertTrue(any(n.startswith("스마트스토어: 읽기 실패") for n in notes))


if __name__ == "__main__":
    unittest.main()
