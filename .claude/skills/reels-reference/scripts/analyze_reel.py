"""릴스 레퍼런스 분석 — 인스타 릴스 URL 1개 → output/레퍼런스/<yyyymmdd>_<slug>/ 폴더 + 원장 한 줄.

하는 일(순서대로):
  1. Gemini API 키 확인(없으면 친절한 문장으로 멈춘다 — 다운로드보다 먼저)
  2. 영상 받기 — yt-dlp 가 내 크롬의 인스타 로그인을 빌려 쓴다(--cookies-from-browser chrome)
     받기에 실패하면 종료 코드 3 으로 멈추고 "캡션 기준 모드"로 다시 부르라고 안내한다
     (클로드가 반자동크롤러로 캡션·화면 텍스트를 읽어 파일로 저장 → --caption-file 로 재실행)
  3. Gemini 에 영상째 업로드(Files API) + 분석 지시 → JSON
  4. 건별 폴더에 원본.mp4 · thumb.jpg · 전사.md · 분석.md · analysis.json 저장
  5. output/레퍼런스/원장.md 맨 아래에 한 줄 추가(표 전체를 다시 쓰지 않는다)
  report.html 과 대시보드는 dashboard/make_dashboard.py 가 이 폴더의 md 로 만든다.

실행(어느 폴더에서든 — 아래는 레포 맨 위 기준 경로):
  python3 .claude/skills/reels-reference/scripts/analyze_reel.py "<릴스 URL>"
  python3 .claude/skills/reels-reference/scripts/analyze_reel.py "<릴스 URL>" --caption-file 캡션.txt

종료 코드: 0 성공 · 2 준비물 부족(키·패키지) · 3 영상 받기 실패(캡션 기준 모드로) · 4 분석 실패
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import mimetypes
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]   # 레포 맨 위(shared/ · 브랜드_SSOT.md · .env) — 루트 CLAUDE.md §5 표준 머리
sys.path.insert(0, str(ROOT))
from shared import env, ledger, store_profile  # noqa: E402  .env·원장·브랜드_SSOT.md 읽기는 shared 한 곳
from shared.paths import output_dir  # noqa: E402  결과물 폴더 위치는 shared/paths.py 한 곳

# ── 위치 ──────────────────────────────────────────────────────────
SKILL_DIR = Path(__file__).resolve().parent.parent          # .claude/skills/reels-reference/
PATTERN_DOC = SKILL_DIR / "패턴집.md"
TAG_AXES = SKILL_DIR / "tag_axes.json"
TAB_DIR_NAME = "레퍼런스"
LEDGER_NAME = "원장.md"
PATTERN_START = "<!-- PATTERN-BLOCK-START -->"
PATTERN_END = "<!-- PATTERN-BLOCK-END -->"

# ── 조절값 ────────────────────────────────────────────────────────
# 분석 모델. flash = 영상 분석 품질 충분 + 비용 최저. .env 의 GEMINI_MODEL 로 바꿀 수 있다.
DEFAULT_MODEL = "gemini-3.8-flash"
TEMPERATURE = 0.4                 # 분석은 창의성보다 일관성
MAX_OUTPUT_TOKENS = 32768         # 씬 표가 길어도 JSON 이 잘리지 않게(상한일 뿐 — 쓴 만큼만 과금)
FILE_WAIT_SEC = 300               # 업로드한 영상이 '처리 중'에서 풀릴 때까지 기다리는 상한
MAX_VIDEO_SEC = 300               # 5분 넘는 영상은 받지 않는다(릴스는 대부분 90초 이하)
YTDLP_TIMEOUT_SEC = 600
STORE_DOC_MAX_CHARS = 12000       # 브랜드_SSOT.md 는 앞부분만 프롬프트에 넣는다(비용) — 맨 끝 '하지 않는 말'이 잘리지 않게 넉넉히
COOKIE_ARGS = ["--cookies-from-browser", "chrome"]   # 내 크롬의 인스타 로그인 재사용

EXIT_SETUP, EXIT_DOWNLOAD, EXIT_ANALYZE = 2, 3, 4


class Stop(Exception):
    """사람에게 보여줄 문장 + 종료 코드로 멈춘다(스택트레이스 대신)."""

    def __init__(self, message: str, code: int):
        super().__init__(message)
        self.code = code


# ── 1. 준비물 확인 ─────────────────────────────────────────────────
def get_setting(name: str) -> str:
    return (env.get(name, required=False) or "").strip()


def require_api_key() -> str:
    key = get_setting("GEMINI_API_KEY")
    if not key:
        raise Stop(
            "Gemini API 키가 없어서 멈췄어요.\n"
            "  이 스킬은 영상을 Gemini 에 통째로 보여주고 분석하기 때문에 키가 꼭 필요해요.\n"
            "  1) 루트 README '키 발급' 절을 따라 키를 만드세요.\n"
            "  2) 클로드 코드에 \"키 넣어줘\" 라고 하면 창이 뜹니다 — 거기에 붙여넣으세요\n"
            "     (= python3 shared/setup_keys.py --only gemini).\n"
            "  3) 키는 채팅창·문서에 붙여넣지 마세요.",
            EXIT_SETUP)
    return key


def require_packages() -> None:
    missing = []
    for mod, pip_name in (("google.genai", "google-genai"), ("yt_dlp", "yt-dlp")):
        try:
            found = importlib.util.find_spec(mod) is not None
        except ModuleNotFoundError:                    # 'google' 자체가 없을 때
            found = False
        if not found:
            missing.append(pip_name)
    if missing:
        raise Stop(
            f"필요한 프로그램이 아직 안 깔려 있어요: {', '.join(missing)}\n"
            "  레포 맨 위에서 한 줄 실행하세요:\n"
            "    python3 -m pip install -r .claude/skills/reels-reference/requirements.txt",
            EXIT_SETUP)
    if sys.version_info < (3, 10):
        print("[주의] 파이썬이 3.10 보다 낮아요. 인스타 받기 도구(yt-dlp)의 새 버전이 안 깔려 "
              "받기가 실패할 수 있어요 — 실패하면 사용법.md '안 될 때'를 보세요.", file=sys.stderr)


# ── 2. URL · 폴더 ────────────────────────────────────────────────
IG_RE = re.compile(r"^https?://(?:www\.|m\.)?instagram\.com/(?:[^/?#]+/)?(reels?|p|tv)/([A-Za-z0-9_-]+)")


def parse_reel_url(url: str) -> str:
    """인스타 릴스·포스트 URL → 짧은 코드(폴더 이름에 쓴다). 아니면 Stop."""
    m = IG_RE.match(url.strip())
    if not m:
        raise Stop(f"인스타그램 릴스 주소가 아니에요: {url[:120]}\n"
                   "  예) https://www.instagram.com/reel/AbCdEf123/", EXIT_SETUP)
    return m.group(2)


def safe_slug(text: str) -> str:
    s = re.sub(r"[^\w가-힣-]+", "_", text.strip()).strip("_")
    return s[:40] or "reel"


def make_case_dir(tab_dir: Path, date_str: str, slug: str) -> Path:
    """output/레퍼런스/<yyyymmdd>_<slug>/ — 이미 분석이 끝난 폴더면 _2, _3 … 새로. 덜 끝난 폴더는 이어 쓴다
    (영상 받기 실패 → 캡션 기준으로 다시 부를 때 같은 폴더를 쓰게)."""
    base = f"{date_str}_{slug}"
    n = 1
    while True:
        d = tab_dir / (base if n == 1 else f"{base}_{n}")
        if not (d / "분석.md").exists():
            d.mkdir(parents=True, exist_ok=True)
            return d
        n += 1


# ── 3. 영상 받기(yt-dlp + 내 크롬 쿠키) ──────────────────────────
def _ytdlp(args: list, timeout: int) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "yt_dlp", *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise Stop(_download_fail_msg(f"{timeout}초 안에 끝나지 않음"), EXIT_DOWNLOAD) from None


def fetch_info(url: str) -> dict:
    r = _ytdlp(["--skip-download", "--dump-json", "--no-playlist", *COOKIE_ARGS, url], 120)
    if r.returncode != 0:
        raise Stop(_download_fail_msg(r.stderr), EXIT_DOWNLOAD)
    line = next((l for l in r.stdout.splitlines() if l.strip()), "")
    try:
        return json.loads(line) if line else {}
    except json.JSONDecodeError:
        raise Stop(_download_fail_msg("영상 정보를 읽지 못함"), EXIT_DOWNLOAD) from None


def download_video(url: str, case_dir: Path) -> Path:
    # ffmpeg 가 있으면 영상+소리 따로 받아 합치고(720p 상한), 없으면 한 파일짜리만 받는다.
    if shutil.which("ffmpeg"):
        fmt = "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]/best"
    else:
        fmt = "best[ext=mp4][height<=720]/best[ext=mp4]/best"
    out = str(case_dir / "원본.%(ext)s")
    r = _ytdlp(["--no-playlist", "--force-overwrites", "-f", fmt, "-o", out, *COOKIE_ARGS, url],
               YTDLP_TIMEOUT_SEC)
    if r.returncode != 0:
        raise Stop(_download_fail_msg(r.stderr), EXIT_DOWNLOAD)
    for f in sorted(case_dir.glob("원본.*")):
        if f.suffix.lower() in (".mp4", ".mov", ".webm", ".mkv", ".m4v"):
            return f
    raise Stop(_download_fail_msg("받은 파일 중 영상이 없음"), EXIT_DOWNLOAD)


def _download_fail_msg(stderr: str) -> str:
    tail = (stderr or "").strip().splitlines()[-3:]
    return ("영상을 받지 못했어요.\n"
            "  흔한 원인: 크롬에서 인스타 로그인이 풀림 · 맥이 '크롬 저장소 접근'을 물었는데 거부함 · "
            "비공개/삭제된 릴스.\n"
            "  마지막 오류: " + (" / ".join(tail) if tail else "(없음)"))


def save_thumbnail(info: dict, case_dir: Path) -> None:
    """썸네일 1장 → thumb.jpg (대시보드 카드 사진). 실패해도 분석은 계속."""
    url = info.get("thumbnail")
    if not url:
        return
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            (case_dir / "thumb.jpg").write_bytes(resp.read())
    except Exception as ex:                             # noqa: BLE001 — 썸네일은 부가물
        print(f"[썸네일] 저장 못 함(계속 진행): {ex}", file=sys.stderr)


# ── 4. 프롬프트 ──────────────────────────────────────────────────
# 마케팅 7원칙 압축 렌즈 — 판단 기준으로 쓸 요약본만 넣는다.
LENS = """[분석 렌즈 — 마케팅 7원칙 (본능분석 반박제거가 근간)]
1. 본능분석 반박제거: 뇌는 '욕망'으로 움직이고 '의심'으로 멈춘다. 이 콘텐츠가 어떤 근본
   욕망(생존/번식/지위)을 건드리고, 어떤 의심을 어떻게 제거하는지가 분석의 중심.
