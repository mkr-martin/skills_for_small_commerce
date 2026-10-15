"""공통 부품 테스트 — 네트워크 0 · 가짜 파일만. 실행: 레포 루트에서
    python3 -m unittest discover -s shared/tests -t .
"""
import os
import tempfile
import unittest
from pathlib import Path

from shared import env, ledger, paths, store_profile

ROOT = paths.repo_root()


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.p = self.dir / "건" / "원장.md"

    def test_create_then_append_keeps_column_order(self):
        ledger.append(self.p, {"날짜": "2026-10-14", "가게": "하루양말", "메모": "a|b\n둘째줄"})
        ledger.append(self.p, {"메모": "순서 뒤집어도", "날짜": "2026-10-15"})
        lines = self.p.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "| 날짜 | 가게 | 메모 |")
        self.assertEqual(lines[1], "|---|---|---|")
        self.assertEqual(lines[2], "| 2026-10-14 | 하루양말 | a\\|b<br>둘째줄 |")
        self.assertEqual(lines[3], "| 2026-10-15 |  | 순서 뒤집어도 |")
        self.assertEqual(len(lines), 4)

    def test_unknown_column_rejected(self):
        ledger.append(self.p, {"날짜": "1"})
        with self.assertRaises(ledger.LedgerError):
            ledger.append(self.p, {"없는열": "x"})

    def test_title_above_table_and_trailing_blank_lines(self):
        self.p.parent.mkdir(parents=True)
        self.p.write_text("# 상세페이지 원장\n\n| 날짜 | 가게 |\n|---|---|\n| 1 | 가 |\n\n\n", encoding="utf-8")
        ledger.append(self.p, {"날짜": "2", "가게": "나"})
        self.assertEqual(self.p.read_text(encoding="utf-8"),
                         "# 상세페이지 원장\n\n| 날짜 | 가게 |\n|---|---|\n| 1 | 가 |\n| 2 | 나 |\n")

    def test_crlf_file_not_corrupted(self):
        self.p.parent.mkdir(parents=True)
        self.p.write_bytes("| 날짜 | 가게 |\r\n|---|---|\r\n| 1 | 가나다라 |\r\n\r\n".encode("utf-8"))
        ledger.append(self.p, {"날짜": "2", "가게": "마"})
        self.assertEqual(self.p.read_bytes().decode("utf-8"),
                         "| 날짜 | 가게 |\r\n|---|---|\r\n| 1 | 가나다라 |\r\n| 2 | 마 |\r\n")

    def test_text_below_table_rejected(self):
        self.p.parent.mkdir(parents=True)
        self.p.write_text("| a |\n|---|\n| 1 |\n\n메모\n", encoding="utf-8")
        with self.assertRaises(ledger.LedgerError):
            ledger.append(self.p, {"a": "2"})


class LedgerReadTest(unittest.TestCase):
    def setUp(self):
        self.p = Path(tempfile.mkdtemp()) / "원장.md"

    def test_roundtrip_with_escape_and_br(self):
        ledger.append(self.p, {"날짜": "2026-10-14", "가게": "하루양말", "메모": "a|b\n둘째줄"})
        ledger.append(self.p, {"날짜": "2026-10-15", "가게": "가상가게"})
        self.assertEqual(ledger.read(self.p), [
            {"날짜": "2026-10-14", "가게": "하루양말", "메모": "a|b\n둘째줄"},
            {"날짜": "2026-10-15", "가게": "가상가게", "메모": ""},
        ])

    def test_missing_file_is_empty(self):
        self.assertEqual(ledger.read(self.p), [])

    def test_title_above_and_text_below_ignored(self):
        self.p.write_text("\ufeff# 원장\n\n| 날짜 | 가게 |\n|:---|---:|\n| 1 | 가 |\n| 2 |\n\n메모 줄\n| 3 | 표 밖 |\n",
                          encoding="utf-8")
        self.assertEqual(ledger.read(self.p), [{"날짜": "1", "가게": "가"}, {"날짜": "2", "가게": ""}])

    def test_too_many_cells_rejected(self):
        self.p.write_text("| a | b |\n|---|---|\n| 1 | 2 | 3 |\n", encoding="utf-8")
        with self.assertRaises(ledger.LedgerError):
            ledger.read(self.p)

    def test_no_separator_rejected(self):
        self.p.write_text("| a | b |\n| 1 | 2 |\n", encoding="utf-8")
        with self.assertRaises(ledger.LedgerError):
            ledger.read(self.p)


