#!/usr/bin/env python3
"""원장.md 들을 읽어 output/dashboard.html 과 건별 report.html 을 만든다.

    python3 dashboard/make_dashboard.py              # 결과물 폴더 = 레포 맨 위 output/
    python3 dashboard/make_dashboard.py --root <폴더>  # 결과물 폴더가 다른 곳에 있을 때

표준 라이브러리만 쓴다. 규격은 같은 폴더의 README.md.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]   # dashboard → 루트 (루트 CLAUDE.md §5 표준 머리)
sys.path.insert(0, str(ROOT))
from shared import ledger  # noqa: E402  원장 읽기는 shared/ledger.py 한 곳
from shared.paths import output_dir  # noqa: E402  결과물 폴더 위치는 shared/paths.py 한 곳

# 탭 = (이름, 결과물 폴더(output/) 안의 폴더, report.html 에 먼저 싣는 md 순서)
TABS = [
    ("상세페이지", "상세페이지", ["시사점.md", "전사.md"]),
    ("레퍼런스", "레퍼런스", ["분석.md", "전사.md"]),
]

# 문의 탭 — 보기 전용. 문의 스킬이 만든 csv 를 읽기만 한다(답변 보내기 코드는 묶음 어디에도 없다).
INBOX_CSV = Path("문의") / "문의함.csv"
INBOX_STATES = ["미답변"]   # 스크립트가 쓰는 값은 이것 하나. 사장님이 바꿔 쓴 상태(답함 등)는 나오는 대로 센다
INBOX_LIST_MAX = 50

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
LEDGER = "원장.md"
REPORT = "report.html"
DASHBOARD = "dashboard.html"   # 결과물 폴더 맨 위에 만든다

CSS = """
:root{--bg:#f6f5f2;--card:#fff;--fg:#1d1d1f;--sub:#6b6b70;--line:#e3e1dc;--accent:#2f6f5e;--chip:#eef3f1;--img:#f0efeb}
@media (prefers-color-scheme: dark){:root{--bg:#161618;--card:#1f1f22;--fg:#ececee;--sub:#9a9aa1;--line:#323236;--accent:#7cc4ad;--chip:#23302c;--img:#2a2a2e}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Malgun Gothic",sans-serif}
a{color:var(--accent)}
.wrap{max-width:1100px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:22px;margin:0 0 4px}
.meta{color:var(--sub);font-size:13px;margin:0 0 20px}
"""

INDEX_CSS = CSS + """
.tabs{display:flex;gap:8px;border-bottom:1px solid var(--line);margin-bottom:20px}
.tabs button{border:0;background:none;color:var(--sub);font:inherit;padding:8px 4px;margin-right:12px;cursor:pointer;border-bottom:2px solid transparent}
.tabs button.on{color:var(--fg);font-weight:600;border-bottom-color:var(--accent)}
.tabs .n{font-size:12px;color:var(--sub);margin-left:4px}
.panel{display:none}.panel.on{display:block}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;display:flex;flex-direction:column}
.thumb{height:180px;background:var(--img);display:block}
.thumb img{width:100%;height:100%;object-fit:cover;object-position:top;display:block}
.body{padding:12px 14px 14px;display:flex;flex-direction:column;gap:6px;flex:1}
.title{font-weight:600;font-size:16px;margin:0}
.date{color:var(--sub);font-size:12px}
.sum{font-size:13px;margin:0;flex:1}
.links{display:flex;gap:12px;font-size:13px;flex-wrap:wrap}
.miss{color:var(--sub);font-size:12px}
.empty{color:var(--sub);padding:40px 0;text-align:center}
.stats{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:18px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;min-width:120px}
.stat b{display:block;font-size:22px}.stat span{color:var(--sub);font-size:13px}
h2{font-size:16px;margin:22px 0 8px}
.tbl{overflow-x:auto}
table{border-collapse:collapse;font-size:14px;width:100%;background:var(--card)}
th,td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{background:var(--chip)}
.note{color:var(--sub);font-size:13px;margin-top:18px;border-top:1px solid var(--line);padding-top:10px}
"""

REPORT_CSS = CSS + """
.wrap{max-width:860px}
.back{font-size:13px}
.doc{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 24px 20px;margin-top:20px;overflow-x:auto}
.doc h1{font-size:20px;margin:16px 0 8px}.doc h2{font-size:18px;margin:20px 0 8px}.doc h3,.doc h4{font-size:16px;margin:16px 0 6px}
table{border-collapse:collapse;margin:10px 0;font-size:14px;width:100%}
th,td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{background:var(--chip)}
blockquote{margin:10px 0;padding:4px 14px;border-left:3px solid var(--accent);color:var(--sub)}
code{background:var(--chip);padding:1px 5px;border-radius:4px;font-size:13px}
pre{background:var(--chip);padding:10px;border-radius:6px;overflow-x:auto}pre code{padding:0;background:none}
.scene{background:var(--img);color:var(--sub);border-radius:6px;padding:6px 10px;margin:8px 0;font-size:14px}
hr{border:0;border-top:1px solid var(--line);margin:18px 0}
.src{color:var(--sub);font-size:12px;margin:0 0 4px}
"""

INDEX_JS = """
(function(){
  var bs=document.querySelectorAll('.tabs button'), ps=document.querySelectorAll('.panel');
  function show(i){bs.forEach(function(b,j){b.classList.toggle('on',i===j)});ps.forEach(function(p,j){p.classList.toggle('on',i===j)});
    try{history.replaceState(null,'','#'+bs[i].dataset.k)}catch(e){}}
  bs.forEach(function(b,i){b.addEventListener('click',function(){show(i)})});
  function fromHash(){var h=decodeURIComponent(location.hash.slice(1)), k=0;
    bs.forEach(function(b,i){if(b.dataset.k===h)k=i}); show(k);}
  window.addEventListener('hashchange',fromHash);
  fromHash();
})();
"""


# ---------------------------------------------------------------- 원장 읽기

def _split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_sep(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", c) for c in cells)


def read_rows(path: Path) -> tuple[list[dict], list[str]]:
    """원장 행을 shared.ledger.read 로 읽어 열 **순서**로 5칸에 붙인다 → (행 목록, 경고 목록)."""
    rows, warns = [], []
    try:
        recs = ledger.read(path)
    except ledger.LedgerError as e:
        return rows, [f"원장을 못 읽음 — {e}"]
    for rec in recs:
        cells = [str(v if v is not None else "").strip() for v in rec.values()]
        if len(cells) != 5:
            return rows, [f"{path.name}: 열이 {len(cells)}개(5개여야 함 — README 2절) — 이 탭은 비워 둠"]
        rows.append(dict(zip(("date", "title", "url", "summary", "folder"), cells)))
    return rows, warns


def folder_name(cell: str) -> str:
    """`[이름](이름/)` 링크 꼴이면 괄호 안을, 아니면 글자 그대로. 끝의 / 는 뗀다."""
    m = re.fullmatch(r"\[[^\]]*\]\(([^)]+)\)", cell)
    name = m.group(1) if m else cell
    return name.strip().strip("`").rstrip("/")


def find_thumb(d: Path) -> Path | None:
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        p = d / f"thumb{ext}"
        if p.is_file():
            return p
    for sub in (d / "원본", d):
        if sub.is_dir():
            imgs = sorted(p for p in sub.iterdir() if p.is_file() and p.suffix.lower() in IMG_EXT)
            if imgs:
                return imgs[0]
    return None


# ---------------------------------------------------------------- md → html

def _inline(text: str) -> str:
    """한 줄 안의 꾸밈. 먼저 escape 하고 나서 표시를 바꾼다(원문 html 은 글자로 보인다)."""
    codes: list[str] = []

    def keep(m):
        codes.append(f"<code>{m.group(1)}</code>")
        return f"\x00{len(codes) - 1}\x00"

    s = html.escape(text, quote=False)
    s = re.sub(r"`([^`]+)`", keep, s)

    def link(m):
        label, url = m.group(1), m.group(2)
        if re.match(r"https?://", url):
            href = url.replace('"', "&quot;")   # 앞에서 이미 escape 했다 — 따옴표만 막는다(이중 escape 금지)
            return f'<a href="{href}" target="_blank" rel="noopener">{label}</a>'
        return m.group(0)

    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], s)


def md_to_html(md: str) -> str:
    out: list[str] = []
    lines = md.splitlines()
    i, n = 0, len(lines)
    para: list[str] = []

    def flush():
        if para:
            out.append("<p>" + "<br>".join(_inline(x) for x in para) + "</p>")
            para.clear()

    while i < n:
        line = lines[i]
        st = line.strip()
        if not st:
            flush(); i += 1; continue
        if st.startswith("```"):
            flush()
            buf = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i]); i += 1
            out.append("<pre><code>" + html.escape("\n".join(buf), quote=False) + "</code></pre>")
            i += 1; continue
        m = re.match(r"(#{1,4})\s+(.*)", st)
        if m:
            flush()
            lv = len(m.group(1))
            out.append(f"<h{lv}>{_inline(m.group(2))}</h{lv}>")
            i += 1; continue
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", st):
            flush(); out.append("<hr>"); i += 1; continue
        if re.fullmatch(r"\[이미지[^\]]*\]|\[애니메이션[^\]]*\]", st):
            flush(); out.append(f'<div class="scene">{_inline(st)}</div>'); i += 1; continue
        if st.startswith("|") and i + 1 < n and _is_sep(_split_row(lines[i + 1])):
            flush()
            head = _split_row(st)
            out.append("<table><thead><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in head) + "</tr></thead><tbody>")
            i += 2
            while i < n and lines[i].strip().startswith("|"):
                out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in _split_row(lines[i])) + "</tr>")
                i += 1
            out.append("</tbody></table>"); continue
        if st.startswith(">"):
            flush()
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip()); i += 1
            out.append("<blockquote>" + "<br>".join(_inline(x) for x in buf) + "</blockquote>"); continue
        lm = re.match(r"([-*+]|\d+[.)])\s+", st)
        if lm:
            flush()
            tag = "ol" if lm.group(1)[0].isdigit() else "ul"
            out.append(f"<{tag}>")
            while i < n:
                cur = lines[i].strip()
                m2 = re.match(r"([-*+]|\d+[.)])\s+(.*)", cur)
                if not m2 or (("ol" if m2.group(1)[0].isdigit() else "ul") != tag):
                    break
                out.append(f"<li>{_inline(m2.group(2))}</li>"); i += 1
            out.append(f"</{tag}>"); continue
        para.append(st); i += 1
    flush()
    return "\n".join(out)


# ---------------------------------------------------------------- 쓰기

def _rel(target: Path, start: Path) -> str:
    """html 안의 상대 링크. 한글·공백은 % 인코딩."""
    from urllib.parse import quote
    return quote(os.path.relpath(target, start).replace(os.sep, "/"))


def _page(title: str, css: str, body: str, js: str = "") -> str:
    return (
        "<!doctype html>\n<html lang=\"ko\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{html.escape(title)}</title><style>{css}</style></head>"
        f"<body><div class=\"wrap\">{body}</div>"
        + (f"<script>{js}</script>" if js else "")
        + "</body></html>\n"
    )


def write_report(d: Path, row: dict, order: list[str], dash_html: Path) -> Path | None:
    mds = [d / name for name in order if (d / name).is_file()]
    mds += sorted(p for p in d.glob("*.md") if p.name not in order)
    if not mds:
        return None
    parts = []
    for p in mds:
        parts.append(f'<section class="doc"><p class="src">{html.escape(p.name)}</p>'
                     f"{md_to_html(p.read_text(encoding='utf-8'))}</section>")
    url = row["url"]
    url_html = (f'<a href="{html.escape(url)}" target="_blank" rel="noopener">원문 열기</a>'
                if re.match(r"https?://", url) else html.escape(url))
    body = (f'<p class="back"><a href="{_rel(dash_html, d)}">← 대시보드</a></p>'
            f"<h1>{html.escape(row['title'])}</h1>"
            f'<p class="meta">{html.escape(row["date"])} · {url_html}</p>' + "".join(parts))
    out = d / REPORT
    out.write_text(_page(f"{row['title']} 분석", REPORT_CSS, body), encoding="utf-8")
    return out


def _days(received: str, today: dt.date) -> int | None:
    try:
        return (today - dt.date.fromisoformat(received.strip()[:10])).days
    except ValueError:
        return None


def inbox_panel(root: Path, today: dt.date) -> tuple[str, int, list[str]]:
    """문의함.csv → (패널 html, 미답변 수, 경고). 읽기만 한다 — 버튼·폼·발송 코드 없음."""
    path = root / INBOX_CSV
    foot = ('<p class="note">이 화면은 보기 전용이다. 이 묶음에는 답변 보내기 코드가 없다 — 답은 각 채널 관리자에서 직접 보낸다.'
            ' 보내기도 API 로 가능하지만 위험해서 재료만 둔다(문의 스킬 완성하기.md).</p>')
    if not path.is_file():
        return ('<p class="empty">아직 모은 문의 없음 — 문의 스킬을 실행하세요.</p>' + foot), 0, []
    warns: list[str] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]
    need = {"채널", "접수일", "상품", "문의 원문", "상태"}
    if rows and not need <= set(rows[0]):
        warns.append(f"[문의] {INBOX_CSV} 열이 모자람: {sorted(need - set(rows[0]))}")
    by_state = {k: 0 for k in INBOX_STATES}
    by_channel: dict[str, int] = {}
    waiting = []
    for r in rows:
        st = r.get("상태", "")
        by_state[st] = by_state.get(st, 0) + 1
        if st == "미답변":
            ch = r.get("채널", "") or "(채널 없음)"
            by_channel[ch] = by_channel.get(ch, 0) + 1
            waiting.append(r)
    # 오래 기다린 순 — 날짜를 못 읽은 줄은 맨 뒤
    waiting.sort(key=lambda r: (_days(r.get("접수일", ""), today) is None,
                                -(_days(r.get("접수일", ""), today) or 0)))
    stat = "".join(f'<div class="stat"><b>{n}</b><span>{html.escape(k)}</span></div>'
                   for k, n in by_state.items())
    ch_rows = "".join(f"<tr><td>{html.escape(k)}</td><td>{n}</td></tr>"
                      for k, n in sorted(by_channel.items(), key=lambda x: -x[1]))
    ch_tbl = (f'<div class="tbl"><table><thead><tr><th>채널</th><th>미답변</th></tr></thead>'
              f"<tbody>{ch_rows}</tbody></table></div>" if ch_rows else '<p class="miss">미답변 없음</p>')
    lst = []
    for r in waiting[:INBOX_LIST_MAX]:
        d = _days(r.get("접수일", ""), today)
        text = r.get("문의 원문", "").replace("\n", " ")
        short = text[:60] + ("…" if len(text) > 60 else "")
        lst.append(f"<tr><td>{html.escape(r.get('접수일', ''))}</td>"
                   f"<td>{'' if d is None else f'{d}일째'}</td>"
                   f"<td>{html.escape(r.get('채널', ''))}</td><td>{html.escape(r.get('상품', ''))}</td>"
                   f"<td>{html.escape(short)}</td></tr>")
    more = (f'<p class="miss">오래된 {INBOX_LIST_MAX}건만 보인다(전체 미답변 {len(waiting)}건).</p>'
            if len(waiting) > INBOX_LIST_MAX else "")
    lst_tbl = (f'<div class="tbl"><table><thead><tr><th>접수일</th><th>기다림</th><th>채널</th><th>상품</th>'
               f'<th>문의 (앞 60자)</th></tr></thead><tbody>{"".join(lst)}</tbody></table></div>{more}'
               if lst else '<p class="miss">미답변 없음</p>')
    body = (f'<div class="stats">{stat}</div>'
            f"<h2>채널별 미답변</h2>{ch_tbl}"
            f"<h2>오래 기다린 미답변</h2>{lst_tbl}{foot}")
    return body, len(waiting), warns


def build(root: Path, out_html: Path, today: dt.date | None = None) -> tuple[int, list[str]]:
    tab_btns, panels, warns, total = [], [], [], 0
    dash_dir = out_html.parent
    for name, folder, order in TABS:
        base = root / folder
        rows, w = read_rows(base / LEDGER)
        warns += [f"[{name}] {x}" for x in w]
        cards = []
        for row in reversed(rows):                       # 최근 줄이 위로
            d = (base / folder_name(row["folder"])).resolve()
            if d.parent != base.resolve():               # 원장 옆 폴더만 — ../ 로 밖을 가리키면 거절
                warns.append(f"[{name}] 원장 옆 폴더가 아님(건너뜀): {row['folder']}")
                rep, thumb = None, None
            elif not d.is_dir():
                warns.append(f"[{name}] 폴더 없음: {d}")
                rep, thumb = None, None
            else:
                rep = write_report(d, row, order, out_html)
                thumb = find_thumb(d)
            img = (f'<img src="{_rel(thumb, dash_dir)}" alt="" loading="lazy">' if thumb else "")
            thumb_html = (f'<a class="thumb" href="{_rel(rep, dash_dir)}">{img}</a>' if rep
                          else f'<div class="thumb">{img}</div>')
            links = []
            if rep:
                links.append(f'<a href="{_rel(rep, dash_dir)}">분석 보기</a>')
            else:
                links.append('<span class="miss">분석 파일 없음</span>')
            if re.match(r"https?://", row["url"]):
                links.append(f'<a href="{html.escape(row["url"])}" target="_blank" rel="noopener">원문</a>')
            cards.append(
                f'<article class="card">{thumb_html}<div class="body">'
                f'<p class="title">{html.escape(row["title"])}</p>'
                f'<span class="date">{html.escape(row["date"])}</span>'
                f'<p class="sum">{html.escape(row["summary"])}</p>'
                f'<div class="links">{"".join(links)}</div></div></article>')
        total += len(cards)
        key = html.escape(folder)
        tab_btns.append(f'<button data-k="{key}">{html.escape(name)}<span class="n">{len(cards)}</span></button>')
        inner = (f'<div class="grid">{"".join(cards)}</div>' if cards
                 else f'<p class="empty">아직 없음 — <code>{key}/{LEDGER}</code> 에 첫 줄이 생기면 여기 보인다.</p>')
        panels.append(f'<section class="panel">{inner}</section>')
    inbox, unanswered, w = inbox_panel(root, today or dt.date.today())
    warns += w
    tab_btns.append(f'<button data-k="문의">문의<span class="n">미답변 {unanswered}</span></button>')
    panels.append(f'<section class="panel">{inbox}</section>')
    body = ("<h1>분석 대시보드</h1>"
            f'<p class="meta">원장·문의함에서 만든 화면 · 분석 {total}건 · 다시 만들기: '
            "<code>python3 dashboard/make_dashboard.py</code></p>"
            f'<nav class="tabs">{"".join(tab_btns)}</nav>' + "".join(panels))
    out_html.write_text(_page("분석 대시보드", INDEX_CSS, body, INDEX_JS), encoding="utf-8")
    return total, warns


def main() -> int:
    ap = argparse.ArgumentParser(description=f"원장.md → output/{DASHBOARD}")
    ap.add_argument("--root", type=Path, default=output_dir(),
                    help="상세페이지/·레퍼런스/·문의/ 가 있는 결과물 폴더 (기본: 레포 맨 위 output/)")
    ap.add_argument("--out", type=Path, default=None, help=f"만들 html 경로 (기본: <결과물 폴더>/{DASHBOARD})")
    a = ap.parse_args()
    root = a.root.resolve()
    out = (a.out or root / DASHBOARD).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    total, warns = build(root, out)
    for w in warns:
        print("경고:", w, file=sys.stderr)
    print(f"완료: {out} ({total}건)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
