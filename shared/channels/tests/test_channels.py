"""채널 인증·요청 테스트 — 네트워크 0 · 가짜 응답만. 실행: 레포 루트에서
    python3 -m unittest discover -s shared/channels/tests -t .
"""
import base64
import hashlib
import hmac
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from shared.channels import ChannelError, cafe24, coupang, naver

FAKE_ENV = {
    "NAVER_COMMERCE_CLIENT_ID": "nid", "NAVER_COMMERCE_CLIENT_SECRET": "$2a$04$abcdefghijklmnopqrstuv",
    "COUPANG_ACCESS_KEY": "ak", "COUPANG_SECRET_KEY": "sk", "COUPANG_VENDOR_ID": "A00000001",
    "CAFE24_MALL_ID": "harusocks", "CAFE24_CLIENT_ID": "cid", "CAFE24_CLIENT_SECRET": "csec",
    "CAFE24_REDIRECT_URI": "https://example.com/cb",
}
EMPTY_ENV_FILE = Path(tempfile.mkdtemp()) / ".env"   # 실제 루트 .env 를 읽지 않게


def env_get(name, required=False, path=None):
    v = FAKE_ENV.get(name)
    if v is None and required:
        raise RuntimeError(name)
    return v


class Base(unittest.TestCase):
    def setUp(self):
        p = mock.patch("shared.env.get", side_effect=env_get)
        p.start()
        self.addCleanup(p.stop)


class ConfiguredTest(Base):
    def test_all_configured_with_fake_env(self):
        self.assertTrue(naver.configured())
        self.assertTrue(coupang.configured())
        self.assertTrue(cafe24.configured())

    def test_missing_key_means_not_configured(self):
        with mock.patch("shared.env.get", side_effect=lambda n, required=False, path=None:
                        None if n == "COUPANG_SECRET_KEY" else env_get(n)):
            self.assertFalse(coupang.configured())


class CoupangTest(Base):
    def test_signature_matches_documented_recipe(self):
        now = datetime(2026, 10, 14, 3, 4, 5, tzinfo=timezone.utc)
        got = coupang.authorization("GET", "/v2/x", "a=1&b=2", now=now)
        sig = hmac.new(b"sk", b"261014T030405ZGET/v2/xa=1&b=2", hashlib.sha256).hexdigest()
        self.assertEqual(got, f"CEA algorithm=HmacSHA256, access-key=ak, signed-date=261014T030405Z, signature={sig}")

    def test_request_signs_the_same_query_it_sends(self):
        seen = {}

        def fake_http(method, url, headers, body=None):
            seen.update(method=method, url=url, headers=headers)
            return {"code": 200}

        with mock.patch.object(coupang, "http_json", side_effect=fake_http), \
                mock.patch.object(coupang, "MIN_GAP", 0):
            coupang.request("get", "/v2/p", {"vendorId": "A00000001", "inquiryStartAt": "2026-10-01"})
        self.assertEqual(seen["method"], "GET")
        self.assertTrue(seen["url"].endswith("/v2/p?vendorId=A00000001&inquiryStartAt=2026-10-01"))
        auth = seen["headers"]["Authorization"]
        dt = auth.split("signed-date=")[1].split(",")[0]
        expect = hmac.new(b"sk", f"{dt}GET/v2/pvendorId=A00000001&inquiryStartAt=2026-10-01".encode(),
                          hashlib.sha256).hexdigest()
        self.assertIn(f"signature={expect}", auth)
        self.assertEqual(seen["headers"]["X-Requested-By"], "A00000001")


class NaverTest(Base):
    def setUp(self):
        super().setUp()
        naver._token.clear()

    def test_token_form_and_bearer(self):
        calls = []

        def fake_http(method, url, headers=None, body=None, form=None):
            calls.append((method, url, headers, form))
            if url.endswith("/oauth2/token"):
                return {"access_token": "tok", "expires_in": 10800}
            return {"ok": True}

        with mock.patch.object(naver, "http_json", side_effect=fake_http), \
                mock.patch.object(naver, "_sign", return_value="SIGN"):
            naver.request("GET", "/v1/contents/qnas", {"page": 1})
            naver.request("GET", "/v1/contents/qnas", {"page": 2})
        token_calls = [c for c in calls if c[1].endswith("/oauth2/token")]
        self.assertEqual(len(token_calls), 1, "토큰은 한 번만 받아 재사용")
        form = token_calls[0][3]
        self.assertEqual(form["grant_type"], "client_credentials")
        self.assertEqual(form["type"], "SELF")
        self.assertEqual(form["client_secret_sign"], "SIGN")
        self.assertEqual(calls[1][1], "https://api.commerce.naver.com/external/v1/contents/qnas?page=1")
        self.assertEqual(calls[1][2]["Authorization"], "Bearer tok")

    def test_sign_is_base64_of_bcrypt(self):
        try:
            import bcrypt
        except ImportError:
            with self.assertRaises(ChannelError):
                naver._sign("nid", FAKE_ENV["NAVER_COMMERCE_CLIENT_SECRET"], "1")
            return
        salt = bcrypt.gensalt(rounds=4).decode()
        sign = naver._sign("nid", salt, "1700000000000")
        self.assertEqual(base64.b64decode(sign), bcrypt.hashpw(b"nid_1700000000000", salt.encode()))


