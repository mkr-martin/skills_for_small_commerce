"""setup_keys 테스트 — 창(osascript)은 가짜로 바꿔 끼운다. 실제 창은 띄우지 않는다.

    python3 -m unittest discover -s shared/tests -t .
"""
import io
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from shared import env, setup_keys

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / ".env.example"
SECRET = "s3cr3t-VALUE-never-print"


class FakeUI:
    """dialog 자리. answers = {키 이름: 값 또는 None(건너뛰기)} · overwrite = 덮어쓰기 창 대답."""

    def __init__(self, answers, overwrite=False):
        self.answers, self.overwrite = answers, overwrite
        self.asked, self.confirms, self.shown = [], [], []

    def ask(self, message, hidden=False):
        name = message.split("] ", 1)[1].split("\n", 1)[0]
        self.asked.append((name, hidden))
        return self.answers.get(name)

    def confirm(self, message, yes="예", no="아니오"):
        self.confirms.append(message)
        return self.overwrite

    def show(self, message):
        self.shown.append(message)


class SetupKeysTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.env = self.dir / ".env"

    def run_main(self, argv, ui):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = setup_keys.main(argv, ui=ui, env_path=self.env, example=EXAMPLE)
        return rc, out.getvalue()

    def test_key_list_comes_from_example(self):
        names = [k["name"] for k in setup_keys.example_keys(EXAMPLE)]
        lines = [ln.split("=", 1)[0] for ln in EXAMPLE.read_text(encoding="utf-8").splitlines()
                 if ln and not ln.startswith("#") and "=" in ln]
        self.assertEqual(names, lines)
        opt = {k["name"] for k in setup_keys.example_keys(EXAMPLE) if k["optional"]}
        self.assertEqual(opt, {"GEMINI_MODEL", "CAFE24_INQUIRY_BOARDS"})

    def test_new_env_from_template_value_never_printed(self):
        ui = FakeUI({"NAVER_COMMERCE_CLIENT_ID": "naver-id", "NAVER_COMMERCE_CLIENT_SECRET": SECRET})
        rc, out = self.run_main(["--only", "naver"], ui)
        self.assertEqual(rc, 0)
        self.assertNotIn(SECRET, out)
        self.assertNotIn("naver-id", out)
        self.assertTrue(all(SECRET not in m for m in ui.shown))
        vals = env.load(self.env)
        self.assertEqual(vals["NAVER_COMMERCE_CLIENT_SECRET"], SECRET)
        self.assertEqual(vals["NAVER_COMMERCE_CLIENT_ID"], "naver-id")
        self.assertIn("GEMINI_API_KEY", vals)                         # 틀(.env.example)의 다른 줄도 있다
        self.assertEqual(stat.S_IMODE(os.stat(self.env).st_mode), 0o600)
        self.assertEqual([a for a in ui.asked], [("NAVER_COMMERCE_CLIENT_ID", False),
                                                 ("NAVER_COMMERCE_CLIENT_SECRET", True)])
        self.assertIn("네이버 ✅", out)

    def test_existing_lines_kept_and_overwrite_asked(self):
        self.env.write_text("# 내 메모\nGEMINI_API_KEY=old-gemini\nCUSTOM=keep me\n", encoding="utf-8")
        ui = FakeUI({"GEMINI_API_KEY": "new value #1"}, overwrite=False)
        self.run_main(["--only", "gemini"], ui)
        self.assertEqual(len(ui.confirms), 1)                          # 이미 있음 → 덮어쓸지 먼저 묻는다
        self.assertEqual(ui.asked, [])                                 # '그대로 두기' → 입력 창 안 띄움
        self.assertEqual(env.load(self.env)["GEMINI_API_KEY"], "old-gemini")

        ui = FakeUI({"GEMINI_API_KEY": "new value #1"}, overwrite=True)
        self.run_main(["--only", "gemini"], ui)
        text = self.env.read_text(encoding="utf-8")
        self.assertIn("# 내 메모", text)
        self.assertIn("CUSTOM=keep me", text)
        self.assertEqual(env.load(self.env)["GEMINI_API_KEY"], "new value #1")   # 공백·# 도 그대로 읽힌다

    def test_cancel_skips_and_status_table(self):
        ui = FakeUI({"COUPANG_ACCESS_KEY": "ak", "CAFE24_MALL_ID": "harumall", "CAFE24_CLIENT_ID": "cid",
                     "CAFE24_CLIENT_SECRET": SECRET, "CAFE24_REDIRECT_URI": "https://example.com/cb"})
        rc, out = self.run_main([], ui)
        self.assertNotIn(SECRET, out)
        self.assertIn("Gemini ❌ 없음", out)
        self.assertIn("네이버 ❌ 없음", out)
        self.assertIn("쿠팡 ⚠️ 일부 빔", out)
        self.assertIn("카페24 ✅", out)
        self.assertIn("카페24 로그인", out)                            # 카페24 키를 넣었으면 로그인 안내
        asked = [n for n, _ in ui.asked]
        self.assertNotIn("GEMINI_MODEL", asked)                        # (선택) 키는 묻지 않는다
        self.assertNotIn("CAFE24_INQUIRY_BOARDS", asked)
        self.assertEqual(env.load(self.env).get("COUPANG_SECRET_KEY"), "")   # 건너뛴 키는 빈 칸 그대로

    def test_single_optional_key(self):
        ui = FakeUI({"CAFE24_INQUIRY_BOARDS": "6,9"})
        self.run_main(["--key", "CAFE24_INQUIRY_BOARDS"], ui)
        self.assertEqual(ui.asked, [("CAFE24_INQUIRY_BOARDS", False)])
        self.assertEqual(env.load(self.env)["CAFE24_INQUIRY_BOARDS"], "6,9")

    def test_bad_only(self):
        with self.assertRaises(SystemExit):
            self.run_main(["--only", "kakao"], FakeUI({}))


if __name__ == "__main__":
    unittest.main()
