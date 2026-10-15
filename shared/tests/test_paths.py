"""결과물 경로 테스트 — 임시 폴더(root)에만 쓴다 · 네트워크 0.

    python3 -m unittest discover -s shared/tests -t .
"""
import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from shared import paths

NOW = datetime(2026, 10, 15, 0, 5, tzinfo=timezone.utc)   # KST 09:05


class PathsTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_skill_root_made_under_root(self):
        d = paths.skill_root("detail-page", root=self.root)
        self.assertEqual(d, self.root / "output_detail-page")
        self.assertTrue(d.is_dir())
        self.assertEqual(paths.skill_root("detail-page", root=self.root), d)   # 두 번 불러도 됨

    def test_default_root_is_repo(self):
        self.assertEqual(paths.repo_root(), Path(paths.__file__).resolve().parents[1])

    def test_run_dir_format_kst(self):
        d = paths.run_dir("detail-page", "하루양말", root=self.root, now=NOW)
        self.assertEqual(d, self.root / "output_detail-page" / "20261015_0905_하루양말")
        self.assertTrue(d.is_dir())

    def test_run_dir_without_name(self):
        d = paths.run_dir("shelf-check", root=self.root, now=NOW)
        self.assertEqual(d.name, "20261015_0905")
        self.assertEqual(paths.run_dir("shelf-check", "  ", root=self.root, now=NOW).name, "20261015_0905_2")

    def test_run_dir_real_clock_shape(self):
        d = paths.run_dir("x", "a", root=self.root)
        self.assertRegex(d.name, r"^\d{8}_\d{4}_a$")

    def test_duplicate_same_minute_gets_suffix(self):
        names = [paths.run_dir("reels-reference", "abc", root=self.root, now=NOW).name for _ in range(3)]
        self.assertEqual(names, ["20261015_0905_abc", "20261015_0905_abc_2", "20261015_0905_abc_3"])

    def test_name_cleaned(self):
        self.assertEqual(paths.clean_name(" 하루 양말/세일:가을\\판 "), "하루_양말세일가을판")
        self.assertEqual(paths.clean_name("a  \t b"), "a_b")
        self.assertEqual(len(paths.clean_name("가" * 100)), 40)
        self.assertEqual(paths.clean_name("///"), "")
        d = paths.run_dir("detail-page", "a/b c", root=self.root, now=NOW)
        self.assertEqual(d.parent, self.root / "output_detail-page")   # 슬래시로 폴더가 깊어지지 않는다
        self.assertEqual(d.name, "20261015_0905_ab_c")
        self.assertFalse(re.search(r"[/\\:\s]", d.name))


if __name__ == "__main__":
    unittest.main()
