#!/usr/bin/env python3
"""긴 상세 이미지를 세로 1,600px 조각으로 자른다 — 클로드가 한 장씩 읽을 수 있게.

    python3 .claude/skills/detail-page/scripts/slice.py <원본 폴더> --out <조각 폴더>

- 원본 폴더의 이미지를 **파일 이름순**(= 상세페이지 위→아래 순서)으로 읽는다.
- 조각 이름 = `<원본순번 3자리>_<조각순번 2자리>.png` — 이름순이 곧 읽는 순서.
- 위아래 조각은 240px 겹친다(줄이 잘려 글자를 놓치지 않게). 남는 자투리가 너무 짧으면
  따로 자르지 않고 앞 조각에 붙인다(거의 같은 그림을 두 번 읽지 않게).
- 가로가 1,400px 보다 넓으면 가로만 줄인다(세로 글자 크기 유지).
- webp·gif 애니메이션은 첫 장면만 쓰고 `조각목록.txt` 에 "움직이는 이미지" 라고 적는다.
- 끝나면 조각 목록을 `조각목록.txt` 에 남기고 개수를 출력한다.

필요한 것: pillow (`python3 -m pip install -r .claude/skills/detail-page/requirements.txt`)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("pillow 가 없습니다 — python3 -m pip install -r .claude/skills/detail-page/requirements.txt")

Image.MAX_IMAGE_PIXELS = 2_000_000_000          # 세로 수만 px 짜리 상세도 정상 입력이다
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
WARN_STRIPS = 60                       # 이보다 많으면 사람에게 먼저 묻는다(SKILL.md)


def slice_tall(img: Image.Image, strip_h: int, overlap: int) -> list[Image.Image]:
    """겹침 세로 조각. 자투리(< overlap×1.5)는 직전 조각에 흡수한다.

    strip_h 보다 길면 무조건 자른다 — 클로드가 이미지를 읽을 때 긴 변을 줄여서 보므로,
    조각이 길수록 작은 글씨가 뭉개진다. 가장 긴 조각 = strip_h + overlap×1.5 미만.
    """
    w, h = img.size
    if h <= strip_h:
        return [img]
    strips, step, y = [], strip_h - overlap, 0
    while y < h:
        end = min(y + strip_h, h)
        rest = h - end
        if 0 < rest < int(overlap * 1.5):
            end = h
        strips.append(img.crop((0, y, w, end)))
        if end >= h:
            break
        y += step
    return strips


def load(p: Path) -> tuple[Image.Image, int]:
    """→ (RGB 첫 장면, 프레임 수). 프레임 수 > 1 이면 움직이는 이미지."""
    im = Image.open(p)
    frames = int(getattr(im, "n_frames", 1))
    if frames > 1:
        im.seek(0)
    return im.convert("RGB"), frames


def main() -> int:
    ap = argparse.ArgumentParser(description="상세 이미지를 세로 조각으로")
    ap.add_argument("src", type=Path, help="원본 이미지 폴더")
    ap.add_argument("--out", type=Path, required=True, help="조각을 쓸 폴더")
    ap.add_argument("--strip", type=int, default=1600, help="조각 세로 px (기본 1600)")
    ap.add_argument("--overlap", type=int, default=240, help="겹침 px (기본 240, --strip 보다 작게)")
    ap.add_argument("--max-width", type=int, default=1400, help="이보다 넓으면 가로만 축소")
    a = ap.parse_args()

    if a.overlap >= a.strip or a.overlap < 0 or a.strip < 200:
        sys.exit("--overlap 은 0 이상이고 --strip 보다 작아야 하며, --strip 은 200 이상이어야 합니다")
    if not a.src.is_dir():
        sys.exit(f"원본 폴더가 없습니다: {a.src}")
    srcs = sorted(p for p in a.src.iterdir() if p.is_file() and p.suffix.lower() in IMG_EXT)
    if not srcs:
        sys.exit(f"이미지가 없습니다: {a.src}")

    a.out.mkdir(parents=True, exist_ok=True)
    for old in a.out.glob("*.png"):          # 다시 돌릴 때 지난 조각이 섞이지 않게
        old.unlink()

    lines, count = [], 0
    for si, p in enumerate(srcs, 1):
        try:
            img, frames = load(p)
        except Exception as e:                # 깨진 파일 하나 때문에 전체를 멈추지 않는다 — 목록에 남긴다
            lines.append(f"{p.name}\t읽기 실패: {type(e).__name__}")
            print(f"경고: {p.name} 읽기 실패 ({e})", file=sys.stderr)
            continue
        if img.width > a.max_width:
            r = a.max_width / img.width
            img = img.resize((a.max_width, max(1, int(img.height * r))), Image.LANCZOS)
        note = f"\t움직이는 이미지({frames}프레임) — 첫 장면" if frames > 1 else ""
        for ci, s in enumerate(slice_tall(img, a.strip, a.overlap), 1):
            name = f"{si:03d}_{ci:02d}.png"
            s.save(a.out / name, format="PNG")
            lines.append(f"{name}\t← {p.name} ({img.width}x{img.height}){note}")
            count += 1

    (a.out / "조각목록.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"원본 {len(srcs)}장 → 조각 {count}개 · {a.out}")
    if count > WARN_STRIPS:
        print(f"주의: 조각이 {count}개({WARN_STRIPS}개 초과) — 읽기 전에 사장님께 확인받으세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
