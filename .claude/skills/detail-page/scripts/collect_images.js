// 상세 이미지 주소 모으기 — 내 크롬의 상세페이지 탭에서 실행한다(반자동크롤러 스킬).
// 크롬 도구의 "스크립트 실행"(evaluate_script)에 이 함수를 통째로 넣는다.
// 도구가 함수가 아니라 식을 원하면 (async () => { ... })() 처럼 감싸서 넣는다.
//
// 하는 일: 펼치기 버튼 누르기 → 끝까지 스크롤 → 플랫폼 판별 → 상세 영역 찾기 → 군더더기 이미지 빼기
// 돌려주는 것: { url, title, platform, branch, images:[{src,w,h}], warnings:[...], ... }
//   → 이 결과를 그대로 <건 폴더>/수집.json 으로 저장하고 download.py 에 넘긴다.
// 이 코드는 "정답"이 아니라 출발점이다. 처음 보는 사이트에서 warnings 가 나오면
// 사람처럼 대응한다 — ladder(조상 사다리)를 보고 상세 영역 셀렉터를 직접 정해 다시 돌린다.
async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const warnings = [];

  // ① 펼치기 — 네이버는 `상품정보 펼쳐보기`·`상세정보 펼쳐보기` 2개를 다 눌러야 전량.
  //    한 번 누르면 두 번째가 뒤늦게 생기므로 2패스.
  const EXPAND = /펼쳐보기|더보기|상세보기|상세정보|상품\s?설명/;
  const expanded = [];
  for (let pass = 0; pass < 2; pass++) {
    const btns = [...document.querySelectorAll('a,button')].filter(e => {
      const t = (e.textContent || '').trim();
      return t.length < 20 && EXPAND.test(t) && !expanded.includes(t);
    });
    if (!btns.length) break;
    btns.forEach(e => { try { e.click(); } catch (_) {} expanded.push((e.textContent||'').trim()); });
    await sleep(1200);
  }

  // ② 끝까지 스크롤 — lazy load 를 다 깨운 뒤에야 naturalWidth 가 0 이 아니다.
  let lastH = 0;
  for (let i = 0; i < 60; i++) {
    window.scrollBy(0, 1600); await sleep(220);
    const h = document.body.scrollHeight;
    if (window.scrollY + window.innerHeight >= h - 50) { if (h === lastH) break; lastH = h; }
  }
  window.scrollTo(0, 0); await sleep(400);

  // ③ 플랫폼 지문 6종 — 증거를 그대로 남긴다(판정이 틀렸을 때 왜 틀렸나를 묻기 위해).
  const head = document.documentElement.outerHTML.slice(0, 40000);
  const F = {
    se_main: document.querySelectorAll('.se-main-container').length,
    cafe24_xans: document.querySelectorAll('[class*=xans]').length,
    cafe24_EC: typeof window.EC !== 'undefined',
    godo_url: /goods_view\.php\?goodsNo=/.test(location.href),
    godo_js: [...document.querySelectorAll('script[src]')].some(s => /godo|nhn-commerce|\/js\/goods/i.test(s.src)),
    imweb: /imweb/i.test(head),
    coupang_url: /coupang\.com\/vp\/products\//.test(location.href),
    next: /_next\//.test(head), nuxt: /__NUXT__/.test(head), vue: /data-v-[0-9a-f]{6,}/.test(head),
    jquery: typeof window.jQuery !== 'undefined',
  };
  // 아임웹은 `#prod_detail` 이 리뷰를 포함해 **오답** — `.detail_detail_wrap` 이 정답.
  const PLATFORMS = [
    ['네이버 스마트·브랜드스토어', '.se-main-container', F.se_main > 0],
    ['쿠팡', '.product-detail-content', F.coupang_url],
    ['고도몰(NHN커머스)', '#detail', F.godo_url || F.godo_js],
    ['카페24', '#prdDetail', F.cafe24_xans > 0 || F.cafe24_EC],
    ['아임웹', '.detail_detail_wrap', F.imweb],
  ];
  const fw = F.next ? 'Next.js' : F.nuxt ? 'Nuxt' : F.vue ? 'Vue' : F.jquery ? 'jQuery' : '미상';
  let platform = `자체구축(${fw})`, hit = null;
  for (const [name, sel, ok] of PLATFORMS) {
    if (!ok) continue;
    let el = null; try { el = document.querySelector(sel); } catch (_) {}
    const n = el ? [...el.querySelectorAll('img')].filter(i => i.naturalWidth >= 300).length : 0;
    if (el && n >= 3) { platform = name; hit = { sel, el }; break; }
    warnings.push(`지문은 ${name} 인데 ${sel} ${el ? `이미지 ${n}장(<3)` : '없음'} — 무릎으로 넘어감`);
  }

  const OK = i => i.naturalWidth >= 300 && i.naturalHeight >= 200;
  const allImgs = [...document.querySelectorAll('img')].filter(OK);
  const text = (document.body.innerText || '').replace(/\s+/g, ' ').trim();
  if (/비정상적인 접근|Access Denied|잠시 후 다시|captcha/i.test(text.slice(0, 2000)))
    warnings.push('차단 문구 — 사람 크롬인지 확인하라');
  const notLoaded = [...document.querySelectorAll('img')].filter(i => i.naturalWidth === 0).length;
  if (notLoaded) warnings.push(`naturalWidth=0 인 img ${notLoaded}개 — 스크롤이 덜 닿았다`);

  // ④ 3분기 — 세로합과 "최장 1장의 비중"만으로. 장수로 판정하면 틀린다
  //    (5장짜리와 10장짜리가 장수는 2배여도 세로합은 20배 차이 날 수 있다).
  //    경계는 정수 비교로 — 부동소수로 0.7 을 비교하면 70.0% 가 69.99% 로 떨어진다.
  const branch = imgs => {
    const total = imgs.reduce((a, b) => a + (b.h || 0), 0);
    if (total < 8000) return '텍스트형';
    const maxH = imgs.reduce((a, b) => Math.max(a, b.h || 0), 0);
    return maxH * 10 >= total * 7 ? '단일장문형' : '다중이미지형';
  };
  const allH = allImgs.reduce((a, b) => a + b.naturalHeight, 0);
  const base = { url: location.href, title: document.title, platform, fingerprint: F,
                 text_chars: text.length, text_sample: text.slice(0, 160), expanded };
  const EMPTY = { small: 0, aspect1: 0, dup: 0, review: 0 };
  if (allH < 8000) return { ...base, container: null, branch: '텍스트형', images: [],
    total_height_px: allH, ladder: [], removed: EMPTY, strips_est: 0,
    warnings: [...warnings, `텍스트형 — 세로합 ${allH}px < 8,000px. 이미지 전사 말고 페이지 글을 그대로 읽어라`] };

  // ⑤ 사다리 — 지문이 맞았을 때도 **진단용으로 항상** 만든다(지문 선택이 옳았나를 사후에 묻기 위해).
  const seed = allImgs.reduce((a, b) => b.naturalHeight > a.naturalHeight ? b : a);
  const chain = []; for (let p = seed.parentElement; p && p !== document.documentElement; p = p.parentElement) chain.push(p);
  // 이름은 **유일하게 집히는지 DOM 으로 검증**한다. 유일하게 안 집히면 셀렉터가 아니다
  //    (예: `.MuiBox-root.css-1pu394w` → 의미 있는 이름은 MuiBox-root 뿐인데 그건 수백 개에 붙는다).
  const HASHY = /^(css|sc|jsx|emotion)[-_]|[-_][0-9a-f]{6,}$|^[a-z]+-\d+$|\[|^(flex|grid|block|relative|absolute|hidden|w|h|p[xytblr]?|m[xytblr]?|text|bg|border|items|justify|gap|rounded|shadow|twc)([-_].*)?$/i;
  const SEM = new Set(['main','article','section','aside','figure']);
  const nameOf = el => {
    if (el.id && !HASHY.test(el.id)) { const s = `#${CSS.escape(el.id)}`;
      if (document.querySelector(s) === el) return { name: s, rank: 3 }; }
    const cls = typeof el.className === 'string' ? el.className.trim() : '';
    const tk = cls ? cls.split(/\s+/).filter(t => t.length >= 3 && !HASHY.test(t)) : [];
    for (let k = 1; k <= Math.min(tk.length, 2); k++) {
      const s = `.${tk.slice(0, k).map(t => CSS.escape(t)).join('.')}`;
      try { if (document.querySelector(s) === el) return { name: s, rank: 2 }; } catch (_) {}
    }
    const tag = el.tagName.toLowerCase();
    if (SEM.has(tag) && document.querySelector(tag) === el) return { name: tag, rank: 1 };
    return { name: el.id ? `#${el.id}` : (cls ? `.${cls.split(/\s+/).slice(0,2).join('.')}` : tag), rank: 0 };
  };
  const rows = chain.map(el => { const n = nameOf(el);
    return { el, name: n.name, rank: n.rank, img_count: [...el.querySelectorAll('img')].filter(OK).length }; });
  const ladder = rows.map(r => ({ name: r.name, img_count: r.img_count }));

  // ⑥ 런타임 무릎 — **가장 크게 뛰는 지점 아래**를 채택. n<4 인 안쪽 조상은 건너뛴다.
  //    "이미지 최다"(body 142장 vs 실제 22장)도 "커버리지 가중 점수"(#wrap 85장 vs 실제 27장)도
  //       쓰지 않는다 — 둘 다 큰 컨테이너가 항상 이긴다.
  const knee = L => {
    let idx = -1, jump = 1;
    for (let i = 0; i < L.length - 1; i++) {
      if ((L[i].img_count || 0) < 4) continue;
      const r = (L[i+1].img_count || 0) / Math.max(L[i].img_count || 0, 1);
      if (r > jump) { jump = r; idx = i; }
    }
    if (idx < 0) return { index: -1, jump: 1, tie: [] };
    // 동수 조상이 여럿이면(=이미지 집합이 같다) id → 의미 클래스 → 해시·유틸 순으로 이름을 고른다.
    const n = L[idx].img_count, tie = [];
    for (let i = idx; i >= 0 && L[i].img_count === n; i--) tie.unshift(i);
    let pick = idx;
    for (const i of tie) if ((L[i].rank || 0) > (L[pick].rank || 0)) pick = i;
    return { index: pick, jump: +jump.toFixed(2), tie: tie.map(i => L[i].name) };
  };

  let container = null, el = null;
  if (hit) {
    container = hit.sel; el = hit.el;
    let m = 1; try { m = document.querySelectorAll(hit.sel).length; } catch (_) {}
    if (m > 1) warnings.push(`${hit.sel} 가 ${m}개 집힌다 — 첫 번째를 썼다`);
  } else {
    const k = knee(rows);
    if (k.index < 0) {
      // body 로도, 안쪽 조상으로도 폴백하지 않는다 — 1장만 담긴 조상을 고르면 "성공한 작은 수집"처럼
      //    보여서 더 위험하다. 0장 + 사다리 + 큰 경고로 **사람을 부른다**.
      return { ...base, container: null, branch: '미판정', images: [], total_height_px: 0,
        ladder, removed: EMPTY, strips_est: 0, warnings: [...warnings,
          `무릎 미검출 — n≥4 이면서 뛰는 지점이 없다. 사다리를 보고 셀렉터를 손으로 넣어라: ${ladder.map(r=>`${r.name}:${r.img_count}`).join(' → ')}`] };
    } else {
      const row = rows[k.index]; el = row.el;
      if (row.rank >= 1) container = row.name;
      // 해시·유틸 클래스는 배포마다 바뀐다 — container 로 기록하지 않고 사다리를 남긴다.
      else warnings.push(`런타임 무릎 — 안정 셀렉터 없음 (후보 ${row.name}, 점프 ×${k.jump}, 사다리 ${ladder.map(r=>`${r.name}:${r.img_count}`).join(' → ')})`);
      if (k.tie.length > 1) warnings.push(`동수 조상 ${k.tie.length}개 — ${k.tie.join(' / ')} 중 이름으로 골랐다`);
    }
  }

  // ⑦ 오염 제거 3종 — 순서대로 걸러 **서로 겹치지 않게** 센다.
  //    비교 키만 쿼리를 떼고 src 는 원문 그대로 — `_next/image?url=…` 는 쿼리가 본체다.
  const picked = [...el.querySelectorAll('img')]
    .map(i => ({ src: i.currentSrc || i.src || '', w: i.naturalWidth, h: i.naturalHeight }))
    .filter(x => /^https?:/.test(x.src));
  const removed = { small: 0, aspect1: 0, dup: 0, review: 0 }, nearSq = [];
  let keep = picked.filter(x => (x.w >= 300 && x.h >= 200) || (removed.small++, false));
  keep = keep.filter(x => {                                        // 종횡비 정확히 1.00 = 추천 썸네일
    if (x.w > 0 && x.h === x.w) { removed.aspect1++; return false; }
    if (x.w > 0 && Math.abs(x.h / x.w - 1) <= 0.02) nearSq.push(`${x.w}x${x.h}`);
    return true;
  });
  const seen = new Set();
  keep = keep.filter(x => {                                        // URL 중복 = 캐러셀 반복 노출
    const key = x.src.split('?')[0];
    if (seen.has(key)) { removed.dup++; return false; } seen.add(key); return true;
  });
  keep = keep.filter(x => !/review|PRODUCTREVIEW/i.test(x.src) || (removed.review++, false));

  if (nearSq.length) warnings.push(`정사각 ±2% 인 이미지 ${nearSq.length}장 — 규칙은 "정확히 1.00"뿐이라 남겼다: ${nearSq.slice(0,6).join(', ')}`);
  if (keep.some(x => x.src.includes('?'))) warnings.push('쿼리가 붙은 src 가 있다(_next/image 등) — 쿼리를 떼면 못 받는다');
  if (!keep.length) warnings.push('오염 제거 후 0장 — 컨테이너가 틀렸다');
  const totalH = keep.reduce((a, b) => a + b.h, 0);
  // 전사 비용의 **상한** = Σ ceil(장별 세로 / 1360). 총합을 한 번에 나누면 29% 과소,
  //    이 식은 20% 안팎 과대 — 정확값은 slice.py 결과뿐. 여기선 상한으로 족하다.
  const strips = keep.reduce((a, b) => a + Math.ceil(b.h / 1360), 0);
  if (strips > 60) warnings.push(`예상 ${strips}스트립(상한) — 60 초과. 전사 전에 사람에게 확인받아라`);

  return { ...base, container, branch: branch(keep), images: keep,
           total_height_px: totalH, ladder, removed, strips_est: strips, warnings };
}
