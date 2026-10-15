"""대시보드 부품 테스트 — 네트워크 0. 실행: 레포 루트에서
    python3 -m unittest discover -s dashboard/tests
"""
import importlib.util
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "make_dashboard", Path(__file__).resolve().parent.parent / "make_dashboard.py")
md = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(md)


class InlineLink(unittest.TestCase):
    def test_link_url_escaped_once(self):
        out = md._inline("[원문](https://a.com/x?a=1&b=2)")
        self.assertIn('href="https://a.com/x?a=1&amp;b=2"', out)   # 두 번 escape 되면 &amp;amp; 가 된다
        self.assertNotIn("&amp;amp;", out)

    def test_quote_in_url_cannot_break_attribute(self):
        out = md._inline('[x](https://a.com/"onmouseover=1)')
        self.assertNotIn('"onmouseover', out)


if __name__ == "__main__":
    unittest.main()
