"""반자동크롤러 정책 판정 — (사이트 × 행동) → allow / confirm / deny.

정책 = 같은 폴더 `policy.json`. 이 모듈은 읽고 판정만 한다(정책을 코드에 박지 않는다).
표준 라이브러리만 쓴다 — 맥 기본 `python3` 로 바로 돈다.

    python3 .claude/skills/semi-auto-crawler/guard.py check <URL>   # 행동 5종 판정 한 화면

`policy.json` 을 읽을 때 불변식(시크릿은 언제나 사람 · 비가역은 허용 불가 · why 필수 ·
host 는 실제 도메인)을 검사한다. 사장님이 정책을 고치다 어긋나면 판정 대신 오류로 멈춘다.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote, urlsplit

POLICY_PATH = Path(__file__).with_name("policy.json")
ACTIONS = ("read", "navigate", "fill", "secret", "irreversible")


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


class PolicyError(ValueError):
    """policy.json 이 불변식을 어겼다 — 판정하지 않는다."""


def validate(policy: dict) -> list[str]:
    """불변식 위반 목록(빈 목록 = 정상). invariants 에 적힌 글을 코드로 강제한다."""
    errs: list[str] = []
    rules = [(s.get("id", "?"), s, True) for s in policy.get("sites", [])]
    rules.append(("default", policy.get("default", {}), False))
    for sid, rule, is_site in rules:
        for key in ("allow", "confirm", "deny"):
            bad = [a for a in rule.get(key, []) if a not in ACTIONS]
            if bad:
                errs.append(f"[{sid}] {key} 에 모르는 행동: {bad}")
        if "secret" in rule.get("allow", []):
            errs.append(f"[{sid}] secret 은 allow 에 올 수 없다(사람이 직접 입력)")
        if "irreversible" in rule.get("allow", []):
            errs.append(f"[{sid}] irreversible 은 allow 에 올 수 없다(confirm 또는 deny)")
        if not str(rule.get("why", "")).strip():
            errs.append(f"[{sid}] why 가 비었다")
        if is_site:
            hosts = rule.get("host") or []
            if not hosts:
                errs.append(f"[{sid}] host 가 비었다")
            for h in hosts:
                if "." not in str(h).strip(".") or any(c in str(h) for c in "*/ "):
                    errs.append(f"[{sid}] host '{h}' 는 실제 도메인이 아니다")
    return errs


@lru_cache(maxsize=1)
def load() -> dict:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    errs = validate(policy)
    if errs:
        raise PolicyError("policy.json 규칙 위반 — 고친 뒤 다시:\n  " + "\n  ".join(errs))
    return policy


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


def main(argv: list[str]) -> int:
    """`check <URL>` 하나만 받는다 — 붙지 않고 정책만 읽으므로 언제나 동작한다."""
    if len(argv) == 2 and argv[0] == "check":
        try:
            verdicts = summary(argv[1])
        except PolicyError as e:
            print(e, file=sys.stderr)
            return 1
        print(f"URL: {argv[1]}\n")
        for v in verdicts:
            print("  " + v.line())
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
