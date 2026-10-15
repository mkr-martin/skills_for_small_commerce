# 스몰 커머스 스킬 묶음 — 공통 규칙 (모든 스킬이 따른다)

이 파일이 묶음 전체 규칙의 **유일한 원본**이다. 각 스킬 `SKILL.md` 는 이 규칙을 다시 적지 않고 맨 위 한 줄(`[루트 CLAUDE.md](../../../CLAUDE.md)`)로 가리킨다. 한 가지 사실은 한 곳에만 — 나머지는 상대경로로 가리킨다.

## 0. 첫 대화 안내 (처음 온 사장님)

트리거: "이 프로젝트에 대해 설명해줘" · "뭐 할 수 있어?" · "처음인데" · "설치 도와줘" · "이 스킬 설치 도와줘" 류. **한 번에 한 단계, 사장님 답을 기다린다.**

1. **세 줄 소개** — 맥 · 클로드 코드 · 크롬 기준 / 커다란 에이전트 대신 설치가 쉽고 효과가 큰 일만 골라 만든 스킬 묶음 / DB·서버 없이 결과는 이 폴더의 `output/` 에 파일로.
2. **스킬 표** — 정본은 README §2 표(여기 다시 적지 않는다). 그 표를 읽어 번호 · 이름 · 한 줄 결과물 · 필요한 것(키 여부)으로 보여 주고, 묶음을 밝힌다: 0 = 바탕(내 크롬) · 1·2 = 배우는 스킬 · 3·4 = 운영하는 스킬(읽기만).
3. **"어느 걸 먼저 해 볼까요? 번호로 답해 주세요."** 하고 멈춘다.
4. 고르면 그 스킬 `사용법.md` 「4. 설치법」을 번호 순서로 하나씩 — 각 단계 전에 `python3 shared/doctor.py <스킬>` 로 상태를 보고 **❌ 인 것만** 안내한다(✅ 는 "이미 됨" 한 줄). 키는 `python3 shared/setup_keys.py --only <채널>`(채팅 금지 — §4) · 카페24 로그인은 `python3 shared/channels/cafe24.py login` · `브랜드_SSOT.md` 는 선택이라고 말하고 원하면 대화로 같이 채운다. 한 단계를 끝내면 doctor 를 다시 돌려 ✅ 로 바뀐 것을 확인한 뒤 다음으로. doctor 가 "No developer tools" 로 실패하면 맥이 띄운 개발자 도구 설치 창을 끝내고 다시 실행한다.
5. 다 되면 그 스킬 첫 실행 예시 한 줄(사용법.md 「실행 한 줄」)을 제안한다.

## 1. 일 시작 전에

1. **`브랜드_SSOT.md` 가 채워져 있으면 먼저 읽는다.** 이 파일은 레포에 늘 있고 처음엔 빈 템플릿이다 — 채우는 건 선택이고, 아직 비어 있어도(템플릿 그대로) 모든 스킬이 작동한다. 채워졌는지는 파일 존재가 아니라 `shared/store_profile.py` 의 `is_filled()`(터미널: `python3 shared/store_profile.py`)로 판단한다. 가게 사실은 여기 적힌 것만 근거로 쓰고 지어내지 않는다. 가게 맞춤 칸(① 시사점의 오늘 고칠 것 · ② 우리 가게 훅 후보)은 비어 있으면 "브랜드_SSOT.md 가 비어 있어 일반 제안" 이라고 밝히고 일반 제안으로 채운다.
2. 사장님은 개발자가 아니다. 쉬운 한국어로, 다음에 할 일 한 줄을 먼저 말한다.
3. 결과를 "됐다"고 말하기 전에 실제로 확인한다(파일이 생겼나 · 표에 한 줄 붙었나 · 화면에 반영됐나). 확인 못 한 것은 "확인 못 함"이라고 쓴다.

## 2. 폴더 지도

