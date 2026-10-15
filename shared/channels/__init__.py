"""판매 채널 API — 인증·요청 한 벌(네이버 커머스 · 쿠팡 윙 · 카페24). 표준 라이브러리만(네이버만 bcrypt).

각 모듈 공통 인터페이스:
    configured() -> bool                                   # 필요한 키가 .env 에 다 있나
    request(method, path, params=None, body=None) -> dict  # 서명·토큰 처리 포함 · 실패 시 ChannelError

    from shared.channels import naver, coupang, cafe24, ChannelError

공식 문서에 적힌 엔드포인트·필드만 쓴다. 문서로 확인 못 한 부분은 '미확인 — 실측 필요' 주석.

오류 문장(ChannelError)은 사장님 화면에 그대로 찍힌다 — 그래서 여기서 두 가지를 한 번에 처리한다:
- 응답 본문·주소에 섞여 나온 키 값(업체코드 · Client ID 등 .env 에서 읽은 값)은 *** 로 가린다(SECRET_KEYS).
- 403 이 '호출 IP 가 허용 목록에 없음' 이면 IP 등록 안내(IP_HELP)를 붙인다(네이버 · 쿠팡은 등록한 IP 에서만 받는다).
"""
from __future__ import annotations

import gzip
import json
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode

from shared import env

# 오류 문장에서 가릴 키 — 값이 응답 본문·요청 경로에 섞여 나올 수 있는 것(쿠팡 403 본문에 업체코드가 든 경로가 찍힘 · 실측 2026-10-14)
SECRET_KEYS = ("COUPANG_VENDOR_ID", "COUPANG_ACCESS_KEY", "COUPANG_SECRET_KEY",
               "NAVER_COMMERCE_CLIENT_ID", "NAVER_COMMERCE_CLIENT_SECRET",
               "CAFE24_CLIENT_ID", "CAFE24_CLIENT_SECRET")
MASK = "***"
IP_HELP = ("호출 IP 가 허용 목록에 없습니다 — 그 채널 API 화면(네이버 커머스API센터 · 쿠팡 윙 OPEN API)에 "
           "지금 인터넷의 IP 를 등록하세요. 내 IP 확인: 터미널에서 curl -s https://api.ipify.org · "
           "집·카페 와이파이가 바뀌면 IP 도 바뀝니다(README '키 발급').")
_IP_WORD = re.compile(r"\bip\b", re.I)


def scrub(text: str) -> str:
    """오류 문장에서 .env 키 값(SECRET_KEYS)을 *** 로. 4자 미만 값은 다른 글자를 망가뜨리지 않게 건너뛴다."""
    for name in SECRET_KEYS:
        value = env.get(name)
        if value and len(value) >= 4:
            text = text.replace(value, MASK)
    return text


def ip_blocked(status: int | None, body: str) -> bool:
    """403 이고 본문이 IP 를 말하면(쿠팡: "Your ip address … is not allowed") 호출 IP 거부로 본다."""
    return status == 403 and bool(_IP_WORD.search(body or ""))


class ChannelError(RuntimeError):
    """채널 API 실패. status = HTTP 상태코드(연결 실패면 None) · body = 응답 본문 앞부분."""

    def __init__(self, message: str, status: int | None = None, body: str = ""):
        super().__init__(scrub(message))
        self.status = status
        self.body = scrub(body)


RETRY_429 = 3   # 429(요청이 많음)면 쉬었다 다시 — 세 번까지(1·2·4초 · Retry-After 가 있으면 그 값, 최대 10초)


def _text(resp) -> str:
    """응답 본문 → 글자. Accept-Encoding 을 안 보내도 gzip 으로 주는 채널이 있다(쿠팡 403 실측 2026-10-14)."""
    raw = resp.read()
    if ((resp.headers or {}).get("Content-Encoding") or "").lower() == "gzip" or raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
    return raw.decode("utf-8", errors="replace")


def _wait_429(e, attempt: int) -> float:
    try:
        return max(0.0, min(float((e.headers or {}).get("Retry-After")), 10.0))
    except (TypeError, ValueError):
        return float(2 ** attempt)


def http_json(method: str, url: str, headers: dict | None = None, body=None,
              form: dict | None = None, timeout: int = 30) -> dict:
    """JSON 요청·응답. 2xx 가 아니면 ChannelError(상태코드 + 본문 요약). 429 는 쉬었다 다시."""
    headers = dict(headers or {})
    data = None
    if form is not None:
        data = urlencode(form).encode("utf-8")
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    attempt = 0
    while True:
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = _text(resp)
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < RETRY_429:
                wait = _wait_429(e, attempt)
                e.close()
                time.sleep(wait)
                attempt += 1
                continue
            detail = _text(e)[:300]
            hint = f" → {IP_HELP}" if ip_blocked(e.code, detail) else ""
            raise ChannelError(f"HTTP {e.code} — {detail}{hint}", status=e.code, body=detail) from None
        except urllib.error.URLError as e:
            raise ChannelError(f"연결 실패 — {e.reason}") from None
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        raise ChannelError(f"JSON 아닌 응답 — {raw[:200]}", body=raw[:300]) from None
