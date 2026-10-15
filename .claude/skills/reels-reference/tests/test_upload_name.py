"""Gemini 업로드 재발 방지 — 네트워크 0. 실행: 레포 루트에서
    python3 -m unittest discover -s .claude/skills/reels-reference/tests

배경: google-genai 는 files.upload 에 경로(str/PathLike)를 주면 파일명을 HTTP 헤더
X-Goog-Upload-File-Name 에 넣는다. 헤더는 ASCII 만 되므로 한글 경로는 'ascii codec' 오류로 실패한다.
그래서 analyze_reel 은 경로가 아니라 파일 핸들로 올려야 한다(핸들이면 헤더에 이름이 안 실린다).
"""
import importlib.util
import io
import os
import sys
import tempfile
import types as pytypes
import unittest
from pathlib import Path
from unittest import mock

_spec = importlib.util.spec_from_file_location(
    "analyze_reel", Path(__file__).resolve().parent.parent / "scripts" / "analyze_reel.py")
ar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ar)


def _ascii(s: str) -> bool:
    return s.isascii()


class _Files:
    def __init__(self):
        self.upload_kwargs = None
        self.upload_file_ok = None      # 호출 시점에 핸들이 열려 있었는지

    def upload(self, **kw):
        self.upload_kwargs = kw
        f = kw.get("file")
        self.upload_file_ok = isinstance(f, io.IOBase) and not f.closed
        return pytypes.SimpleNamespace(state=None, name="files/x", uri="https://example/x")

    def get(self, **kw):
        raise AssertionError("state 가 없으면 폴링하지 않는다")

    def delete(self, **kw):
        pass


class _Models:
    def generate_content(self, **kw):
        return pytypes.SimpleNamespace(text='{"title": "t"}')


class _Client:
    def __init__(self, **kw):
        self.files = _Files()
        self.models = _Models()


def _fake_genai(holder):
    class Types:
        class UploadFileConfig:
            def __init__(self, **kw): self.kw = kw

        class GenerateContentConfig:
            def __init__(self, **kw): self.kw = kw

        class Part:
            @staticmethod
            def from_uri(**kw): return ("uri", kw)

            @staticmethod
            def from_text(**kw): return ("text", kw)

    def make_client(**kw):
        c = _Client()
        holder.append(c)
        return c

    genai = pytypes.ModuleType("google.genai")
    genai.Client = make_client
    genai.types = Types
    google = pytypes.ModuleType("google")
    google.genai = genai
    return {"google": google, "google.genai": genai, "google.genai.types": Types}


class UploadName(unittest.TestCase):
    def test_upload_gets_handle_or_ascii_path_even_under_korean_dir(self):
        with tempfile.TemporaryDirectory() as d:
            korean = Path(d) / "한글 폴더" / "건별"
            korean.mkdir(parents=True)
            video = korean / "원본.mp4"
            video.write_bytes(b"\x00\x00\x00\x18ftypmp42")
            clients = []
            with mock.patch.dict(sys.modules, _fake_genai(clients)):
                try:
                    ar.gemini_analyze("k", "m", "p", video, korean)
                except Exception:
                    pass   # 응답 파싱 쪽 실패는 이 테스트의 관심사가 아니다 — 업로드 인자만 본다
            self.assertEqual(len(clients), 1)
            files = clients[0].files
            arg = files.upload_kwargs["file"]
            if isinstance(arg, (str, os.PathLike)):
                self.assertTrue(_ascii(os.path.basename(arg)), f"한글 파일명이 헤더로 간다: {arg!r}")
            else:
                self.assertTrue(files.upload_file_ok, "파일 핸들이 닫힌 채/비핸들로 넘어갔다")


if __name__ == "__main__":
    unittest.main()
