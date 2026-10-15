"""쿠팡 윙 OPEN API — 요청마다 HMAC-SHA256 서명(토큰 없음).

문서: 'Creating HMAC Signature'
    Authorization: CEA algorithm=HmacSHA256, access-key=…, signed-date=yyMMdd'T'HHmmss'Z'(UTC), signature=…
    서명할 문자열 = signed-date + METHOD + path + query(? 없이) — query 는 실제 URL 과 같은 문자열.
    초당 5회 제한.

    from shared.channels import coupang
    coupang.request("GET", f"/v2/providers/openapi/apis/api/v5/vendors/{coupang.vendor_id()}/onlineInquiries", params={...})
"""
from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

from shared import env
from shared.channels import ChannelError, http_json

BASE = "https://api-gateway.coupang.com"
KEYS = ["COUPANG_ACCESS_KEY", "COUPANG_SECRET_KEY", "COUPANG_VENDOR_ID"]
MIN_GAP = 0.25          # 초당 5회 제한
_last = [0.0]


def configured() -> bool:
    return all(env.get(k) for k in KEYS)


def vendor_id() -> str:
    return env.get("COUPANG_VENDOR_ID", required=True)


def authorization(method: str, path: str, query: str, now: datetime | None = None) -> str:
    dt = (now or datetime.now(timezone.utc)).strftime("%y%m%dT%H%M%SZ")
    secret = env.get("COUPANG_SECRET_KEY", required=True)
    sig = hmac.new(secret.encode("utf-8"), (dt + method + path + query).encode("utf-8"),
                   hashlib.sha256).hexdigest()
    access = env.get("COUPANG_ACCESS_KEY", required=True)
    return f"CEA algorithm=HmacSHA256, access-key={access}, signed-date={dt}, signature={sig}"


def request(method: str, path: str, params: dict | None = None, body=None) -> dict:
    """응답 JSON 을 그대로 돌려준다. 본문의 code 판정은 부르는 쪽이 API 별로 한다."""
    method = method.upper()
    query = urlencode(params) if params else ""        # 서명과 URL 에 같은 문자열
    url = f"{BASE}{path}" + (f"?{query}" if query else "")
    wait = MIN_GAP - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    headers = {"Authorization": authorization(method, path, query),
               "X-Requested-By": vendor_id(),
               "Content-Type": "application/json;charset=UTF-8"}
    return http_json(method, url, headers, body=body)


# --- products (shelf-check) ---
# 매대 점검(④)이 쓴다. 조회(GET)만.
SELLER_API = "/v2/providers/seller_api/apis/api/v1/marketplace"


def _ok(res: dict) -> dict:
    # 상품 API 문서: code = SUCCESS/ERROR (문의 API 와 값이 다르다)
    if str(res.get("code", "SUCCESS")) != "SUCCESS":
        raise ChannelError(f"쿠팡 응답 code={res.get('code')} — {res.get('message', '')}")
    return res


def products() -> list:
    """[(상품 조회 data, {vendorItemId: 아이템별 수량/가격/상태 data}), …]. 상품삭제는 뺀다.
    문서 '상품 목록 페이징 조회': GET {SELLER_API}/seller-products (vendorId · maxPerPage 최대 100 · nextToken)
    문서 '상품 조회':             GET {SELLER_API}/seller-products/{sellerProductId}
    문서 '상품 아이템별 수량/가격/상태 조회': GET {SELLER_API}/vendor-items/{vendorItemId}/inventories"""
    pairs, nxt = [], ""
    while True:
        params = {"vendorId": vendor_id(), "maxPerPage": 100}
        if nxt:
            params["nextToken"] = nxt
        res = _ok(request("GET", f"{SELLER_API}/seller-products", params=params))
        for p in res.get("data") or []:
            if p.get("statusName") == "상품삭제":
                continue
            detail = _ok(request("GET", f"{SELLER_API}/seller-products/{p['sellerProductId']}")).get("data") or {}
            inv = {}
            for it in detail.get("items") or []:
                vid = it.get("vendorItemId")      # 임시저장이면 null(문서)
                if vid:
                    inv[vid] = _ok(request("GET", f"{SELLER_API}/vendor-items/{vid}/inventories")).get("data") or {}
            pairs.append((detail, inv))
        nxt = str(res.get("nextToken") or "")
        if not nxt:
            return pairs