class StoreProfileTest(unittest.TestCase):
    def _write(self, text):
        p = Path(tempfile.mkdtemp()) / "브랜드_SSOT.md"
        p.write_text(text, encoding="utf-8")
        return p

    def test_low_stock(self):
        p = self._write("## 16. 저재고 기준\n<!-- 숫자 7 -->\n- 저재고 기준: 25개\n")
        self.assertEqual(store_profile.low_stock(path=p), 25)

    def test_low_stock_default(self):
        p = self._write("## 1. 파는 것\n")
        self.assertEqual(store_profile.low_stock(default=10, path=p), 10)
        self.assertEqual(store_profile.low_stock(path=Path("/nope/브랜드_SSOT.md")), 10)

    def test_missing_or_empty_file_gives_defaults(self):
        """브랜드_SSOT.md 는 선택 — 없음 · 빈 파일 · 폴더 자리여도 예외 없이 기본값."""
        d = Path(tempfile.mkdtemp())
        empty = self._write("")
        for p in (d / "없는파일.md", empty, d):
            self.assertEqual(store_profile.read(path=p), "")
            self.assertEqual(store_profile.low_stock(path=p), 10)
            self.assertEqual(store_profile.color_aliases(path=p), {})

    def test_is_filled(self):
        """스킬은 파일 존재가 아니라 is_filled() 로 판단 — 템플릿 그대로 False · 한 항목 True · 없음 False."""
        self.assertFalse(store_profile.is_filled(path=ROOT / "브랜드_SSOT.md"))          # 레포 템플릿 그대로
        self.assertTrue(store_profile.is_filled(path=ROOT / "브랜드_SSOT_예시.md"))
        self.assertFalse(store_profile.is_filled(path=Path(tempfile.mkdtemp()) / "없음.md"))
        tpl = (ROOT / "브랜드_SSOT.md").read_text(encoding="utf-8")
        self.assertFalse(store_profile.is_filled(path=self._write("")))
        one = tpl.replace("- 출고 마감 / 택배사 / 도착까지:", "- 출고 마감 / 택배사 / 도착까지: 오후 2시 · 하루택배", 1)
        self.assertNotEqual(one, tpl)
        self.assertTrue(store_profile.is_filled(path=self._write(one)))
        self.assertTrue(store_profile.is_filled(path=self._write(tpl.replace("1. Q:", "1. Q: 세탁기 돼요?", 1))))
        self.assertTrue(store_profile.is_filled(path=self._write(tpl.replace("| | | | |", "| 데일리 | 검정 | M | |", 1))))
        self.assertTrue(store_profile.is_filled(path=self._write(tpl.replace("- 저재고 기준: 10개", "- 저재고 기준: 20개", 1))))

    def test_color_aliases_ignores_comments(self):
        p = self._write("<!-- 예: 먹색 = 차콜 -->\n- 색 별칭(설명): 블랙 = 검정 = Black · 베이지 = 살구\n- 색 별칭: <!-- 예: 회색 = 그레이 -->\n")
        a = store_profile.color_aliases(path=p)
        self.assertEqual(a, {"블랙": "블랙", "검정": "블랙", "black": "블랙", "베이지": "베이지", "살구": "베이지"})

    def test_real_template_and_example(self):
        self.assertEqual(store_profile.low_stock(path=ROOT / "브랜드_SSOT.md"), 10)
        self.assertEqual(store_profile.color_aliases(path=ROOT / "브랜드_SSOT.md"), {})
        ex = ROOT / "브랜드_SSOT_예시.md"
        self.assertEqual(store_profile.low_stock(path=ex), 10)
        self.assertEqual(store_profile.color_aliases(path=ex)["카키"], "올리브")


class EnvTest(unittest.TestCase):
    def test_parse_and_required(self):
        p = Path(tempfile.mkdtemp()) / ".env"
        p.write_text("# c\nA=1 # 주석\nB=\"x # y\"\nexport C=3\nEMPTY=\n", encoding="utf-8")
        for k in ("A", "B", "C", "EMPTY"):
            os.environ.pop(k, None)
        self.assertEqual(env.load(p), {"A": "1", "B": "x # y", "C": "3", "EMPTY": ""})
        self.assertEqual(env.get("A", path=p), "1")
        self.assertIsNone(env.get("EMPTY", path=p))
        with self.assertRaises(env.MissingKeyError) as cm:
            env.get("EMPTY", required=True, path=p)
        self.assertIn("README", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