2. 상식파괴·3초 후킹: 예상을 깨는 순간에 주의가 집중된다.
3. 구체어·숫자: 추상은 불신, 구체적 수치·사례가 확신을 만든다.
4. 손실 회피: 이득보다 손실에 2배 민감 — "놓치면 손해" 프레이밍.
5. 정체성 자극: "혹시 나도?" — 자아상을 건드리는 메시지.
6. 권위·사회적 증거: 전문가·후기·다수의 선택이 판단 비용을 줄인다.
7. 정보 격차: 빈칸("OOO", '이것')은 채우려는 충동을 만든다."""

# 환각 방지 바닥 — 보지 못한 것을 그럴싸하게 지어내는 사고를 막는다.
NO_GUESS = ("★ 제공된 자료(첨부 영상·아래 캡션 텍스트)에 **실제로 있는 것만** 말하라. "
            "제공되지 않은 것(안 본 영상·열지 못한 링크)은 추정·창작 금지 — "
            "근거가 없으면 그 항목은 null이나 빈 배열로 두고, 모르면 모른다고 하라.")


def load_pattern_block() -> str:
    text = PATTERN_DOC.read_text(encoding="utf-8")
    start = text.index(PATTERN_START) + len(PATTERN_START)
    return text[start:text.index(PATTERN_END, start)].strip()


def tags_block(axes: dict, has_store: bool) -> str:
    total_max = axes.get("total_tag_max", 4)
    lines = [f"[태그 규칙] 전체 태그 합계 최대 {total_max}개 — 이 릴스를 가장 잘 설명하는 것만. "
             "애매하면 달지 말 것(적은 태그가 맞는 태그다).",
             "아래 축에서만 축 태그를 고른다(축당 최대 1개, 목록에 없는 단어로 축 태그 창작 금지)."]
    for axis, values in axes.get("axes", {}).items():
        if values:
            lines.append(f"- {axis}: {', '.join(values)}")
        elif has_store:                                # 비워 둔 축 = 브랜드_SSOT.md 에서 값을 가져온다
            lines.append(f"- {axis}: [우리 가게] 문서의 '{axis}' 항목에 적힌 것 중에서만")
    lines.append(f"목록 밖 자유 태그는 최대 {axes.get('free_tag_max', 1)}개(꼭 필요할 때만).")
    lines.append('출력은 축 구분 없이 평탄한 문자열 배열 하나로: "tags": ["숏폼", "3초후킹"]')
    return "\n".join(lines)


SCENES_BLOCK = """[씬 나누기 — 영상이 첨부된 경우만]
"scenes"에 의미 단위 씬 배열을 넣어라:
- 각 씬 = {"start_sec": 정수, "end_sec": 정수, "description": "무슨 일이 일어나는지 1~2문장",
  "role": "후킹|전개|전환|CTA 중 하나",
  "text_overlay": [{"timestamp": "0:03", "voice": "들리는 말 그대로(없으면 null)",
    "text": "화면 자막·글자 그대로(없으면 null)"}]}
