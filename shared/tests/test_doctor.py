"""doctor 테스트 — 이 맥 상태 대신 가짜 Probe. 네트워크 0 · 값 미출력 단언.

    python3 -m unittest discover -s shared/tests -t .
"""
import io
import unittest
from contextlib import redirect_stdout

from shared import doctor

SECRET = "real-key-value-must-not-print"


class FakeProbe(doctor.Probe):
    def __init__(self, keys=(), channels=(), packages=(), token=False, filled=False, stock=False,
                 chrome="155.0.1", npx=True, py=(3, 11, 2)):
        self.keys, self.channels, self.packages = set(keys), set(channels), set(packages)
        self.token, self.filled, self.stock = token, filled, stock
        self.chrome, self.npx, self.py = chrome, npx, py

    def python_version(self): return self.py
    def which(self, name): return self.npx
    def chrome_version(self): return self.chrome
    def mcp_ok(self): return True
    def importable(self, module): return module in self.packages
    def has_key(self, name): return name in self.keys
    def channel_configured(self, channel): return channel in self.channels
    def cafe24_token(self): return self.token
    def store_filled(self): return self.filled
    def stock_csv(self): return self.stock
    # requirements() 는 진짜(레포의 requirements.txt) — 두 벌 금지 확인 겸


def marks(rows):
    return {(i, m) for i, m, _, _ in rows}


class DoctorTest(unittest.TestCase):
    def test_skills_table_steps_known(self):
        for s, meta in doctor.SKILLS.items():
            for step in meta["steps"]:
                self.assertIn(step, doctor.CHECKS, s)

    def test_reels_key_missing_and_packages_missing(self):
        rows = doctor.check("reels-reference", FakeProbe())
        bad = [t for _, m, t, _ in rows if m == doctor.BAD]
        self.assertIn("Gemini 키 없음", bad)
        self.assertTrue(any("google-genai" in t for t in bad))
        self.assertTrue(any("yt-dlp" in t for t in bad))
        self.assertTrue(all(f for _, m, _, f in rows if m == doctor.BAD))   # ❌ 마다 고치는 법

    def test_reels_all_ready(self):
        pr = FakeProbe(keys={"GEMINI_API_KEY"}, packages={"google.genai", "yt_dlp"}, filled=True)
        text, bad = doctor.report(["reels-reference"], pr)
        self.assertFalse(bad)
        self.assertNotIn(SECRET, text)

    def test_value_never_printed(self):
        class Leaky(FakeProbe):                       # 혹시 값을 돌려줘도 출력에 안 나와야 한다
            def has_key(self, name):
                return SECRET
        out = io.StringIO()
        with redirect_stdout(out):
            doctor.main(["all"], Leaky(channels={"naver"}))
        self.assertNotIn(SECRET, out.getvalue())

    def test_inquiry_no_channel_is_bad_shelf_is_optional(self):
        self.assertIn((2, doctor.BAD), marks(doctor.check("inquiry-inbox", FakeProbe())))
        shelf = marks(doctor.check("shelf-check", FakeProbe(stock=True)))
        self.assertNotIn((2, doctor.BAD), shelf)          # ④ 는 키 없이 csv 로도 된다
        self.assertIn((5, doctor.OK), shelf)              # output/매대/재고표.csv
        texts = [t for _, _, t, _ in doctor.check("shelf-check", FakeProbe())]
        self.assertTrue(any("output/매대/재고표.csv" in t for t in texts))

    def test_ip_note_only_for_ip_channels(self):
        def ip_rows(chs):
            return [(m, t) for _, m, t, _ in doctor.check("inquiry-inbox", FakeProbe(channels=chs)) if "IP" in t]
        self.assertEqual(ip_rows({"cafe24"}), [])
        rows = ip_rows({"naver", "coupang"})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], doctor.OPT)          # 확인 못 하는 항목 — ❌ 로 막지 않는다
        self.assertIn("네이버·쿠팡", rows[0][1])

    def test_bcrypt_only_when_naver(self):
        rows = doctor.check("inquiry-inbox", FakeProbe(channels={"coupang"}))
        self.assertIn((3, doctor.OPT), marks(rows))
        rows = doctor.check("inquiry-inbox", FakeProbe(channels={"naver"}))
        self.assertIn((3, doctor.BAD), marks(rows))
        rows = doctor.check("inquiry-inbox", FakeProbe(channels={"naver"}, packages={"bcrypt"}))
        self.assertIn((3, doctor.OK), marks(rows))

    def test_cafe24_login(self):
        self.assertIn((4, doctor.BAD), marks(doctor.check("inquiry-inbox", FakeProbe(channels={"cafe24"}))))
        self.assertIn((4, doctor.OK), marks(doctor.check("inquiry-inbox", FakeProbe(channels={"cafe24"}, token=True))))

    def test_chrome_old_or_missing_and_store_optional(self):
        self.assertIn((3, doctor.BAD), marks(doctor.check("semi-auto-crawler", FakeProbe(chrome="141.0"))))
        self.assertIn((3, doctor.BAD), marks(doctor.check("semi-auto-crawler", FakeProbe(chrome=None))))
        self.assertIn((6, doctor.OPT), marks(doctor.check("detail-page", FakeProbe(packages={"PIL"}))))
        _, bad = doctor.report(["detail-page"], FakeProbe(packages={"PIL"}))
        self.assertFalse(bad)                             # 브랜드_SSOT.md 비어 있어도 ❌ 아님

    def test_unknown_skill(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(doctor.main(["nope"], FakeProbe()), 2)


if __name__ == "__main__":
    unittest.main()
