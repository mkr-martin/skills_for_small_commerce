"""준비 상태 점검 — 스킬 하나(또는 전부)의 선행조건을 ✅ / ❌ / ⚪(선택) 로 보여 준다. 고치는 법은 ❌ 줄 끝에 한 줄.

    python3 shared/doctor.py                 # 전부(= all)
    python3 shared/doctor.py detail-page     # 스킬 하나 (semi-auto-crawler · detail-page · reels-reference · inquiry-inbox · shelf-check)

- 스킬별로 무엇을 보는지는 아래 SKILLS 표 한 곳에만 적는다. 번호 = 각 스킬 사용법.md 「설치법」 단계 번호.
  파이썬 패키지는 그 스킬의 requirements.txt 를 읽는다(두 벌 금지).
- 키는 "있는지만" 본다 — 🛑 값은 어디에도 찍지 않는다(키 이름도 필요한 것만).
- 종료 코드: ❌ 가 하나라도 있으면 1, 없으면 0.
"""
from __future__ import annotations

import importlib.util
import json
import plistlib
import shutil
import sys
from pathlib import Path

if __name__ == "__main__":   # 파일로 직접 실행 — 어느 폴더에서든 shared 를 찾게(루트 CLAUDE.md §5 표준 머리)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared import env, store_profile  # noqa: E402
from shared.paths import output_dir, repo_root  # noqa: E402

OK, BAD, OPT = "✅", "❌", "⚪"
CHROME_MIN = 144
PY_MIN = (3, 9)
CHROME_PLISTS = [Path("/Applications/Google Chrome.app/Contents/Info.plist"),
                 Path.home() / "Applications/Google Chrome.app/Contents/Info.plist"]
# pip 이름 → import 이름(다른 것만)
IMPORT_NAME = {"pillow": "PIL", "google-genai": "google.genai", "yt-dlp": "yt_dlp"}
# 이 pip 패키지는 이 채널 키가 있을 때만 필요하다
ONLY_FOR_CHANNEL = {"bcrypt": "naver"}
CHANNELS = [("naver", "네이버"), ("coupang", "쿠팡"), ("cafe24", "카페24")]
KEYS_FIX = "클로드에게 \"키 넣어줘\"(= python3 shared/setup_keys.py) · 발급 방법은 README '키 발급'"
STOCK_CSV = ("매대", "재고표.csv")          # output/ 아래 — ④ 재고표 자리(fetch_shelf.STOCK_PATH 와 같은 곳)
IP_CHANNELS = ("naver", "coupang")         # 호출 IP 허용 목록이 있는 채널 — 등록 여부는 API 를 불러 봐야 안다

# 스킬별 점검 항목 — 순서 = 사용법.md 「설치법」 단계 번호(1부터). 항목 이름은 아래 CHECKS 의 키.
SKILLS = {
    "semi-auto-crawler": {"no": "⓪", "name": "반자동크롤러", "steps": ["python", "node", "chrome", "mcp"]},
    "detail-page":       {"no": "①", "name": "상세페이지 분석", "steps": ["python", "node", "chrome", "mcp", "packages", "store"]},
    "reels-reference":   {"no": "②", "name": "릴스 레퍼런스", "steps": ["python", "chrome", "packages", "gemini", "store"]},
    "inquiry-inbox":     {"no": "③", "name": "문의 모으기", "steps": ["python", "channels", "packages", "cafe24_login", "store"]},
    "shelf-check":       {"no": "④", "name": "매대 점검", "steps": ["python", "channels_or_csv", "packages", "cafe24_login", "stock_csv", "store"]},
}


