"""문의 모으기 테스트 — 네트워크 0. 응답은 각 채널 공식 문서의 예시 모양을 본뜬 가짜.
실행(레포 루트에서): python3 -m unittest discover -s .claude/skills/inquiry-inbox/tests
"""
import csv
import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load(name):
    """scripts/ 안 모듈을 이름 그대로 sys.modules 에 올린다(서로 'from common import' 하므로)."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


common = _load("common")
inq = _load("inquiries")
fetch = _load("fetch")


class ParseTest(unittest.TestCase):
    def test_naver_customer_inquiry(self):
        rows = inq.naver_parse_customer({"content": [
            {"inquiryNo": 101, "category": "배송", "title": "언제 와요", "inquiryContent": "주문했는데요",
             "inquiryRegistrationDateTime": "2026-10-13T01:02:03.071Z", "answered": False,
             "orderId": "1", "productName": "하루양말 3족", "productOrderOption": "흰색",
             "customerName": "김하루"},
            {"inquiryNo": 102, "title": "x", "inquiryContent": "y", "answered": True,
             "inquiryRegistrationDateTime": "2026-10-13T01:02:03.071Z", "orderId": "2", "customerName": "이"}]})
        self.assertEqual(len(rows), 1, "답변 완료 건은 뺀다")
        r = rows[0]
        self.assertEqual(r["id"], "naver:inquiry:101")
        self.assertEqual(r["종류"], "고객문의")
        self.assertEqual(r["접수일"], "2026-10-13 10:02")      # UTC → 한국시간
        self.assertEqual(r["상품"], "하루양말 3족 (흰색)")
        self.assertEqual(r["고객"], "김*루")
        self.assertEqual(r["문의 원문"], "[배송] 언제 와요\n주문했는데요")
        self.assertEqual((r["답변"], r["상태"]), ("", "미답변"))

    def test_naver_product_qna(self):
        rows = inq.naver_parse_qna({"contents": [
            {"createDate": "2025-02-03T22:36:42.008+09:00", "question": "사이즈 커요?", "answered": False,
             "productId": 5, "productName": "발목양말", "maskedWriterId": "har****", "questionId": 77}]})
        self.assertEqual(rows[0]["id"], "naver:qna:77")
        self.assertEqual(rows[0]["고객"], "har****", "이미 가려진 값은 그대로")
        self.assertEqual(rows[0]["접수일"], "2025-02-03 22:36")

    def test_coupang_online_skips_answered(self):
        rows = inq.coupang_parse_online({"content": [
            {"inquiryId": 39352323, "sellerProductId": 786583589, "content": "스판 강한가요?",
             "inquiryAt": "2025-01-15T14:17:13.973885-08:00", "commentDtoList": []},
            {"inquiryId": 2, "content": "답 달린 건", "inquiryAt": "2025-01-15T14:17:13.973885-08:00",
             "commentDtoList": [{"inquiryCommentId": 1, "content": "답"}]}]})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "coupang:online:39352323")
        self.assertEqual(rows[0]["상품"], "등록상품 786583589")
        self.assertEqual(rows[0]["접수일"], "2025-01-16 07:17")   # 6자리 소수·-08:00 도 읽는다

    def test_coupang_callcenter_uses_transfer_post(self):
        rows = inq.coupang_parse_callcenter({"content": [{
            "inquiryId": 1015668177, "itemName": "하루양말 L", "content": "상담이력",
            "inquiryAt": "2025-01-15T14:17:13.973885-08:00", "receiptCategory": "기타문의>기타",
            "replies": [
                {"answerId": 11, "partnerTransferStatus": "answered", "content": "옛 이관"},
                {"answerId": 1027082307, "partnerTransferStatus": "requestAnswer", "content": "[판매자이관] 반송 확인 부탁"}]}]})
        r = rows[0]
        self.assertEqual(r["id"], "coupang:cs:1015668177:1027082307")
        self.assertEqual(r["종류"], "고객센터")
        self.assertEqual(r["문의 원문"], "[기타문의>기타]\n[판매자이관] 반송 확인 부탁")

    def test_cafe24_fetch_without_boards_says_how(self):
        """게시판 번호(.env CAFE24_INQUIRY_BOARDS)가 비면 안내 문장으로 멈춘다(이름 오류로 죽지 않게)."""
        with mock.patch.object(inq.env, "get", return_value=None):
            with self.assertRaises(inq.ChannelError) as cm:
                inq.cafe24_fetch(7)
        self.assertIn("CAFE24_INQUIRY_BOARDS 가 비어 있습니다", str(cm.exception))
        self.assertIn("--key CAFE24_INQUIRY_BOARDS", str(cm.exception))

    def test_cafe24_articles(self):
        rows = inq.cafe24_parse_articles(6, [
            {"article_no": 5, "title": "배송문의", "content": "<p>언제&nbsp;와요?</p>", "writer": "박양말",
             "created_date": "2026-10-12T09:00:00+09:00", "product_no": 12, "deleted": "F", "reply_depth": 0},
            {"article_no": 6, "title": "Re:", "content": "답변글", "reply_depth": 1, "deleted": "F"},
            {"article_no": 7, "title": "삭제", "content": "x", "deleted": "T"},
            {"article_no": 8, "title": "1:1 처리완료", "content": "x", "deleted": "F", "reply_status": "C"},
        ], "상품문의")
        self.assertEqual([r["id"] for r in rows], ["cafe24:6:5"])
        self.assertEqual(rows[0]["문의 원문"], "배송문의\n언제 와요?")
        self.assertEqual(rows[0]["고객"], "박*말")
        self.assertEqual(rows[0]["상품"], "상품번호 12")

    def test_mask(self):
        self.assertEqual(common.mask_name("남궁하루"), "남**루")
        self.assertEqual(common.mask_name("김하"), "김*")
        self.assertEqual(common.mask_name("harusocks"), "har***")
        self.assertEqual(common.mask_name(""), "")

    def test_coupang_windows_are_at_most_7_days(self):
        from datetime import date
        wins = list(inq._coupang_windows(20))
        for s, e in wins:
            self.assertLessEqual((date.fromisoformat(e) - date.fromisoformat(s)).days, 6)
        self.assertEqual(len(wins), 3)


class FetchFlowTest(unittest.TestCase):
    """fetch.py 를 끝까지 — 채널 함수만 가짜로 바꿔 끼운다."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp()) / "문의"
        self.batch = [inq._row("naver:qna:1", "네이버", "상품문의", "2026-10-13 10:00", "발목양말", "har****", "커요?"),
                      inq._row("naver:qna:2", "네이버", "상품문의", "2026-10-13 11:00", "발목양말", "", "작아요?")]

    def run_fetch(self, *extra):
        fake_fetch = {"naver": lambda days: list(self.batch),
                      "coupang": lambda days: [], "cafe24": lambda days: []}
        conf = {"naver": True, "coupang": False, "cafe24": True}
        mods = {k: mock.Mock(configured=mock.Mock(return_value=v), KEYS=[k.upper() + "_KEY"]) for k, v in conf.items()}
        out = io.StringIO()
        with mock.patch.object(fetch, "FETCH", fake_fetch), mock.patch.object(fetch, "MODULE", mods), \
                mock.patch.object(sys, "argv", ["fetch.py", "--dir", str(self.dir), *extra]), redirect_stdout(out):
            self.assertEqual(fetch.main(), 0)
        return out.getvalue()

    def read(self):
        with (self.dir / "문의함.csv").open(encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))

    def test_first_run_writes_csv_and_reports_missing_keys(self):
        out = self.run_fetch()
        self.assertIn("쿠팡: 키 없음", out)
        self.assertIn("네이버: 미답변 2건 중 새로 2건 추가", out)
        rows = self.read()
        self.assertEqual(list(rows[0].keys()), common.COLUMNS)
        self.assertEqual([r["id"] for r in rows], ["naver:qna:1", "naver:qna:2"])
        self.assertTrue((self.dir / "문의함.csv").read_bytes().startswith(b"\xef\xbb\xbf"), "엑셀용 BOM")

    def test_rerun_skips_known_ids_and_keeps_owner_edits(self):
        self.run_fetch()
        # 사장님이 엑셀에서 답변·상태를 쓰고 '메모' 열을 하나 더 만들었다
        rows = self.read()
        rows[0]["답변"], rows[0]["상태"], rows[0]["메모"] = "넉넉해요", "답함", "단골"
        rows[1]["메모"] = ""
        with (self.dir / "문의함.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=common.COLUMNS + ["메모"])
            w.writeheader()
            w.writerows(rows)
        self.batch.append(inq._row("naver:qna:3", "네이버", "상품문의", "", "", "", "새 문의"))
        self.batch.append(dict(self.batch[-1]))      # 같은 응답에 겹쳐 온 건도 한 번만
        out = self.run_fetch()
        self.assertIn("새로 1건", out)
        rows = self.read()
        self.assertEqual([r["id"] for r in rows], ["naver:qna:1", "naver:qna:2", "naver:qna:3"])
        self.assertEqual((rows[0]["답변"], rows[0]["상태"], rows[0]["메모"]), ("넉넉해요", "답함", "단골"))

    def test_cp949_csv_from_excel_still_reads(self):
        self.dir.mkdir(parents=True)
        (self.dir / "문의함.csv").write_bytes(
            ("id,채널,답변,상태\nnaver:qna:1,네이버,좋아요,답함\n").encode("cp949"))
        self.run_fetch()
        rows = self.read()
        self.assertEqual(rows[0]["답변"], "좋아요")
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
