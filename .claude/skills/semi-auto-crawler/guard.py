# 생성물 — 하네스 40_commerce_harness/shared/crawl/policy.py 정본 · sync_skillpack.py · 2026-10-18
"""크롤 정책 판정 — (사이트 × 행동) → allow / confirm / deny + 운영 규율(pace) + 무인 가능 여부(unattended).

정책 SSOT = 같은 폴더 `policy.json`(층1 · 사이트 무관) + 오버레이 `altafit_specific/crawl_policy_overlay.json`
(층2 · 회사 전용 사이트 — 있으면). 이 모듈은 읽고 판정만 한다(정책을 코드에 박지 않는다).
불변식은 `70_infra/verify_integrity.check_browser_policy`가 병합본에 대해 pre-commit에서 강제한다.

두 드라이버가 이 한 벌을 읽는다(#585):
  · 동석(사람 크롬 MCP)  — CLI `python -m browser.guard check|pace <URL>`(50 shim) → `main()`
  · 무인(zion 진짜 크롬) — `browser.Navigator.goto` → `require()`·`pace()`·`unattended()`

    from ..shared.crawl import policy                # 40 안 = 상대 import / 50 = harness_sdk.crawl("policy")
    policy.classify(url, "fill").decision            # "allow" | "confirm" | "deny"
    policy.require(url, "navigate")                  # allow 가 아니면(미등록 호스트 포함) PolicyDenied
    policy.unattended(url)                           # "ok" | "anonymous_blocked" | "manual_only"

★ stdlib 만 쓴다 — 공개 스킬팩에 이 파일이 `guard.py` 로 그대로 복사된다(`70_infra/sync_skillpack.py`).
  오버레이가 없는 곳(스킬팩·분사본)에서는 층1 정책만으로 같은 판정을 한다.

REUSE-CHECK:
  · `50_code/tools/browser/guard.py` — 판정 본체(`_host`·`_rest`·`_host_hit`·`pre_deny`·`match_site`·
    `classify`·`summary`·`pace`·`main`)를 **AST 그대로** 이 파일로 옮겼다(새로 짜지 않았다). 저쪽은 이제
    CLI shim 이다. 그 불변식 lint `70_infra/verify_integrity.py` `check_browser_policy` 는 병합본을 읽도록 고쳐
    재사용했다 — docstring 인용: "불변식 3종(+ⓒ 운영 규율 칸 스키마):"
  · 무인 차단·로그인벽 호스트 목록(구 50 `reference/settings.py` `WEBPAGE_BLOCKED_HOSTS`·`WEBPAGE_MANUAL_ONLY_HOSTS`
    · HEAD 60eadf79 값 그대로)을 `unattended.mode` 칸으로 올렸다 — 50 도구 상수라 40 무인 드라이버·동석 레일이
    못 읽었다. 화면 판정은 다시 짜지 않고 `40_commerce_harness/shared/crawl/diag.py` `classify_cause` 의 사전을
    공유한다(`signals.json` · `wall_signal`) — docstring 인용: "(예외, URL, 화면 텍스트, 모달 감지) → 원인 코드."
WHY: 동석·무인 크롤이 같은 정책·같은 판정을 쓰게 판정기를 공용 층(40 shared/crawl)에 한 벌로 둔다.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote, urlsplit

POLICY_PATH = Path(__file__).with_name("policy.json")
# 층2 오버레이(회사 전용 사이트) — <SDK>/altafit_specific/. 없으면(스킬팩·분사본) 층1 만으로 판정한다.
OVERLAY_PATH = Path(__file__).resolve().parent.parent.parent / "altafit_specific" / "crawl_policy_overlay.json"
ACTIONS = ("read", "navigate", "fill", "secret", "irreversible")
UNATTENDED_MODES = ("ok", "anonymous_blocked", "manual_only")


class PolicyError(ValueError):
    """정책 파일 자체가 잘못됐다(오버레이 키 위반·사이트 id 중복) — 판정 전에 멈춘다."""


class PolicyDenied(RuntimeError):
    """무인 이동·행동이 정책에 막혔다(미등록 호스트·deny·confirm·무인 금지·탭 상한) — **사람이 볼 사안**.

    `browser.SessionExpired` 와 같은 **분류 예외** 관례: caller 는 `except PolicyDenied:` 로 잡아 중단+경보한다.
    재시도로 풀리는 실패가 아니다(정책을 바꾸거나 사람이 동석해야 한다)."""

    def __init__(self, url: str, reason: str, verdict: "Verdict | None" = None):
        super().__init__(f"정책 거부 — {reason} ({url})")
        self.url, self.reason, self.verdict = url, reason, verdict


@dataclass(frozen=True)
class Verdict:
    decision: str            # allow | confirm | deny
    site: str                # 매칭된 사이트 id (없으면 "default")
    action: str
    why: str

    @property
    def mark(self) -> str:
        return {"allow": "🟢", "confirm": "🟡", "deny": "🔴"}[self.decision]

    def line(self) -> str:
        return f"{self.mark} {self.decision.upper():7} [{self.site}] {self.action} — {self.why}"


def merge(base: dict, overlay: dict | None) -> dict:
    """층1 정책 + 오버레이 → 병합본. **순수함수**.

    · 오버레이는 `sites`(와 `_` 주석 키)만 — default·pre_deny 같은 전역 칸을 회사 층이 느슨하게 못 바꾼다.
    · 오버레이 sites 는 층1 sites **뒤에** 붙는다 — 첫 매칭 우선이라 층1 안전 규칙(money·주문확정 차단)이 먼저 걸린다.
    · 사이트 id 중복(층1↔오버레이·각자 안)은 `PolicyError` — 같은 id 두 벌이면 어느 쪽이 이기는지 숨는다."""
    sites = list(base.get("sites", []))
    if overlay:
        extra = sorted(k for k in overlay if k != "sites" and not k.startswith("_"))
        if extra:
            raise PolicyError(f"오버레이에는 sites 만 둘 수 있다 — 허용 밖 키 {extra}")
        sites += list(overlay.get("sites", []))
    ids = [s.get("id") for s in sites]
    dup = sorted({i for i in ids if ids.count(i) > 1}, key=str)
    if dup:
        raise PolicyError(f"사이트 id 중복 {dup} — 층1·오버레이를 합쳐 id 는 하나씩만")
    return {**base, "sites": sites}


@lru_cache(maxsize=1)
def load() -> dict:
    """병합 정책(층1 + 오버레이) — 판정이 읽는 유일한 accessor. 파일 직독 금지."""
    base = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    overlay = json.loads(OVERLAY_PATH.read_text(encoding="utf-8")) if OVERLAY_PATH.is_file() else None
    return merge(base, overlay)


# 브라우저(WHATWG)와 파이썬(urlsplit)의 해석이 갈리는 문자 — 있으면 판정을 포기한다.
# 예: `https://evil.io\\@dash.cloudflare.com/x` 를 urlsplit은 host=dash.cloudflare.com 으로 읽지만
# 브라우저는 `\\`를 `/`로 정규화해 evil.io 로 간다. 가드가 A를 허용하는 사이 브라우저는 B로 가는
# **파서 차분 우회**다. 지금은 이미 정규화된 page.url 만 넘어와 무해하지만, PreToolUse 훅이
# navigate 인자를 직접 판정하는 순간 훅이 막으려던 바로 그 지점이 뚫린다 → 선제 차단.
_HOST_SUSPECT = ("\\", "@", "\t", "\n", "\r", "\x00", " ")


ALLOWED_SCHEMES = ("http", "https")   # 그 외(javascript:·file:·data:·chrome:)는 판정 없이 거부


def _host(url: str) -> str:
    """호스트명. 스킴이 http(s)가 아니거나 브라우저와 해석이 갈릴 URL이면 빈 문자열.

    ★ 빈 문자열은 "미등록 사이트(default)"가 아니라 **판정 불가 = 거부**로 이어진다(classify).
      default 는 "호스트는 정상적으로 잡혔으나 정책에 없는 사이트"에만 쓴다."""
    sch = (urlsplit(url or "").scheme or "").lower()
    if sch not in ALLOWED_SCHEMES:
        return ""                       # javascript:·file:·data:·스킴 없음 → classify 가 deny
    raw = url or ""
    scheme, sep, rest = raw.partition("://")
    authority = (rest if sep else raw).split("/")[0].split("?")[0].split("#")[0]
    if any(c in authority for c in _HOST_SUSPECT):
        return ""                       # userinfo·역슬래시·제어문자 → fail-closed
    h = (urlsplit(raw).hostname or "").lower()
    return "" if any(c in h for c in _HOST_SUSPECT) else h


def _rest(url: str) -> str:
    """path + query + fragment — 호스트를 뺀 나머지. **percent-decode 후** 비교한다.

    안 하면 `/accounts/log%6fut`·`/accounts%2flogout` 한 번으로 경로 규칙이 뚫린다(2026-08-26 검수)."""
    p = urlsplit(url)
    out = p.path or ""
    if p.query:
        out += "?" + p.query
    if p.fragment:
        out += "#" + p.fragment
    for _ in range(3):                  # 다중 인코딩(%2525…)까지 풀어서 비교
        dec = unquote(out)
        if dec == out:
            break
        out = dec
    return out.lower()


def _host_hit(host: str, domain: str) -> bool:
    """도메인 suffix 매칭 — 정확히 같거나 `.`으로 끝날 때만.

    부분일치를 쓰지 않는 이유: `evil.example/dash.cloudflare.com`(경로 삽입)이나
    `echosting.cafe24.com.evil.io`(서브도메인 위장)가 상위 등급을 훔칠 수 있다."""
    d = domain.lower().lstrip(".")
    return host == d or host.endswith("." + d)


def pre_deny(url: str) -> Verdict | None:
    """사이트 매칭 **이전에** 걸리는 전역 차단(로그아웃 등).

    사이트 규칙 뒤에 두면 앞선 규칙에 걸리는 도메인에서 무력화된다(v2 실사고)."""
    pre = load().get("pre_deny")
    if not pre:
        return None
    rest = _rest(url)
    for frag in pre.get("url_contains", []):
        if frag.lower() in rest:
            return Verdict("deny", "pre_deny", "*", pre["why"])
    return None


def match_site(url: str) -> dict | None:
    """URL에 맞는 첫 사이트 항목. host(도메인 suffix) AND url_contains(경로 부분일치).

    **정의 순서가 우선순위** — 좁은 규칙(경로 지정)을 넓은 규칙보다 위에 둔다."""
    host, rest = _host(url), _rest(url)
    if not host:
        return None
    for site in load()["sites"]:
        if not any(_host_hit(host, d) for d in site.get("host", [])):
            continue
        needles = site.get("url_contains")
        if needles and not any(n.lower() in rest for n in needles):
            continue
        return site
    return None


def classify(url: str, action: str) -> Verdict:
    """이 URL에서 이 행동을 해도 되나. deny → confirm → allow 순(거부 우선)."""
    if action not in ACTIONS:
        raise ValueError(f"알 수 없는 행동: {action} (가능: {', '.join(ACTIONS)})")
    blocked = pre_deny(url)
    if blocked is not None:
        return Verdict("deny", blocked.site, action, blocked.why)
    if not _host(url):                  # 스킴 위반·파서 차분·URL 아님 → 판정 포기 = 거부
        return Verdict("deny", "unparsable", action,
                       "http(s) URL로 호스트를 확정할 수 없다(스킴 위반·userinfo·역슬래시·빈 값). "
                       "판정할 수 없는 것은 허용하지 않는다.")
    site = match_site(url)
    rule, sid = (site, site["id"]) if site else (load()["default"], "default")
    for decision in ("deny", "confirm", "allow"):
        if action in rule.get(decision, []):
            return Verdict(decision, sid, action, rule["why"])
    return Verdict("deny", sid, action, rule["why"] + " (명시되지 않은 행동 — 기본 거부)")


def summary(url: str) -> list[Verdict]:
    """한 URL에 대한 전 행동 판정 — 탭 목록에 붙여 보여주기 좋다."""
    return [classify(url, a) for a in ACTIONS]


@dataclass(frozen=True)
class Pace:
    """사이트별 운영 규율 — 판정(allow/confirm/deny)과 별개로 '얼마나 조심스럽게 두드리나'."""
    site: str
    max_tabs: int             # 같은 도메인 동시 탭 수 상한
    min_interval_sec: int     # 같은 도메인 페이지 이동 사이 최소 간격
    captcha_frequent: bool    # 캡차가 잦은 사이트인가
    captcha_handling: str     # 감지 시 처리 — stop_and_handoff (우회 금지)
    nav: str                  # direct | click_from_link_page

    def line(self) -> str:
        cap = "잦음" if self.captcha_frequent else "드묾"
        return (f"⏱ [{self.site}] 탭 ≤{self.max_tabs} · 간격 ≥{self.min_interval_sec}s · "
                f"캡차 {cap}→{self.captcha_handling} · 이동 {self.nav}")


def pace(url: str) -> Pace:
    """이 URL의 운영 규율. 사이트 항목에 없는 칸은 `default` 값을 쓴다(칸 단위 상속).

    해석 불가 URL 은 default 값을 돌려준다 — 어차피 classify 가 deny 라 이동 자체를 안 한다."""
    pol = load()
    base = pol["default"]
    site = match_site(url) if _host(url) else None
    rule = site or {}
    cap = {**base.get("captcha", {}), **rule.get("captcha", {})}
    return Pace(
        site=site["id"] if site else "default",
        max_tabs=int(rule.get("max_tabs", base["max_tabs"])),
        min_interval_sec=int(rule.get("min_interval_sec", base["min_interval_sec"])),
        captcha_frequent=bool(cap.get("frequent", False)),
        captcha_handling=cap.get("handling", "stop_and_handoff"),
        nav=rule.get("nav", base.get("nav", "direct")),
    )


def unattended(url: str) -> str:
    """무인(사람 없는) 크롤 가능 여부 — `ok` | `anonymous_blocked` | `manual_only`.

    · `anonymous_blocked` = 익명 헤드리스(`browser.open_anonymous`)는 금지, 로그인 프로필(`open_profile`)·사람 크롬은 가능
    · `manual_only`       = 무인 금지 — 사람 동석으로만
    칸 = 사이트 항목의 `unattended.mode`(없으면 default 의 칸 → 그것도 없으면 ok · pace 와 같은 칸 단위 상속).
    해석 불가 URL 은 `manual_only`(판정할 수 없는 것은 무인으로 열지 않는다)."""
    if not _host(url):
        return "manual_only"
    site = match_site(url) or {}
    cell = site.get("unattended") or load()["default"].get("unattended") or {}
    mode = cell.get("mode", "ok")
    if mode not in UNATTENDED_MODES:          # lint 가 막지만 런타임도 fail-closed
        return "manual_only"
    return mode


def require(url: str, action: str) -> Verdict:
    """무인 실행용 단언 — `allow` 가 아니면 `PolicyDenied`. 통과하면 그 Verdict 를 돌려준다.

    · 미등록 호스트는 default 사이트 규칙으로 판정한다(read·navigate allow · fill·irreversible confirm → 거부 · secret deny).
      임의 URL 은 런타임 default · 어댑터 리터럴 호스트의 등록 강제는 lint(`check_crawl_host_registered` · 5단계) 몫.
    · `confirm` 도 거부한다 — 무인에는 확정해 줄 사람이 없다(사람 확정은 동석 레일 몫)."""
    v = classify(url, action)
    if v.decision != "allow":
        raise PolicyDenied(url, f"[{v.site}] {action} = {v.decision} — {v.why}", v)
    return v


def main(argv: list[str]) -> int:
    """`check <URL>` · `pace <URL>` — 붙지 않고 정책만 읽으므로 언제나 동작한다."""
    if len(argv) == 2 and argv[0] == "check":
        print(f"URL: {argv[1]}\n")
        for v in summary(argv[1]):
            print("  " + v.line())
        print("\n  " + pace(argv[1]).line())
        return 0
    if len(argv) == 2 and argv[0] == "pace":
        print(pace(argv[1]).line())
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