- 말과 화면 글자는 들리는/보이는 그대로 받아 적어라(요약·윤문 금지). 그 씬에 없으면 빈 배열.
- 경계는 초 단위 정수만. 씬끼리 겹치지 말 것, 첫 씬 start_sec=0, 마지막 end_sec≈영상 길이.
- 씬 개수·경계는 장면·메시지가 바뀌는 곳으로 네가 판단하라."""


def store_block(store_text: str | None) -> str:
    if not store_text:
        return ("[우리 가게] 브랜드_SSOT.md 가 아직 비어 있다(템플릿 그대로). my_store_apply 는 null 로 두고, "
                "my_store_hooks 는 [제품]·[고객] 같은 대괄호 빈칸이 들어간 일반 문구로 써라.")
    if len(store_text) > STORE_DOC_MAX_CHARS:
        print(f"[경고] 브랜드_SSOT.md 가 {STORE_DOC_MAX_CHARS}자를 넘어 뒷부분이 잘렸습니다 "
              f"(전체 {len(store_text)}자) — 맨 끝 '하지 않는 말'이 빠질 수 있어요.", file=sys.stderr)
    return ("[우리 가게 — 브랜드_SSOT.md 원문]\n" + store_text[:STORE_DOC_MAX_CHARS] +
            "\n\n응용(my_store_apply·my_store_hooks)은 위 문서의 파는 것·소구점·타깃·말투에만 근거하라. "
            "문서에 없는 제품·혜택·수치·후기는 지어내지 마라.")


def build_prompt(*, has_video: bool, duration_sec: float, caption: str | None,
                 store_text: str | None, note: str | None) -> str:
    axes = json.loads(TAG_AXES.read_text(encoding="utf-8"))
    if has_video:
        src = "인스타그램 릴스 영상(첨부)" + (f" — 길이 약 {int(duration_sec)}초" if duration_sec else "")
    else:
        src = ("인스타그램 릴스의 **캡션·화면 텍스트만**(영상은 보지 못했다). 영상 속 말·장면·음악은 "
               "모른다 — 씬 표는 빈 배열, 3초 훅은 텍스트에 실제로 있는 첫 문장만.")
    parts = [
        "당신은 작은 온라인 가게의 숏폼(릴스) 레퍼런스 분석가다. 잘 된 릴스에서 '무엇이 먹혔는지'에 "
        "패턴 이름을 붙이고, 우리 가게 영상에 옮길 수 있게 정리한다.",
        f"입력: {src}",
        "반드시 한국어로 답하라.",
        NO_GUESS, "", LENS, "",
        tags_block(axes, bool(store_text)), "",
        load_pattern_block(),
        "위 패턴 사전에 **명확히 해당할 때만** 고른다(억지 매칭 금지 — 해당 없으면 null·빈 배열).",
        "", store_block(store_text),
    ]
    if caption:
        parts += ["", "[캡션·화면 텍스트 원문]\n" + caption.strip()]
    if note:
        parts += ["", f"[올린 사람의 메모 — 분석 힌트로 반영]\n{note}"]
    if has_video:
        parts += ["", SCENES_BLOCK]
    parts += ["", """[출력 — 마크다운 코드블록 없이 순수 JSON만]
{
  "title": "30자 이내 — 핵심 소재와 훅이 드러나는 제목",
  "one_line": "40자 이내 한 줄 요약 — 무엇이 먹혔나",
  "summary": "2~3문장 요약(무슨 릴스이며 왜 참고할 가치가 있는지)",
  "tags": ["위 태그 규칙에 따른 평탄 배열"],
  "hook_type": "훅 유형 6 중 정확히 하나의 이름(예: '정보성 훅') — 해당 없으면 null",
  "opening": "오프닝 15 중 해당하는 번호와 문구(예: '2. 그거 아세요?') — 해당 없으면 null",
  "formulas": ["릴스 공식 18 중 명확히 해당하는 이름 — 최대 3개, 없으면 []"],
  "hook_3s": "첫 3초에 실제로 나온 말·화면 글자 원문 그대로 — 없으면 null",
  "hook_why": "그 3초가 왜 손가락을 멈추게 하는지 1~2문장",
  "instinct": "본능분석 — 어떤 근본 욕망을 건드리는지 1~2문장",
  "objection_removal": "반박제거 — 어떤 의심을 어떻게 지우는지(해당 없으면 null)",
  "key_points": ["따라 할 수 있게 구체적인 핵심 포인트 3~5개"],
  "scenes": [ ... 위 씬 나누기 형식 — 영상이 없으면 [] ... ],
  "my_store_apply": "우리 가게에 옮긴다면 — 1~2문장 아이디어",
  "my_store_hooks": [
    {"hook": "우리 가게 영상의 첫 3초 문구", "hook_type": "훅 유형 6 중 하나", "why": "어떤 소구점을 왜 건드리나"}
  ]
}
my_store_hooks 는 정확히 3개."""]
    return "\n".join(parts)


# ── 5. Gemini 호출 ───────────────────────────────────────────────
def _parse_json(raw: str) -> dict:
    """코드펜스 제거 + 바깥 중괄호 추출. 끝내 못 읽으면 Stop(원문은 파일로 남긴다)."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip().removeprefix("json").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError("분석 결과(JSON)를 읽지 못했어요")