```
./
├── CLAUDE.md            ← 이 파일(공통 규칙)
├── README.md            사람용 안내(스킬 표 §2 · 준비물 · 설치(ZIP)·업데이트 §4 · 키 발급·IP 등록 §5 · 결과물 §7)
├── LICENSE              MIT
├── 브랜드_SSOT.md           가게 정보 — 빈 템플릿으로 시작 · 채우기는 선택 · 브랜드_SSOT_예시.md = 알타핏 작성 예
├── .env                 API 키(setup_keys.py 가 창으로 받아 씀 · 올라가지 않음) · 키 이름 목록 원본 = .env.example
├── cafe24.token.json    카페24 로그인 토큰(login 이 만들고 자동 연장 · 올라가지 않음)
├── .mcp.json            크롬 연결(반자동크롤러)
├── .gitignore           비밀값 · output/ · 맥·파이썬 찌꺼기를 막는다
├── output/              결과물 전부(스킬이 처음 실행될 때 생김 · 올라가지 않음) — 아래 「결과물 폴더」
├── shared/              공통 부품(표준 라이브러리만 · 네이버만 bcrypt)
│   ├── paths.py         repo_root() · output_dir() — 결과물 위치는 여기 한 곳
│   ├── env.py           get(name, required=False) — 루트 .env 읽기
│   ├── setup_keys.py    "키 넣어줘" — 키마다 맥 입력 창 → .env (값 출력 0)
│   ├── doctor.py        스킬별 준비 상태 ✅/❌ — 점검 항목 표(SKILLS)는 여기 한 곳 · 번호 = 사용법.md 설치법 번호
│   ├── dialog.py        맥 기본 입력 창(osascript) — setup_keys · 카페24 login 이 쓴다
│   ├── store_profile.py is_filled() · read() · low_stock() · color_aliases() — 브랜드_SSOT.md(선택) 읽기
│   ├── ledger.py        append(원장경로, row) · read() — 원장 한 줄 추가·읽기 (터미널: python3 shared/ledger.py)
│   ├── channels/        판매채널 API 인증·조회(네이버·쿠팡·카페24) — ③④ 가 같이 쓴다 · 쓰기 API 없음 · 오류 문장의 키 값 가림 · 403 IP 안내
│   │   └── tests/       python3 -m unittest discover -s shared/channels/tests -t .
│   └── tests/           python3 -m unittest discover -s shared/tests -t .
├── dashboard/           make_dashboard.py(+ 규격 README.md) — 원장들 → output/dashboard.html (탭: 상세페이지 · 레퍼런스 · 문의(보기 전용))
└── .claude/skills/      ⓪ = 바탕 · ①② = 배우는 스킬(남의 콘텐츠 분석) · ③④ = 운영하는 스킬(내 가게 데이터 · 읽기만)
    ├── semi-auto-crawler/  ⓪ 반자동크롤러 — 내 크롬으로 화면 읽기(다른 스킬의 바탕 · 키 없음)
    ├── detail-page/        ① 상세페이지 분석 — 전사.md + 시사점.md (키 없음)
    ├── reels-reference/    ② 릴스 레퍼런스 — 전사.md + 분석.md (Gemini 키)
    ├── inquiry-inbox/      ③ 문의 모으기 — 미답변 문의 → 문의함.csv (채널 API 키 · 모으기만)
    └── shelf-check/        ④ 매대 점검 — 오버셀·공실·저재고·가격 경보 (채널 API 키 · 읽기만 · 없으면 csv)
```

스킬 폴더 안: `SKILL.md`(클로드용 절차) · `사용법.md`(사람용 5절) · `scripts/` · `tests/`(있으면 · `python3 -m unittest discover -s .claude/skills/<스킬>/tests`) · `requirements.txt`(외부 패키지가 있을 때만). 스킬에 따라 더 있는 것: `prompts/`(①) · `패턴집.md`·`tag_axes.json`(②) · `완성하기.md`(③) · `templates/`(④) · `guard.py`·`policy.json`·`references/`(⓪).

**결과물 폴더 = `output/` 하나** — 스킬이 만드는 것과 사장님 가게 데이터는 전부 여기(`.gitignore` 의 `/output/` 한 줄로 올라가지 않음 · 업데이트 때 이 폴더만 새 폴더로 옮긴다). 위치는 `shared/paths.py` 의 `output_dir()` 한 곳에서만 정한다 — 스크립트는 결과물 경로를 `output_dir("매대", …)` 로만 만든다(레포 맨 위나 지금 터미널 위치에 직접 잇지 않는다 — 어느 폴더에서 실행해도 같은 곳에 쓴다).

```
output/
├── dashboard.html       대시보드(make_dashboard.py 가 매번 새로 씀)
├── 수집/                 ⓪ 화면에서 읽어 정리한 표 <yyyymmdd>_<이름>.csv
├── 상세페이지/           ① 원장.md + 건 폴더 <yyyymmdd>_<가게>/
├── 레퍼런스/             ② 원장.md + 건 폴더 <yyyymmdd>_<코드>/
├── 문의/                 ③ 문의함.csv
└── 매대/                 ④ 재고표.csv(사장님이 채움) · 매핑표.csv · <yyyymmdd>/매대표.csv · 결과.csv
```

파일 이름 규칙: 폴더(스킬 폴더 · `shared/` · `dashboard/` · `output/`)와 코드 = 영문(ASCII) · 문서와 결과물(`output/` 안) = 한글. 예외는 도구가 정한 이름(README.md · CLAUDE.md · SKILL.md · LICENSE · requirements.txt)과 반자동크롤러 `references/` 두 장.

## 3. 원장 규칙 (DB 없음)

