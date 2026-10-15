"""키 넣기 — 키마다 맥 기본 입력 창을 띄워 받아 레포 루트 `.env` 에 쓴다. 사장님은 `.env` 를 몰라도 된다.

    python3 shared/setup_keys.py                     # 모든 채널(창으로 묻는 키 전부)
    python3 shared/setup_keys.py --only naver        # 한 채널만 (gemini · naver · coupang · cafe24 · 쉼표로 여러 개)
    python3 shared/setup_keys.py --key CAFE24_INQUIRY_BOARDS   # 키 하나만(선택 키도 가능)

- 키 이름 목록은 `.env.example` 에서 읽는다(두 벌 금지). 주석에 "(선택)" 이 붙은 키는 --key 로만 묻는다.
- 이미 값이 있는 키는 "덮어쓸까요?" 창을 먼저 띄운다. 건너뛰기(취소)를 누르면 그 키는 건드리지 않는다.
- `.env` 의 다른 줄(주석·다른 키)은 그대로 둔다. 파일이 없으면 `.env.example` 을 틀로 만든다. 권한 600.
- 🛑 값은 화면·로그·표준출력 어디에도 찍지 않는다 — 찍는 것은 키 이름과 채널별 ✅/❌ 뿐.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if __name__ == "__main__":   # 파일로 직접 실행 — 어느 폴더에서든 shared 를 찾게(루트 CLAUDE.md §5 표준 머리)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared import dialog  # noqa: E402
from shared.env import _parse_line, load  # noqa: E402
from shared.paths import repo_root  # noqa: E402

# 채널 = 키 이름 앞머리. 순서 = 창이 뜨는 순서.
GROUPS = {"gemini": ("GEMINI_", "Gemini"), "naver": ("NAVER_", "네이버"),
          "coupang": ("COUPANG_", "쿠팡"), "cafe24": ("CAFE24_", "카페24")}
HIDDEN_WORDS = ("SECRET", "ACCESS_KEY", "API_KEY")      # 이 글자가 든 키는 입력 글자를 가린다
HELP = "발급 방법: README '키 발급' 절"
CAFE24_NEXT = "카페24는 로그인이 한 번 필요합니다 — 클로드에게 '카페24 로그인' 이라고 말하세요."


def example_keys(example: Path) -> list[dict]:
    """`.env.example` → [{name, group, optional, hint}, …] (파일 순서). hint = 바로 위 주석 묶음의 마지막 줄."""
    out, comments = [], []
    for raw in example.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            comments = []
            continue
        if line.startswith("#"):
            comments.append(line.lstrip("#").strip().lstrip("─").strip())
            continue
        kv = _parse_line(line)
        if not kv:
            continue
        name = kv[0]
        group = next((g for g, (prefix, _) in GROUPS.items() if name.startswith(prefix)), None)
        hint = comments[-1] if comments else ""
        out.append({"name": name, "group": group, "optional": "(선택)" in hint, "hint": hint})
    return out


def _fmt(value: str) -> str:
    """`.env` 한 줄 값 — shared/env.py 가 그대로 읽어 내는 모양으로."""
    if any(c in value for c in " \t#\"'"):
        q = "'" if '"' in value else '"'
        return f"{q}{value}{q}"
    return value


def write_env(env_path: Path, example: Path, updates: dict[str, str]) -> None:
    """updates 의 키만 바꾸거나 덧붙인다. 다른 줄은 그대로. 임시 파일 → 바꿔치기 · 권한 600."""
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    else:
        lines = example.read_text(encoding="utf-8").splitlines()
    done = set()
    for i, raw in enumerate(lines):
        kv = _parse_line(raw)
        if kv and kv[0] in updates and kv[0] not in done:
            lines[i] = f"{kv[0]}={_fmt(updates[kv[0]])}"
            done.add(kv[0])
    lines += [f"{k}={_fmt(v)}" for k, v in updates.items() if k not in done]
    tmp = env_path.with_name(env_path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, env_path)


def status(keys: list[dict], values: dict[str, str], groups: list[str]) -> list[str]:
    """채널별 한 줄 — '네이버 ✅' · '쿠팡 ❌ 없음' · '카페24 ⚠️ 일부 빔(키 이름…)'. 값은 담지 않는다."""
    rows = []
    for g in groups:
        need = [k["name"] for k in keys if k["group"] == g and not k["optional"]]
        have = [n for n in need if values.get(n)]
        label = GROUPS[g][1]
        if need and len(have) == len(need):
            rows.append(f"{label} ✅")
        elif not have:
            rows.append(f"{label} ❌ 없음")
        else:
            rows.append(f"{label} ⚠️ 일부 빔({', '.join(n for n in need if n not in have)})")
    return rows


def _ask_one(k: dict, current: str | None, ui) -> str | None:
    """키 하나 — 새 값 또는 None(건드리지 않음)."""
    name = k["name"]
    if current and not ui.confirm(f"{name} 는 이미 들어 있습니다.\n새 값으로 덮어쓸까요?",
                                  yes="덮어쓰기", no="그대로 두기"):
        return None
    label = GROUPS[k["group"]][1] if k["group"] else "키"
    msg = (f"[{label}] {name}\n{k['hint']}\n\n값을 붙여넣고 확인을 누르세요(모르면 건너뛰기).\n{HELP}")
    hidden = any(w in name for w in HIDDEN_WORDS)
    value = ui.ask(msg, hidden=hidden)
    if value is None:
        return None
    value = value.strip()
    if not value or "\n" in value or "\r" in value:
        return None
    return value


def _parse_only(raw: list[str] | None) -> list[str]:
    if not raw:
        return list(GROUPS)
    picked = [x.strip().lower() for r in raw for x in r.split(",") if x.strip()]
    bad = [x for x in picked if x not in GROUPS]
    if bad:
        raise SystemExit(f"--only 에는 {', '.join(GROUPS)} 중에서 고르세요(받은 것: {', '.join(bad)})")
    return [g for g in GROUPS if g in picked]


def main(argv: list[str] | None = None, ui=dialog, env_path: Path | None = None,
         example: Path | None = None) -> int:
    ap = argparse.ArgumentParser(description="키를 맥 입력 창으로 받아 .env 에 쓴다(값은 출력하지 않음)")
    ap.add_argument("--only", action="append", help="채널만: gemini · naver · coupang · cafe24 (쉼표로 여러 개)")
    ap.add_argument("--key", help="키 하나만(.env.example 에 있는 이름)")
    args = ap.parse_args(argv)
    env_path = env_path or (repo_root() / ".env")
    example = example or (repo_root() / ".env.example")

    keys = example_keys(example)
    if args.key:
        targets = [k for k in keys if k["name"] == args.key]
        if not targets:
            raise SystemExit(f"{args.key} 는 .env.example 에 없는 키 이름입니다.")
        groups = [g for g in GROUPS if g == targets[0]["group"]]
    else:
        groups = _parse_only(args.only)
        targets = [k for k in keys if k["group"] in groups and not k["optional"]]

    current = load(env_path)
    updates: dict[str, str] = {}
    for k in targets:
        value = _ask_one(k, current.get(k["name"]), ui)
        if value is not None:
            updates[k["name"]] = value
            print(f"{k['name']}: 받음")          # 값은 찍지 않는다
        else:
            print(f"{k['name']}: 건너뜀")
    if updates:
        write_env(env_path, example, updates)

    rows = status(keys, {**current, **updates}, groups)
    cafe24_new = any(n.startswith("CAFE24_") and n != "CAFE24_INQUIRY_BOARDS" for n in updates)
    if cafe24_new and any(r.startswith("카페24 ✅") for r in rows):
        rows.append("")
        rows.append(CAFE24_NEXT)
    text = "\n".join(rows)
    print(text)
    ui.show(("저장했습니다(.env).\n\n" if updates else "바뀐 것 없음.\n\n") + text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