def gemini_analyze(api_key: str, model: str, prompt: str, video: Path | None,
                   case_dir: Path) -> dict:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    parts, uploaded = [], None
    try:
        if video:
            mime = mimetypes.guess_type(str(video))[0] or "video/mp4"
            print("[분석] 영상을 Gemini 에 올리는 중…", file=sys.stderr)
            # 경로가 아니라 파일 핸들로 올린다 — SDK 는 경로의 파일명을 HTTP 헤더에 넣는데 헤더는 ASCII 만 되므로
            # 한글 파일명·폴더(원본.mp4 등)가 'ascii codec' 오류로 실패한다. 핸들이면 이름이 헤더에 안 실린다.
            with open(video, "rb") as fh:
                uploaded = client.files.upload(file=fh,
                                               config=types.UploadFileConfig(mime_type=mime))
            waited = 0
            while uploaded.state and uploaded.state.name == "PROCESSING":
                if waited >= FILE_WAIT_SEC:
                    raise TimeoutError(f"Gemini 가 영상 처리를 {FILE_WAIT_SEC}초 안에 못 끝냈어요")
                time.sleep(2)
                waited += 2
                uploaded = client.files.get(name=uploaded.name)
            if uploaded.state and uploaded.state.name == "FAILED":
                raise RuntimeError("Gemini 가 영상 처리에 실패했어요(파일이 깨졌을 수 있음)")
            parts.append(types.Part.from_uri(file_uri=uploaded.uri, mime_type=mime))
        parts.append(types.Part.from_text(text=prompt))
        print(f"[분석] {model} 이 분석하는 중…", file=sys.stderr)
        resp = client.models.generate_content(
            model=model, contents=parts,
            config=types.GenerateContentConfig(
                temperature=TEMPERATURE, max_output_tokens=MAX_OUTPUT_TOKENS,
                response_mime_type="application/json"))
        cands = getattr(resp, "candidates", None) or []
        reason = getattr(getattr(cands[0], "finish_reason", None), "name", "") if cands else ""
        if reason in ("MAX_TOKENS", "SAFETY", "RECITATION"):
            raise RuntimeError({"MAX_TOKENS": "응답이 길이 상한에서 잘렸어요",
                                "SAFETY": "Gemini 안전필터에 걸려 응답이 멈췄어요",
                                "RECITATION": "저작물 인용 제한으로 응답이 멈췄어요"}[reason])
        raw = resp.text or ""
        try:
            parsed = _parse_json(raw)
            if not isinstance(parsed, dict):
                raise ValueError("분석 결과가 예상한 모양(JSON 객체)이 아니에요")
            return parsed
        except ValueError:
            (case_dir / "gemini_원문.txt").write_text(raw, encoding="utf-8")
            raise
    finally:
        if uploaded is not None:                       # 올린 영상은 바로 지운다(어차피 48시간 뒤 자동 삭제)
            try:
                client.files.delete(name=uploaded.name)
            except Exception:                          # noqa: BLE001
                pass


