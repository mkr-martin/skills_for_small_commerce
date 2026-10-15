import importlib.util
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "shelf_check", Path(__file__).resolve().parent.parent / "scripts" / "shelf_check.py")
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)

LOW = 10


def L(qty, shown=True, selling=True, mark=True):
    return {"qty": qty, "shown": shown, "selling": selling, "mark": mark}


# (설명, 재고표 상태, 메모, 매대 줄(None=미등록), 기대 상태)
CASES = [
    ("미등록", "판매", "", None, "not_listed"),
    ("정상", "판매", "", L(120), "occupied"),
    ("저재고", "판매", "", L(4), "low_stock"),
    ("재고 딱 기준값은 정상", "판매", "", L(10), "occupied"),
    ("오버셀: 재고 0 + 품절표시 꺼짐", "판매", "", L(0, mark=False), "oversell"),
    ("오버셀(단순): 품절표시 열 없음 + 재고 0 + 판매중", "판매", "", L(0, mark=None), "oversell"),
    ("품절표시 켜진 재고 0 = 비정상 공실", "판매", "", L(0), "vacant_anomaly"),
    ("판매중지 = 비정상 공실", "판매", "", L(50, selling=False), "vacant_anomaly"),
    ("미노출은 품절이 아니다", "판매", "", L(50, shown=False), "sealed"),
    ("단종이고 닫힘", "단종", "", L(0), "vacant_managed"),
    ("단종인데 남은 재고 판매중", "단종", "", L(30), "occupied"),
    ("의도된 품절 메모", "판매", "시즌 끝나서 의도된 품절", L(0), "intended_soldout"),
    ("재고표 밖인데 열려 있음", None, "", L(30), "ssot_extra"),
    ("재고표 밖이고 닫혀 있음 = 맞는 상태(경보 아님)", None, "", L(0, selling=False), "vacant_managed"),
    ("재고표 밖이고 재고 0 품절표시", None, "", L(0), "vacant_managed"),
    ("재고 칸 비어 있음 = 확인불가(0 품절로 오경보 금지)", "판매", "", L(None), "qty_unknown"),
    ("판매중지 + 재고 비어 있음 = 공실(확인불가 아님)", "판매", "", L(None, selling=False), "vacant_anomaly"),
    ("미노출 + 재고 비어 있음", "판매", "", L(None, shown=False), "sealed"),
]


class ClassifyCases(unittest.TestCase):
    def test_cases(self):
        for label, status, memo, listing, expected in CASES:
            with self.subTest(label):
                self.assertEqual(sc.classify_state(status, memo, listing, LOW), expected)


class Helpers(unittest.TestCase):
    def test_parse_num(self):
        self.assertEqual(sc.parse_num("12,000원"), 12000)
        self.assertIsNone(sc.parse_num(""))
        self.assertIsNone(sc.parse_num("abc"))

    def test_price_gap(self):
        self.assertEqual(sc.price_gap(9900, 8900), (9900, 8900))
        self.assertIsNone(sc.price_gap(9900, 9900))
        self.assertIsNone(sc.price_gap(None, 9900))

    def test_analyze_price_and_missing_mark_column(self):
        stock = [{"제품": "A", "색": "흰", "사이즈": "M", "상태": "판매", "기준가": "1000", "메모": ""}]
        shelf = [{"채널": "몰", "제품": "A", "색": "흰", "사이즈": "M", "재고수량": "0",
                  "노출(Y/N)": "Y", "판매중(Y/N)": "Y", "판매가": "900"}]
        _, res = sc.analyze(stock, shelf, LOW, has_mark_col=False)
        self.assertEqual(res[0]["상태"], "oversell")
        self.assertEqual(res[0]["가격"], "어긋남")


class MissingFile(unittest.TestCase):
    def test_missing_csv_exits_with_friendly_message(self):
        with self.assertRaises(SystemExit) as cm:
            sc.read_csv("/nonexistent/재고표.csv", ["제품"])
        self.assertIn("찾지 못했어요", str(cm.exception.code))


if __name__ == "__main__":
    unittest.main()