class Cafe24Test(Base):
    def setUp(self):
        super().setUp()
        self.tok = Path(tempfile.mkdtemp()) / "cafe24.token.json"
        p = mock.patch.object(cafe24, "token_path", return_value=self.tok)
        p.start()
        self.addCleanup(p.stop)

    def _write(self, access, minutes_left, refresh="r1"):
        at = (datetime.now(cafe24.KST) + timedelta(minutes=minutes_left)).strftime("%Y-%m-%dT%H:%M:%S.000")
        self.tok.write_text(json.dumps({"access_token": access, "expires_at": at, "refresh_token": refresh}))

    def test_no_token_file_asks_login(self):
        with self.assertRaises(ChannelError) as cm:
            cafe24.request("GET", "/boards")
        self.assertIn("login", str(cm.exception))

    def test_login_via_dialog(self):
        """login — 브라우저 열기·입력 창은 가짜. 돌아온 주소의 code·state 를 검사해 토큰 요청."""
        class UI:
            def __init__(self, answer):
                self.answer = answer

            def ask(self, message, hidden=False):
                return self.answer
        with mock.patch.object(cafe24.secrets, "token_urlsafe", return_value="st"), \
                mock.patch.object(cafe24.subprocess, "run") as run, \
                mock.patch.object(cafe24, "_token_call", return_value={"access_token": "x"}) as tc, \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cafe24.login(ui=UI("https://example.com/cb?code=C1&state=st")), 0)
            self.assertEqual(tc.call_args[0][0]["code"], "C1")
            cmds = [c[0][0][0] for c in run.call_args_list]
            self.assertEqual(cmds[:2], ["pbcopy", "open"])
            self.assertNotIn("cid", out.getvalue())          # Client ID 는 화면에 찍지 않는다
            self.assertNotIn("client_id", out.getvalue())
            self.assertEqual(cafe24.login(ui=UI("https://example.com/cb?code=C1&state=other")), 1)
            self.assertEqual(cafe24.login(ui=UI(None)), 1)              # 건너뛰기
            self.assertEqual(tc.call_count, 1)

    def test_valid_token_used_as_is(self):
        self._write("a1", 60)
        with mock.patch.object(cafe24, "http_json", return_value={"boards": []}) as h:
            cafe24.request("GET", "/boards", {"shop_no": 1})
        url, headers = h.call_args[0][1], h.call_args[0][2]
        self.assertEqual(url, "https://harusocks.cafe24api.com/api/v2/admin/boards?shop_no=1")
        self.assertEqual(headers["Authorization"], "Bearer a1")

    def test_expired_token_refreshed_and_rotated(self):
        self._write("old", 2, refresh="r1")
        seen = []

        def fake_http(method, url, headers=None, body=None, form=None):
            seen.append((url, headers, form))
            if url.endswith("/oauth/token"):
                return {"access_token": "new", "refresh_token": "r2", "expires_at": "2099-01-01T00:00:00.000"}
            return {"articles": []}

        with mock.patch.object(cafe24, "http_json", side_effect=fake_http):
            cafe24.request("GET", "/boards/6/articles")
        self.assertEqual(seen[0][2], {"grant_type": "refresh_token", "refresh_token": "r1"})
        self.assertEqual(seen[0][1]["Authorization"], "Basic " + base64.b64encode(b"cid:csec").decode())
        self.assertEqual(seen[1][1]["Authorization"], "Bearer new")
        saved = json.loads(self.tok.read_text())
        self.assertEqual(saved["refresh_token"], "r2", "바뀐 리프레시 토큰을 저장해야 다음에 쓸 수 있다")
        self.assertEqual(oct(os.stat(self.tok).st_mode & 0o777), "0o600")

    def test_401_retries_once_after_refresh(self):
        self._write("a1", 60)
        n = {"api": 0}

        def fake_http(method, url, headers=None, body=None, form=None):
            if url.endswith("/oauth/token"):
                return {"access_token": "a2", "refresh_token": "r2", "expires_at": "2099-01-01T00:00:00.000"}
            n["api"] += 1
            if n["api"] == 1:
                raise ChannelError("HTTP 401", status=401)
            return {"ok": headers["Authorization"]}

        with mock.patch.object(cafe24, "http_json", side_effect=fake_http):
            self.assertEqual(cafe24.request("GET", "/boards"), {"ok": "Bearer a2"})

    def test_authorize_url_has_read_scope_only(self):
        url = cafe24.authorize_url("st")
        self.assertTrue(url.startswith("https://harusocks.cafe24api.com/api/v2/oauth/authorize?response_type=code"))
        self.assertIn("scope=mall.read_community", url)
        self.assertNotIn("write", url)


