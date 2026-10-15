"""네이버 커머스 API — 전자서명(bcrypt) → OAuth 토큰(3시간) → Bearer 요청.

문서: 커머스API센터 '인증 토큰 발급 요청' (POST /v1/oauth2/token)
    client_secret_sign = base64( bcrypt( f"{client_id}_{timestamp}", client_secret ) )
    timestamp = 밀리초 Unix 시간(5분간 유효) · type = SELF(내 스토어)

    from shared.channels import naver
    naver.request("GET", "/v1/contents/qnas", params={...})   # path 는 /external 뒤부터
"""
from __future__ import annotations

import base64
import time
from urllib.parse import urlencode

from shared import env
from shared.channels import ChannelError, http_json

BASE = "https://api.commerce.naver.com/external"
KEYS = ["NAVER_COMMERCE_CLIENT_ID", "NAVER_COMMERCE_CLIENT_SECRET"]

_token: dict = {}   # 한 번 실행하는 동안만 메모리에 둔다(유효 3시간 · 파일 저장 안 함)


def configured() -> bool:
    return all(env.get(k) for k in KEYS)


def _sign(client_id: str, client_secret: str, ts: str) -> str:
    try:
        import bcrypt
    except ImportError:
        raise ChannelError("bcrypt 가 없습니다 — 터미널에서 `python3 -m pip install bcrypt` 한 번 실행") from None
    try:
        hashed = bcrypt.hashpw(f"{client_id}_{ts}".encode("utf-8"), client_secret.encode("utf-8"))
    except ValueError:
        raise ChannelError("NAVER_COMMERCE_CLIENT_SECRET 형식이 이상합니다 — 커머스API센터에서 다시 복사") from None
    return base64.b64encode(hashed).decode("utf-8")


def token() -> str:
    if _token.get("value") and time.time() < _token.get("until", 0):
        return _token["value"]
    cid = env.get("NAVER_COMMERCE_CLIENT_ID", required=True)
    secret = env.get("NAVER_COMMERCE_CLIENT_SECRET", required=True)
    ts = str(int(time.time() * 1000))
    data = http_json("POST", f"{BASE}/v1/oauth2/token", {"Accept": "application/json"},
                     form={"client_id": cid, "timestamp": ts, "grant_type": "client_credentials",
                           "client_secret_sign": _sign(cid, secret, ts), "type": "SELF"})
    if not data.get("access_token"):
        raise ChannelError("토큰 발급 응답에 access_token 이 없습니다")
    _token["value"] = data["access_token"]
    _token["until"] = time.time() + int(data.get("expires_in") or 10800) - 300
    return _token["value"]


def request(method: str, path: str, params: dict | None = None, body=None) -> dict:
    url = f"{BASE}{path}" + (f"?{urlencode(params)}" if params else "")
    headers = {"Authorization": f"Bearer {token()}", "Accept": "application/json"}
    return http_json(method, url, headers, body=body)


# --- products (shelf-check) ---
# 매대 점검(④)이 쓴다. 조회만 — 상품 목록 조회는 POST 지만 문서상 조회 API 다.
SHELF_STATUSES = ["SALE", "OUTOFSTOCK", "SUSPENSION"]   # 판매종료·금지·대기·삭제는 매대가 아니다


def products() -> list:
    """[(상품 목록 1건, 원상품 조회 응답), …].
    문서 086 상품 목록 조회: POST /v1/products/search (page 1부터 · size 최대 500 · 응답 contents·totalPages)
    문서 070 원상품 조회:    GET  /v2/products/origin-products/{originProductNo}"""
    pairs, page = [], 1
    while True:
        res = request("POST", "/v1/products/search",
                      body={"productStatusTypes": SHELF_STATUSES, "page": page, "size": 100})
        for item in res.get("contents") or []:
            no = item.get("originProductNo")
            pairs.append((item, request("GET", f"/v2/products/origin-products/{no}") if no else {}))
        if page >= int(res.get("totalPages") or 1):
            return pairs
        page += 1
