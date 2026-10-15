"""카페24 Admin API — OAuth 2.0(인증 코드 → 접근 토큰 2시간 · 리프레시 토큰 2주).

문서: Admin API 'Authentication'
    1) 브라우저: GET https://{mallid}.cafe24api.com/api/v2/oauth/authorize?response_type=code&client_id&state&redirect_uri&scope
       → {redirect_uri}?code=…&state=… 로 돌아온다(code 는 1분 안에 한 번만 쓸 수 있음)
    2) POST /api/v2/oauth/token  (Basic base64(client_id:client_secret))
       grant_type=authorization_code&code&redirect_uri  /  grant_type=refresh_token&refresh_token
    리프레시하면 리프레시 토큰도 새로 바뀐다 → 토큰 파일(레포 루트 cafe24.token.json · git 제외)에 다시 저장.

처음 한 번 · SCOPES 를 바꾼 뒤 한 번 더(사장님이 "카페24 로그인" 하면 클로드가 실행한다):
    python3 shared/channels/cafe24.py login
    → 브라우저에 동의 화면이 열리고, 넘어간 주소를 맥 입력 창(shared/dialog.py)에 붙여넣는다.

    from shared.channels import cafe24
    cafe24.request("GET", "/boards")        # path 는 /api/v2/admin 뒤부터
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

if __name__ == "__main__":   # 파일로 직접 실행(login) — 어느 폴더에서든 shared 를 찾게(루트 CLAUDE.md §5 표준 머리)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared import dialog, env  # noqa: E402
from shared.channels import ChannelError, http_json  # noqa: E402
from shared.paths import repo_root  # noqa: E402

KEYS = ["CAFE24_MALL_ID", "CAFE24_CLIENT_ID", "CAFE24_CLIENT_SECRET"]
# 로그인할 때 받을 권한. 스킬이 새 권한이 필요하면 여기에 더하고 login 을 한 번 다시 한다.
SCOPES = ["mall.read_community",   # ③ 문의 모으기(게시판 읽기)
          "mall.read_product"]     # ④ 매대 점검(상품·품목 읽기)
KST = timezone(timedelta(hours=9))
LOGIN_HELP = "카페24 로그인이 필요합니다 — 클로드에게 '카페24 로그인' 이라고 말하세요(= `python3 shared/channels/cafe24.py login`)"


def configured() -> bool:
    return all(env.get(k) for k in KEYS)


def token_path():
    return repo_root() / "cafe24.token.json"


def _host() -> str:
    return f"https://{env.get('CAFE24_MALL_ID', required=True)}.cafe24api.com"


def _load() -> dict:
    p = token_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def _save(data: dict) -> None:
    p = token_path()
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def _token_call(form: dict) -> dict:
    basic = base64.b64encode(
        f"{env.get('CAFE24_CLIENT_ID', required=True)}:{env.get('CAFE24_CLIENT_SECRET', required=True)}"
        .encode("utf-8")).decode("ascii")
    data = http_json("POST", f"{_host()}/api/v2/oauth/token", {"Authorization": f"Basic {basic}"}, form=form)
    if not data.get("access_token"):
        raise ChannelError("토큰 응답에 access_token 이 없습니다")
    _save(data)
    return data


def _expired(tok: dict, margin_min: int = 5) -> bool:
    raw = str(tok.get("expires_at") or "")
    try:
        # 미확인 — 실측 필요: 문서 예시 expires_at 에 시간대 표기가 없다 → 카페24 규칙(+09:00)대로 한국시간으로 읽는다
        at = datetime.fromisoformat(raw[:19]).replace(tzinfo=KST)
    except ValueError:
        return True
    return datetime.now(KST) >= at - timedelta(minutes=margin_min)


def refresh() -> dict:
    tok = _load()
    if not tok.get("refresh_token"):
        raise ChannelError(LOGIN_HELP)
    try:
        return _token_call({"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})
    except ChannelError as e:
        if e.status in (400, 401):
            raise ChannelError(f"리프레시 토큰이 만료됐습니다(2주). {LOGIN_HELP}", e.status, e.body) from None
        raise


def access_token() -> str:
    tok = _load()
    if not tok.get("access_token"):
        raise ChannelError(LOGIN_HELP)
    if _expired(tok):
        tok = refresh()
    return tok["access_token"]


def request(method: str, path: str, params: dict | None = None, body=None) -> dict:
    """카페24 Admin API 호출(조회). 401 이면 토큰을 한 번 새로 받아 다시 시도한다."""
    url = f"{_host()}/api/v2/admin{path}" + (f"?{urlencode(params)}" if params else "")
    for attempt in (1, 2):
        headers = {"Authorization": f"Bearer {access_token()}", "Content-Type": "application/json"}
        try:
            return http_json(method.upper(), url, headers, body=body)
        except ChannelError as e:
            if e.status == 401 and attempt == 1:
                refresh()          # 만료 직전 경계 — 한 번만 새로 받아 다시
                continue
            raise
    return {}


def authorize_url(state: str) -> str:
    q = urlencode({"response_type": "code", "client_id": env.get("CAFE24_CLIENT_ID", required=True),
                   "state": state, "redirect_uri": env.get("CAFE24_REDIRECT_URI", required=True),
                   "scope": ",".join(SCOPES)})
    return f"{_host()}/api/v2/oauth/authorize?{q}"


def login(ui=dialog) -> int:
    """동의 화면을 브라우저로 열고, 돌아온 주소를 맥 입력 창으로 받아 토큰을 저장한다(ui 는 테스트용 주입 자리)."""
    state = secrets.token_urlsafe(12)
    url = authorize_url(state)
    # 주소에 Client ID 가 들어 있어 화면(대화 기록)에 찍지 않는다 — 클립보드와 기본 브라우저로만 넘긴다.
    subprocess.run(["pbcopy"], input=url, text=True, check=False)
    subprocess.run(["open", url], check=False)
    print("브라우저에 카페24 로그인 창을 열었어요(주소는 클립보드에도 있어요).")
    pasted = ui.ask("1) 열린 화면에서 쇼핑몰 관리자로 로그인해 '동의'를 누르세요.\n"
                    "2) 넘어간 페이지 주소창의 주소 전체를 복사해 여기에 붙여넣고 확인(1분 안에).")
    if pasted is None:
        print("취소했습니다. 다시 하려면 클로드에게 '카페24 로그인'.")
        return 1
    pasted = pasted.strip()
    qs = parse_qs(urlparse(pasted).query)
    code = (qs.get("code") or [""])[0]
    if not code:
        print("주소에서 code 를 못 찾았습니다. 처음부터 다시 해 주세요.")
        return 1
    if (qs.get("state") or [""])[0] != state:
        print("state 값이 다릅니다(다른 창의 주소?). 처음부터 다시 해 주세요.")
        return 1
    try:
        _token_call({"grant_type": "authorization_code", "code": code,
                     "redirect_uri": env.get("CAFE24_REDIRECT_URI", required=True)})
    except ChannelError as e:
        print(f"토큰 발급 실패 — {e}")
        return 1
    print(f"완료 — {token_path().name} 에 저장했습니다(2주 동안 자동 연장 · git 에 올라가지 않음).")
    return 0


# --- products (shelf-check) ---
# 매대 점검(④)이 쓴다. 조회(GET)만 · 권한 mall.read_product(위 SCOPES).
def products() -> list:
    """[(상품, [품목…]), …].  미확인 — 실측 필요: 품목 목록 조회는 문서 요청사양에 limit/offset 이 없어 한 번에 다 온다고 본다.
    문서 02_Product 'Retrieve a list of products': GET /products (limit 최대 100 · offset 최대 5000)
    문서 02_Product 'Retrieve a list of product variants': GET /products/{product_no}/variants"""
    import time  # 문서 '요청 수 제한': Bucket 은 1초에 2회씩 빠진다 → 0.5초 간격이면 상품이 많아도 429 없음
    pairs, offset = [], 0
    while True:
        # 미확인 — 실측 필요: 응답 최상위 키 'products'·'variants' — 문서 응답 예시가 비어 있어 카페24 공통 규칙으로 맞춤
        items = request("GET", "/products", params={"limit": 100, "offset": offset}).get("products") or []
        for p in items:
            time.sleep(0.5)
            pairs.append((p, request("GET", f"/products/{p['product_no']}/variants").get("variants") or []))
        if len(items) < 100 or offset + 100 > 5000:
            return pairs
        offset += 100


# (실행 진입점은 맨 끝에 둔다 — 위 구역 함수가 다 정의된 뒤)
if __name__ == "__main__":
    if sys.argv[1:] == ["login"]:
        sys.exit(login())
    print("사용법: python3 shared/channels/cafe24.py login")
    sys.exit(2)