- 원장 = 결과물 폴더(`output/<탭>/`)의 `원장.md` — **마크다운 표 한 장**, 한 줄 = 한 건.
- **맨 아래 한 줄 추가만** 한다. 🛑 **전체 재작성·정렬·기존 줄 수정 금지**(사장님이 손으로 고친 줄이 사라진다). 고쳐야 하면 사장님께 말하고 사장님이 고친다.
- 열은 고정이다. 새 열이 필요하면 스킬 문서를 고치는 일이지, 원장 한 줄에 끼워 넣을 일이 아니다.
- 스크립트는 `shared/ledger.py` 의 `append()` 만 쓴다(헤더 생성 · 열 순서 · `|` 이스케이프를 대신 처리). 세션에서 붙일 때도 같은 함수를 터미널로 — `python3 shared/ledger.py <원장.md> '<한 줄 JSON>'`.
- 사장님이 엑셀로 채우는 **입력**만 csv(UTF-8 BOM). 산출물 표도 csv 면 UTF-8 BOM.

## 4. 안전 규칙

- 🛑 **`.env` 는 읽거나 출력하지 않는다 · 키는 채팅으로 받지 않는다** — 사장님이 "키 넣어줘" 하면 `python3 shared/setup_keys.py`(한 채널만 `--only naver` 등)를 실행한다(입력은 사장님 화면의 창에서). 사장님이 채팅에 키를 붙여넣으면 쓰지 말고 "키 넣어줘"를 권한다.
- "카페24 로그인" 이면 `python3 shared/channels/cafe24.py login` 을 실행한다(브라우저 동의 → 돌아온 주소를 창에 붙여넣기 — 기다릴 수 있게 타임아웃 넉넉히). 키 값·주소·코드는 채팅·문서·원장·로그 어디에도 적지 않는다(키 이름만).
- 🛑 **③④ 에는 쓰기 코드가 없다**(답변 보내기 · 옵션 열고 닫기 · 재고·가격 바꾸기). API 로 가능하지만 위험해서 재료만 둔다 — ③ `.claude/skills/inquiry-inbox/완성하기.md` · ④ `.claude/skills/shelf-check/사용법.md` 「참고 — 옵션 열고 닫기」. 쓰기 API 를 부르는 코드를 즉석에서 쓰지 않는다(임시 스크립트·curl 포함). 사장님이 직접 만들자고 하면 **두 번 확인 게이트부터** 만든다 — (1) 대화에서 바뀔 내용 전문을 보여 주고 "할까요?" 확인 (2) 실행 명령은 자동 허용 목록에 넣지 않아 클로드 코드 권한 창이 한 번 더 묻는다. 한 번에 한 묶음만, 결과를 다시 읽어 보고한다.
- 결제 · 삭제 · 가격·재고·쿠폰 변경은 스킬이 하지 않는다 — 사장님 손으로.
- 크롬 화면 작업은 ⓪ 반자동크롤러 규칙(`.claude/skills/semi-auto-crawler/SKILL.md`)을 따른다 — 사이트별 판정은 `guard.py`.
- 고객 개인정보(이름·전화·주소)는 산출물에서 가린다(예: 김*수).

## 5. 스크립트 규칙

- 표준 라이브러리 우선. 외부 패키지가 필요하면 그 스킬의 `requirements.txt` 에 적고 `사용법.md` 설치법에 한 줄.
- 공통 부품은 `shared/` 에서 불러 쓴다 — 같은 기능을 스킬 안에 다시 만들지 않는다. `shared` 를 쓰는 스크립트는 **표준 머리 3줄 하나로만** 불러온다(다른 불러오기 방식 금지 — 어느 폴더에서 실행해도 같은 결과):

  ```python
  ROOT = Path(__file__).resolve().parents[4]   # scripts → <스킬> → skills → .claude → 루트
  sys.path.insert(0, str(ROOT))
  from shared import env, ledger, store_profile
  ```

  숫자는 루트까지의 깊이만 바뀐다 — 스킬 폴더 바로 아래 `parents[3]` · `dashboard/` `parents[1]`. 같은 폴더의 다른 스크립트(`from common import …`)는 이 3줄 **뒤에** 불러온다. `shared/` 안의 부품을 파일로 직접 실행하게 할 때(`setup_keys.py` · `store_profile.py` · `channels/cafe24.py`)만 같은 두 줄을 `if __name__ == "__main__":` 아래에 둔다(불러 쓸 때는 경로를 건드리지 않게).
- 실행 표기는 하나 — `python3 <레포 맨 위 기준 경로>/<스크립트>.py`(예: `python3 dashboard/make_dashboard.py` · 카페24 첫 로그인 `python3 shared/channels/cafe24.py login`). `python3 -m <모듈>` 표기는 쓰지 않는다(테스트 실행 `python3 -m unittest` · 설치 `python3 -m pip` 만 예외).
- 키는 `env.get("이름", required=True)` 로 — 비었으면 "키 넣어줘" 를 안내하는 친절한 문장으로 멈춘다. 새 키는 `.env.example` 에 한 줄 더하면 `setup_keys.py` 가 저절로 묻는다(키 이름 목록은 거기 한 곳).
- 테스트는 네트워크 없이 가짜 데이터로.

## 6. 각 스킬 사용법 문서

모든 스킬의 `사용법.md` 는 5절 순서가 고정이다: **목적 → 산출물 → 스킬의 작동 방식 → 설치법(준비물 + 실행 한 줄) → 안 될 때.**