class HttpJsonTest(unittest.TestCase):
    """shared.channels.http_json — 실측(2026-10-14)에서 나온 두 모양."""

    @staticmethod
    def _err(code, raw, headers):
        import urllib.error
        from email.message import Message
        m = Message()
        for k, v in headers.items():
            m[k] = v
        return urllib.error.HTTPError("https://x", code, "err", m, io.BytesIO(raw))

    def test_gzip_error_body_is_readable(self):
        # 쿠팡 403 은 Accept-Encoding 없이도 gzip 본문을 준다 → 사장님이 IP 문구를 읽을 수 있어야 한다
        import gzip
        from shared import channels
        body = gzip.compress(b'{"message":"Your ip address 1.2.3.4 is not allowed"}')
        err = self._err(403, body, {"Content-Encoding": "gzip"})
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(ChannelError) as cm:
                channels.http_json("GET", "https://x")
        self.assertEqual(cm.exception.status, 403)
        self.assertIn("1.2.3.4 is not allowed", str(cm.exception))

    def test_429_waits_and_retries(self):
        # 네이버 GW.RATE_LIMIT(429) 실측 — 쉬었다 다시 부르면 이어서 된다
        from shared import channels

        class Resp:
            headers = {}

            def read(self):
                return b'{"ok": true}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        calls = [self._err(429, b"{}", {"Retry-After": "0"}), Resp()]
        with mock.patch("urllib.request.urlopen", side_effect=lambda *a, **k: (
                (_ for _ in ()).throw(calls.pop(0)) if isinstance(calls[0], Exception) else calls.pop(0))), \
                mock.patch.object(channels.time, "sleep") as sl:
            self.assertEqual(channels.http_json("GET", "https://x"), {"ok": True})
        sl.assert_called_once_with(0.0)

    def test_429_gives_up_after_retries(self):
        from shared import channels
        with mock.patch("urllib.request.urlopen",
                        side_effect=lambda *a, **k: (_ for _ in ()).throw(self._err(429, b"{}", {}))), \
                mock.patch.object(channels.time, "sleep") as sl:
            with self.assertRaises(ChannelError) as cm:
                channels.http_json("GET", "https://x")
        self.assertEqual(cm.exception.status, 429)
        self.assertEqual([c.args[0] for c in sl.call_args_list], [1.0, 2.0, 4.0])


class ErrorTextTest(Base):
    """오류 문장 — 403 IP 거부엔 등록 안내를 붙이고, .env 키 값(업체코드 등)은 *** 로 가린다(실측 2026-10-14)."""

    COUPANG_403 = (b'{"code":403,"message":"Your ip address 1.2.3.4 is not allowed for this request. '
                   b'/v2/providers/openapi/apis/api/v5/vendors/A00000001/onlineInquiries"}')

    def _raise(self, code, raw):
        from shared import channels
        err = HttpJsonTest._err(code, raw, {})
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(ChannelError) as cm:
                channels.http_json("GET", "https://x")
        return cm.exception

    def test_ip_403_adds_registration_help(self):
        from shared import channels
        e = self._raise(403, self.COUPANG_403)
        self.assertIn(channels.IP_HELP, str(e))
        self.assertIn("api.ipify.org", str(e))

    def test_vendor_id_masked_in_message_and_body(self):
        e = self._raise(403, self.COUPANG_403)
        self.assertNotIn("A00000001", str(e))
        self.assertNotIn("A00000001", e.body)
        self.assertIn("/vendors/***/onlineInquiries", str(e))

    def test_other_403_has_no_ip_help(self):
        from shared import channels
        e = self._raise(403, b'{"message":"insufficient scope"}')
        self.assertNotIn(channels.IP_HELP, str(e))
        self.assertFalse(channels.ip_blocked(401, "Your ip address is not allowed"))
        self.assertFalse(channels.ip_blocked(403, "zip file description"))   # 낱말 ip 만

    def test_coupang_request_error_masks_vendor_in_path(self):
        """쿠팡 모듈을 거친 실제 경로 — 오류 문장 어디에도 업체코드가 남지 않는다."""
        with mock.patch("urllib.request.urlopen", side_effect=HttpJsonTest._err(403, self.COUPANG_403, {})), \
                mock.patch.object(coupang, "MIN_GAP", 0):
            with self.assertRaises(ChannelError) as cm:
                coupang.request("GET", f"/v2/providers/openapi/apis/api/v5/vendors/{coupang.vendor_id()}/onlineInquiries")
        self.assertNotIn("A00000001", str(cm.exception))

    def test_short_values_are_not_masked(self):
        from shared import channels
        self.assertEqual(channels.scrub("ak sk nid"), "ak sk nid")   # 4자 미만 값은 건너뜀(다른 글자를 망가뜨리지 않게)


if __name__ == "__main__":
    unittest.main()