# ── 6. 산출물 쓰기 ───────────────────────────────────────────────
def cell(v) -> str:
    """표 칸 안전화 — 줄바꿈·파이프 제거(원장·표가 깨지지 않게)."""
    s = "" if v is None else str(v)
    return re.sub(r"\s+", " ", s.replace("|", "/")).strip()


def _sec(v) -> str:
    try:
        s = int(float(v))
    except (TypeError, ValueError):
        return "?"
    return f"{s // 60}:{s % 60:02d}"


def _list(v) -> list:
    return [x for x in v if x] if isinstance(v, list) else []


def write_transcript(case_dir: Path, *, url: str, mode_label: str, uploader: str,
                     duration: float, caption: str | None, scenes: list) -> None:
    L = [f"# 전사 — {uploader or '릴스'}", "",
         f"- 원문: {url}", f"- 기준: {mode_label}"]
    if duration:
        L.append(f"- 길이: {_sec(duration)}")
    L += ["", "## 캡션", ""]
    L += [f"> {line}" if line.strip() else ">" for line in (caption or "(캡션 없음)").strip().splitlines()]
    L += ["", "## 말·화면 글자 (시간순)", ""]
    rows = []
    for sc in scenes:
        for t in _list(sc.get("text_overlay")) if isinstance(sc, dict) else []:
            if isinstance(t, dict) and (t.get("voice") or t.get("text")):
                rows.append(f"| {cell(t.get('timestamp'))} | {cell(t.get('voice')) or '-'} "
                            f"| {cell(t.get('text')) or '-'} |")
    if rows:
        L += ["| 시점 | 말(음성) | 화면 글자 |", "|---|---|---|", *rows]
    else:
        L.append("영상을 보지 못해 음성·화면 글자 전사가 없어요(캡션 기준)."
                 if "캡션" in mode_label else "영상에서 받아 적을 말·글자가 없었어요.")
    (case_dir / "전사.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def write_analysis(case_dir: Path, a: dict, *, url: str, mode_label: str, has_store: bool = True) -> None:
    L = [f"# 분석 — {a.get('title') or '릴스'}", ""]
    if "캡션" in mode_label:
        L += ["> ⚠️ **캡션 기준 분석** — 영상을 받지 못해 캡션·화면 텍스트만 보고 분석했어요. "
              "말·장면·음악은 반영되지 않았습니다.", ""]
    L += [f"- 원문: {url}", f"- 기준: {mode_label}", "", a.get("summary") or "", "",
          "## 한눈에", "",
          "| 항목 | 값 |", "|---|---|",
          f"| 훅 유형 | {cell(a.get('hook_type')) or '해당 없음'} |",
          f"| 오프닝 | {cell(a.get('opening')) or '해당 없음'} |",
          f"| 공식 | {cell(' · '.join(_list(a.get('formulas'))[:3])) or '해당 없음'} |",
          f"| 태그 | {cell(' · '.join(_list(a.get('tags'))[:4])) or '-'} |",
          "", "## 3초 훅", "",
          f"> {cell(a.get('hook_3s')) or '(자료에 없음)'}", "",
          a.get("hook_why") or "", "",
          "## 왜 먹혔나", "",
          f"- **본능**: {a.get('instinct') or '-'}",
          f"- **반박 제거**: {a.get('objection_removal') or '해당 없음'}"]
    L += [f"- {p}" for p in _list(a.get("key_points"))]
    scenes = [s for s in _list(a.get("scenes")) if isinstance(s, dict)]
    L += ["", "## 씬 표", ""]
    if scenes:
        L += ["| 구간 | 역할 | 무슨 일 | 자막·말 |", "|---|---|---|---|"]
        for s in scenes:
            words = " / ".join(cell(t.get("text") or t.get("voice"))
                               for t in _list(s.get("text_overlay")) if isinstance(t, dict)
                               and (t.get("text") or t.get("voice")))
            L.append(f"| {_sec(s.get('start_sec'))}~{_sec(s.get('end_sec'))} | {cell(s.get('role'))} "
                     f"| {cell(s.get('description'))} | {words or '-'} |")
    else:
        L.append("씬 표 없음(영상을 보지 못했거나 나눌 장면이 없었어요).")
    generic = "브랜드_SSOT.md 가 비어 있어 일반 제안"     # 브랜드_SSOT.md 는 선택 — 비어 있으면 일반 제안임을 밝힌다
    apply = a.get("my_store_apply") if has_store else None
    L += ["", "## 내 가게에 옮기면", "",
          apply or f"({generic} — 아래 훅 후보의 [제품]·[고객] 같은 빈칸을 내 가게 말로 채워 쓰세요)", "",
          "### 훅 후보 3" + ("" if has_store else f" ({generic})"), ""]
    hooks = [h for h in _list(a.get("my_store_hooks")) if isinstance(h, dict)][:3]
    for i, h in enumerate(hooks, 1):
        L.append(f"{i}. **{cell(h.get('hook'))}** — {cell(h.get('hook_type'))} · {cell(h.get('why'))}")
    if not hooks:
        L.append("(후보를 만들지 못했어요)")
    (case_dir / "분석.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def ledger_summary(a: dict, caption_mode: bool) -> str:
    bits = [a.get("hook_type") or "훅 유형 없음"]
    if a.get("opening"):
        bits.append(f"오프닝 {a['opening']}")
    if _list(a.get("formulas")):
        bits.append("공식 " + "/".join(_list(a.get("formulas"))[:3]))
    if _list(a.get("tags")):
        bits.append(" ".join(f"#{t}" for t in _list(a.get("tags"))[:4]))
    head = "(캡션 기준) " if caption_mode else ""
    return cell(head + " · ".join(str(b) for b in bits) + " — " + (a.get("one_line") or a.get("title") or ""))


# ── 본체 ─────────────────────────────────────────────────────────
def run(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description="인스타 릴스 레퍼런스 분석(Gemini)")
    ap.add_argument("url", help="인스타그램 릴스 주소")
    ap.add_argument("--caption-file", help="캡션 기준 모드 — 반자동크롤러로 읽은 캡션·화면 텍스트 파일")
    ap.add_argument("--slug", help="폴더 이름 꼬리(기본 = 릴스 코드)")
    ap.add_argument("--note", help="분석 힌트 한 줄(예: '경쟁 가게 릴스')")
    args = ap.parse_args(argv)

    api_key = require_api_key()                        # 키부터 — 받기·업로드 전에 멈춘다
    require_packages()
    model = get_setting("GEMINI_MODEL") or DEFAULT_MODEL

    code = parse_reel_url(args.url)
    slug = safe_slug(args.slug or code)
    today = dt.datetime.now()
    tab_dir = output_dir(TAB_DIR_NAME)
    case_dir = make_case_dir(tab_dir, today.strftime("%Y%m%d"), slug)
    print(f"[폴더] {case_dir.relative_to(ROOT)}", file=sys.stderr)

    store_text = store_profile.read().strip() if store_profile.is_filled() else None   # 템플릿 그대로면 None → 일반 제안

    caption_mode = bool(args.caption_file)
    info: dict = {}
    video = None
    if caption_mode:
        cap_path = Path(args.caption_file).expanduser()
        if not cap_path.exists():
            raise Stop(f"캡션 파일이 없어요: {cap_path}", EXIT_SETUP)
        caption = cap_path.read_text(encoding="utf-8").strip()
        if not caption:
            raise Stop("캡션 파일이 비어 있어요 — 읽은 캡션·화면 텍스트를 넣고 다시 실행하세요.", EXIT_SETUP)
        if cap_path.resolve().parent != case_dir.resolve():
            shutil.copyfile(cap_path, case_dir / "캡션.txt")
    else:
        try:
            print("[받기] 내 크롬의 인스타 로그인으로 영상 정보를 읽는 중…", file=sys.stderr)
            info = fetch_info(args.url)
            duration = float(info.get("duration") or 0)
            if duration <= 0:
                raise Stop("이 주소에서 영상을 찾지 못했어요(사진 게시물이거나 비공개·삭제).", EXIT_DOWNLOAD)
            if duration > MAX_VIDEO_SEC:
                raise Stop(f"{MAX_VIDEO_SEC}초 넘는 영상은 받지 않아요(이 영상 {int(duration)}초).",
                           EXIT_DOWNLOAD)
            video = download_video(args.url, case_dir)
        except Stop as ex:
            if ex.code != EXIT_DOWNLOAD:
                raise
            raise Stop(f"{ex}\n\n→ 캡션 기준 모드로 바꾸세요: 반자동크롤러로 이 릴스의 캡션·화면 텍스트를 읽어\n"
                       f"   {case_dir / '캡션.txt'}\n"
                       "   에 저장한 뒤 이렇게 다시 실행:\n"
                       f"   python3 .claude/skills/reels-reference/scripts/analyze_reel.py \"{args.url}\" "
                       f"--caption-file \"{case_dir / '캡션.txt'}\"", EXIT_DOWNLOAD) from None
        save_thumbnail(info, case_dir)
        caption = (info.get("description") or "").strip() or None

    duration = float(info.get("duration") or 0)
    uploader = info.get("uploader_id") or info.get("uploader") or info.get("channel") or ""
    uploader = f"@{uploader}" if uploader and not uploader.startswith("@") else uploader
    mode_label = "영상(Gemini 가 영상을 직접 봄)" if video else "캡션 기준(영상 못 봄)"

    prompt = build_prompt(has_video=bool(video), duration_sec=duration, caption=caption,
                          store_text=store_text, note=args.note)
    try:
        analysis = gemini_analyze(api_key, model, prompt, video, case_dir)
    except Exception as ex:                            # noqa: BLE001 — SDK 오류 종류가 많다
        msg = str(ex)
        if "API key" in msg or "API_KEY" in msg or "PERMISSION_DENIED" in msg:
            msg = "Gemini 가 키를 받아주지 않았어요 — 키를 새로 만들어 \"키 넣어줘\" 로 덮어써 주세요."
        raise Stop(f"분석에 실패했어요: {msg[:400]}\n  (받은 영상은 {case_dir} 에 남아 있어요 — "
                   "다시 실행하면 같은 폴더를 이어 씁니다)", EXIT_ANALYZE) from None

    if not video:                                      # 영상을 못 봤으면 씬·말 전사는 있을 수 없다(지어낸 것)
        analysis["scenes"] = []
    (case_dir / "analysis.json").write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    scenes = [s for s in _list(analysis.get("scenes")) if isinstance(s, dict)]
    write_transcript(case_dir, url=args.url, mode_label=mode_label, uploader=uploader,
                     duration=duration, caption=caption, scenes=scenes)
    write_analysis(case_dir, analysis, url=args.url, mode_label=mode_label, has_store=bool(store_text))

    title = " · ".join(x for x in (uploader, analysis.get("title")) if x) or slug
    ledger_path = tab_dir / LEDGER_NAME               # 열 5개 고정 — dashboard/README.md 규격
    try:
        ledger.append(ledger_path, {
            "날짜": today.strftime("%Y-%m-%d"), "계정·영상": cell(title), "URL": args.url,
            "요약": ledger_summary(analysis, caption_mode), "폴더": case_dir.name})
    except ValueError as ex:                           # LedgerError — 원장 모양이 깨져 있을 때
        raise Stop(f"분석은 {case_dir} 에 저장했지만 원장에 줄을 못 붙였어요: {ex}", EXIT_ANALYZE) from None
    print(f"[완료] {case_dir.relative_to(ROOT)}/분석.md · 전사.md\n"
          f"[원장] {ledger_path.relative_to(ROOT)} 맨 아래 한 줄 추가")
    return 0


def main() -> None:
    try:
        sys.exit(run())
    except Stop as ex:
        print(f"\n[멈춤] {ex}", file=sys.stderr)
        sys.exit(ex.code)


if __name__ == "__main__":
    main()
