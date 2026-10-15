#!/usr/bin/env python3
"""상세 이미지 주소 목록을 받아 순서대로 저장한다 (표준 라이브러리만).

    python3 .claude/skills/detail-page/scripts/download.py <수집.json 또는 주소목록.txt> \\
        --out <폴더>/원본 --referer <상세페이지 URL>

- 입력이 `.json` 이면 수집 스니펫 결과의 `images[].src` 를, 아니면 한 줄에 주소 하나를 읽는다.
- 이름 = `01.jpg`, `02.webp` … (자릿수는 장수에 맞춰 0을 채움 — 이름순 = 위→아래 순서).
- 확장자는 주소 끝 → 서버가 알려준 형식 순서로 정한다. webp·gif 는 그대로 둔다(움직이는 이미지).
- Referer 를 붙인다 — 일부 쇼핑몰은 Referer 없는 요청을 거절한다.
- 같은 번호 파일이 이미 있으면 건너뛴다(이어 받기 · 손으로 넣은 장 보존). 처음부터 다시 받으려면 폴더를 비운다.
- 실패한 주소는 끝에 모아 보여 주고, 하나라도 실패하면 종료 코드 1.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0 Safari/537.36")
EXT_OK = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
CT_EXT = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
          "image/webp": ".webp", "image/gif": ".gif"}
MAX_BYTES = 60 * 1024 * 1024          # 한 장 60MB 넘으면 이미지가 아닐 가능성 — 거절


def read_urls(src: Path) -> list[str]:
    text = src.read_text(encoding="utf-8")
    if src.suffix.lower() == ".json":
        data = json.loads(text)
        imgs = data.get("images", []) if isinstance(data, dict) else data
        urls = [(x.get("src") if isinstance(x, dict) else x) for x in imgs]
    else:
        urls = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    return [u for u in urls if isinstance(u, str) and u.startswith(("http://", "https://"))]


def pick_ext(url: str, content_type: str) -> str:
    ext = Path(urlparse(url).path).suffix.lower()
    if ext in EXT_OK:
        return ".jpg" if ext == ".jpeg" else ext
    return CT_EXT.get(content_type.split(";")[0].strip().lower(), ".jpg")


def fetch(url: str, referer: str, tries: int = 3) -> tuple[bytes, str]:
    last: Exception | None = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": referer,
                                                       "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"})
            with urllib.request.urlopen(req, timeout=30) as r:
                ct = r.headers.get("Content-Type", "")
                body = r.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise ValueError("너무 큼(60MB 초과)")
            if ct and not ct.lower().startswith(("image/", "application/octet-stream", "binary/")):
                raise ValueError(f"이미지가 아님({ct})")
            return body, ct
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (401, 403, 404, 410):     # 다시 해도 같다
                break
        except Exception as e:                     # 끊김·시간초과는 잠깐 쉬고 다시
            last = e
        time.sleep(1.5 * (k + 1))
    raise RuntimeError(f"{type(last).__name__}: {last}")


def main() -> int:
    ap = argparse.ArgumentParser(description="상세 이미지 내려받기")
    ap.add_argument("src", type=Path, help="수집.json 또는 주소목록.txt")
    ap.add_argument("--out", type=Path, required=True, help="저장 폴더(보통 <건 폴더>/원본)")
    ap.add_argument("--referer", default="", help="상세페이지 주소(권장)")
    a = ap.parse_args()

    urls = read_urls(a.src)
    if not urls:
        sys.exit(f"내려받을 주소가 없습니다: {a.src}")
    a.out.mkdir(parents=True, exist_ok=True)
    width = max(2, len(str(len(urls))))
    referer = a.referer or ""
    fails = []
    for i, url in enumerate(urls, 1):
        have = [q for q in a.out.glob(f"{i:0{width}d}.*") if q.suffix.lower() in EXT_OK]
        if have:                                   # 이어 받기 · 사람이 손으로 넣은 장은 건드리지 않는다
            print(f"  [{i}/{len(urls)}] {have[0].name} 이미 있음 — 건너뜀")
            continue
        try:
            body, ct = fetch(url, referer)
        except Exception as e:
            fails.append((i, url, str(e)))
            print(f"  [{i}/{len(urls)}] 실패 — {e}", file=sys.stderr)
            continue
        name = f"{i:0{width}d}{pick_ext(url, ct)}"
        (a.out / name).write_bytes(body)
        print(f"  [{i}/{len(urls)}] {name} {len(body) // 1024}KB")
        time.sleep(0.3)                            # 상대 서버에 예의
    ok = len(urls) - len(fails)
    print(f"완료: {ok}/{len(urls)}장 → {a.out}")
    if fails:
        print("실패한 주소(번호가 비어 있으면 순서가 빠진 것 — 사장님께 알릴 것):")
        for i, url, err in fails:
            print(f"  {i:0{width}d}  {url}  ({err})")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