class Probe:
    """이 맥의 실제 상태를 읽는 자리 — 테스트는 이 클래스를 가짜로 바꿔 끼운다."""

    def python_version(self) -> tuple:
        return sys.version_info[:3]

    def which(self, name: str) -> bool:
        return shutil.which(name) is not None

    def chrome_version(self) -> str | None:
        for p in CHROME_PLISTS:
            try:
                with p.open("rb") as f:
                    return str(plistlib.load(f).get("CFBundleShortVersionString") or "") or None
            except (OSError, ValueError):
                continue
        return None

    def mcp_ok(self) -> bool:
        try:
            data = json.loads((repo_root() / ".mcp.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return "chrome" in (data.get("mcpServers") or {})

    def importable(self, module: str) -> bool:
        try:
            return importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):      # 'google' 자체가 없을 때 등
            return False

    def has_key(self, name: str) -> bool:
        return bool(env.get(name))

    def channel_configured(self, channel: str) -> bool:
        from shared.channels import cafe24, coupang, naver
        return {"naver": naver, "coupang": coupang, "cafe24": cafe24}[channel].configured()

    def cafe24_token(self) -> bool:
        from shared.channels import cafe24
        return cafe24.token_path().exists()

    def stock_csv(self) -> bool:
        return output_dir(*STOCK_CSV).is_file()

    def store_filled(self) -> bool:
        return store_profile.is_filled()

    def requirements(self, skill: str) -> list[str]:
        p = repo_root() / ".claude" / "skills" / skill / "requirements.txt"
        if not p.exists():
            return []
        out = []
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                for sep in ("==", ">=", "<=", "~=", ">", "<", "["):
                    line = line.split(sep, 1)[0]
                out.append(line.strip().lower())
        return out


# ---------------------------------------------------------------- 항목별 판정 → [(표시, 글, 고치는 법)]
def _python(pr: Probe, skill: str):
    v = pr.python_version()
    text = "파이썬 " + ".".join(map(str, v))
    if tuple(v[:2]) < PY_MIN:
        return [(BAD, text, "python3 3.9 이상 — 터미널에서 python3 --version 이 안 되면 맥이 띄우는 설치 창으로 설치")]
    if skill == "reels-reference" and tuple(v[:2]) < (3, 10):
        return [(OK, text + " (3.10 이상 권장 — 인스타 받기 도구 새 버전용)", "")]
    return [(OK, text, "")]


def _node(pr: Probe, skill: str):
    if pr.which("npx"):
        return [(OK, "Node(npx)", "")]
    return [(BAD, "Node(npx) 없음", "nodejs.org 에서 LTS 설치 → 터미널 새로 열기")]


def _chrome(pr: Probe, skill: str):
    v = pr.chrome_version()
    if not v:
        return [(BAD, "크롬 없음", "google.com/chrome 에서 설치")]
    try:
        major = int(v.split(".")[0])
    except ValueError:
        major = 0
    if major < CHROME_MIN:
        return [(BAD, f"크롬 {v} (144 이상 필요)", "크롬 메뉴 → 도움말 → Chrome 정보에서 업데이트")]
    return [(OK, f"크롬 {v}", "")]


def _mcp(pr: Probe, skill: str):
    if pr.mcp_ok():
        return [(OK, "크롬 연결 설정(.mcp.json)", "")]
    return [(BAD, "크롬 연결 설정(.mcp.json) 없음", "레포를 통째로 다시 받기(숨김 파일 .mcp.json 이 빠짐)")]


def _packages(pr: Probe, skill: str):
    rows = []
    for pkg in pr.requirements(skill):
        ch = ONLY_FOR_CHANNEL.get(pkg)
        if ch and not pr.channel_configured(ch):
            rows.append((OPT, f"패키지 {pkg} — {dict(CHANNELS)[ch]} 키를 넣을 때만 필요", ""))
            continue
        if pr.importable(IMPORT_NAME.get(pkg, pkg)):
            rows.append((OK, f"패키지 {pkg}", ""))
        else:
            rows.append((BAD, f"패키지 {pkg} 없음",
                         f"python3 -m pip install -r .claude/skills/{skill}/requirements.txt"))
    return rows or [(OK, "파이썬 패키지 — 따로 필요 없음", "")]


def _gemini(pr: Probe, skill: str):
    if pr.has_key("GEMINI_API_KEY"):
        return [(OK, "Gemini 키 있음", "")]
    return [(BAD, "Gemini 키 없음", KEYS_FIX)]


def _channel_rows(pr: Probe):
    rows, n = [], 0
    for ch, label in CHANNELS:
        if pr.channel_configured(ch):
            n += 1
            rows.append((OK, f"{label} 키 있음", ""))
        else:
            rows.append((OPT, f"{label} 키 없음(쓰는 채널만 넣으면 됨)", ""))
    ip = [label for ch, label in CHANNELS if ch in IP_CHANNELS and pr.channel_configured(ch)]
    if ip:
        rows.append((OPT, f"{'·'.join(ip)} 호출 IP 등록은 여기서 확인 못 함 — 실행 중 HTTP 403(ip … not allowed)이 나면 "
                          "README '키 발급'대로 지금 IP 를 등록", ""))
    return rows, n


def _channels(pr: Probe, skill: str):
    rows, n = _channel_rows(pr)
    if n == 0:
        rows.insert(0, (BAD, "채널 키가 하나도 없음", KEYS_FIX))
    return rows


def _channels_or_csv(pr: Probe, skill: str):
    rows, n = _channel_rows(pr)
    if n == 0:
        rows.insert(0, (OPT, "채널 키 없음 — 매대표.csv 를 직접 채워 쓰는 방식도 됨",
                        ""))
    return rows


def _cafe24_login(pr: Probe, skill: str):
    if not pr.channel_configured("cafe24"):
        return [(OPT, "카페24 로그인 — 카페24 를 쓸 때만", "")]
    if pr.cafe24_token():
        return [(OK, "카페24 로그인됨(토큰 파일 있음)", "")]
    return [(BAD, "카페24 로그인 안 됨", "클로드에게 \"카페24 로그인\"(= python3 shared/channels/cafe24.py login)")]


def _stock_csv(pr: Probe, skill: str):
    where = "/".join(("output",) + STOCK_CSV)
    if pr.stock_csv():
        return [(OK, f"재고표 있음({where})", "")]
    return [(BAD, f"재고표 없음({where})",
             f"양식 .claude/skills/shelf-check/templates/재고표.csv 를 {where} 로 복사해 엑셀로 채우기")]


def _store(pr: Probe, skill: str):
    if pr.store_filled():
        return [(OK, "브랜드_SSOT.md 채워짐", "")]
    return [(OPT, "브랜드_SSOT.md 비어 있음(선택 — 없어도 작동 · 채우면 결과가 내 가게에 맞춰짐)", "")]


CHECKS = {"python": _python, "node": _node, "chrome": _chrome, "mcp": _mcp, "packages": _packages,
          "gemini": _gemini, "channels": _channels, "channels_or_csv": _channels_or_csv,
          "cafe24_login": _cafe24_login, "stock_csv": _stock_csv, "store": _store}


def check(skill: str, pr: Probe | None = None) -> list[tuple]:
    """[(단계 번호, 표시, 글, 고치는 법), …]"""
    pr = pr or Probe()
    out = []
    for i, step in enumerate(SKILLS[skill]["steps"], 1):
        for mark, text, fix in CHECKS[step](pr, skill):
            out.append((i, mark, text, fix))
    return out


def report(skills: list[str], pr: Probe | None = None) -> tuple[str, bool]:
    pr = pr or Probe()
    lines, bad = [], False
    for s in skills:
        meta = SKILLS[s]
        lines.append(f"{meta['no']} {meta['name']} ({s})")
        for i, mark, text, fix in check(s, pr):
            bad = bad or mark == BAD
            lines.append(f"  {mark} {i}. {text}" + (f"  → {fix}" if mark == BAD and fix else ""))
        lines.append("")
    lines.append("❌ 가 있습니다 — 줄 끝 → 대로 고친 뒤 다시 점검하세요." if bad else "준비 끝 — ❌ 없음.")
    return "\n".join(lines), bad


def main(argv: list[str] | None = None, pr: Probe | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    target = argv[0] if argv else "all"
    if target in ("-h", "--help"):
        print(f"사용법: python3 shared/doctor.py [all | {' | '.join(SKILLS)}]  — 스킬별 준비 상태 ✅/❌/⚪")
        return 0
    if target == "all":
        skills = list(SKILLS)
    elif target in SKILLS:
        skills = [target]
    else:
        print(f"스킬 이름을 확인하세요: all · {' · '.join(SKILLS)}")
        return 2
    text, bad = report(skills, pr)
    print(text)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
