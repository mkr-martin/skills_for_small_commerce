# 반자동크롤러 — 구동 규약 상세 (SKILL.md §2.5 에서 분리)

## 세 가지 함정과 정답

| 함정 | 진짜 원인 | 정답 |
|---|---|---|
| 클릭이 `did not become interactive`로 죽는다 | Puppeteer Locator의 visible/viewport 게이트 ↔ 기하정보 없는 a11y 트리의 **불일치** | `evaluate_script`로 **네이티브 `el.click()`** |
| uid가 안 먹는다 | ~~검색하면 재할당~~ **아니다** — uid는 `loaderId_backendNodeId`로 안정적. React 리렌더가 **DOM 노드를 파괴·재생성**한 것 | 스냅샷 재촬영 말고 **라벨 텍스트로 다시 찾아** 네이티브 클릭 |
| 스냅샷 1회가 수천 토큰 | 사이드바·푸터까지 전부 온다. **스코프 옵션은 존재하지 않는다**(upstream 이슈 open) | ⓐ `filePath`로 파일 저장(응답 1줄) ⓑ **스냅샷을 아예 안 뜨고** `evaluate_script`로 필요한 것만 |

## 표준 패턴 — 라벨로 찾고 · 네이티브로 누르고 · 같은 콜에서 검증

스냅샷 → uid 클릭 → 재스냅샷을 **왕복마다** 반복하지 말 것. 한 번에 끝낸다:

```js
// evaluate_script — 찾기·클릭·검증을 1왕복에
const rows = [...document.querySelectorAll('label, [role="checkbox"], button')];
const hit  = rows.filter(el => /Workers R2 Storage/i.test(el.textContent));
hit.forEach(el => el.click());
return hit.map(el => ({ text: el.textContent.trim().slice(0, 40),
                        checked: el.getAttribute('aria-checked') }));
```

접힌·가상화된 섹션의 체크박스 여러 개도 **1왕복·수백 토큰**이면 된다.

## 비전이 필요한 자리 (여기서만)

canvas 차트 · 이미지 전용 UI · ARIA 라벨이 없는 커스텀 위젯 · "디자인이 깨졌나" 시각 검증. (canvas 페이지는 스냅샷이 **빈 트리**로 나온다 — 그게 신호다)
그마저 **1차 수단은 `evaluate_script`로 원본 데이터를 직접 꺼내는 것**이고, 픽셀뿐일 때만 스크린샷을 본다.

## 🕳️ 화면이 비어 보일 때 — 시행착오 목록 (실측 박제)

**증상: `body.innerText`가 헤더·푸터뿐(수백 자)인데 사람 눈에는 목록이 멀쩡히 보인다.** "봇 차단"으로 오진하기 쉽다. 아래 순서로 확인한다.

| # | 원인 | 확인법 | 해결 |
|---|---|---|---|
| 1 | **Shadow DOM** (가장 흔함·오진 1순위) | `[...document.querySelectorAll('*')].filter(e=>e.shadowRoot).length` | `shadowRoot`를 **직접 순회**. `open` 모드면 `host.shadowRoot.textContent`로 다 읽힌다. ★ **`textContent`엔 `<style>` CSS가 통째로 섞이므로**, 텍스트 노드만 재귀 수집(STYLE/SCRIPT/LINK 제외)해야 파싱 가능한 배열이 나온다 |
| 2 | **JS 렌더 지연** | 5~10초 더 기다렸다 재확인 | `setTimeout` 후 재읽기. 이걸 안 하고 "차단"이라 결론내면 오진 |
| 3 | **iframe 내부** | `document.querySelectorAll('iframe')` + `contentDocument` 접근 가능 여부 | 같은 오리진이면 `f.contentDocument`로 진입 |
| 4 | 진짜 봇 차단 | 위 3개가 전부 아님 + WebFetch도 403 | 사람이 직접 조작 |

**실제로 있었던 오진**: 어느 쇼핑몰 앱 목록 페이지에서 `body.innerText` 487자 · `WebFetch` 403 → **"봇 차단"으로 잘못 결론짓고 수집 포기를 보고**했다. 실제로는 **Shadow DOM(open) 안에 8만 자 본문**이 그대로 있었다(사람이 "화면엔 다 보이는데?"라고 짚어 다시 조사). `shadowRoot` 순회로 **85개 전량 수집 성공**. → **`innerText`가 비었다는 것은 차단의 증거가 아니다. 위 표를 1→4 순서로 다 확인한 뒤에만 "차단"이라 말한다.**

**목록 수집 일반 요령(같이 얻은 것)**
- **정렬 파라미터를 먼저 찾는다** — `select` option의 `value`(카페24 `order=SALES_DESC`, 고도몰 `sortCriterion=SALE_COUNT`). **판매량순이 곧 수요 순위**라 분석 가치가 가장 크다.
- **숨긴 iframe 순차 로드**로 한 번의 `evaluate_script`에서 여러 페이지를 돈다(페이지 이동은 스크립트를 끊는다). `position:fixed;left:-9999px` + `onload` 대기 + 렌더 여유 2초.
- **결과는 `filePath`로 파일에 떨군다** — 수백 행을 세션 컨텍스트에 싣지 않는다.
- SSR HTML(`fetch`)에 목록이 없어도 렌더 후 DOM엔 있다. 둘을 **혼동하지 말 것**(fetch 3개 vs 렌더 23개를 겪었다).

## 쓰기 작업 흐름 예시 (SKILL.md §3)
```
사람: 클라우드플레어에서 이미지 저장 공간(R2 버킷) 하나 만들어줘
클로드: (`list_pages`) Cloudflare 대시보드 탭에 붙었습니다. 계정 A입니다.
        정책: 🟢read,navigate,fill 🟡irreversible 🔴secret
        (1) R2 진입 (2) Create bucket (3) 이름 입력 (4) 위치 확인 까지 제가 하고,
        (5) 생성(되돌리기 어려움)은 미리보기 보여드린 뒤 확정받고 누르겠습니다.
클로드: (1)~(4) 완료. 이름 haru-socks-images / 위치 APAC / 되돌리기 = 빈 버킷 삭제.
        (5) 눌러도 될까요?
사람: ㅇㅋ
클로드: 생성했습니다. 버킷 목록에 haru-socks-images 확인됩니다.
```
