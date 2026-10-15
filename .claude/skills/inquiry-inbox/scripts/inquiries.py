"""채널별 '미답변 문의 읽기' — 인증·요청은 루트 shared/channels 가 한다. 읽기만 한다(답변 보내기 코드는 없음).

공식 문서에 적힌 엔드포인트·필드만 쓴다. 문서로 확인 못 한 부분은 '미확인 — 실측 필요' 주석.

문의 id = '채널:종류:번호[:보조번호]'. 나중에 답변 보내기를 직접 만들 때 필요한 번호까지 id 에 담아 둔다
(완성하기.md). 앞 글자 덕에 엑셀이 긴 숫자를 지수로 바꾸는 사고도 막힌다.
"""
from __future__ import annotations

import html
import re
import sys
from datetime import timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]   # scripts → inquiry-inbox → skills → .claude → 루트 (루트 CLAUDE.md §5 표준 머리)
sys.path.insert(0, str(ROOT))
from shared import env  # noqa: E402
from shared.channels import ChannelError, cafe24, coupang, naver  # noqa: E402

from common import ST_NEW, mask_name, now_kst, to_kst_text  # noqa: E402  같은 폴더

LABEL = {"naver": "네이버", "coupang": "쿠팡", "cafe24": "카페24"}
MODULE = {"naver": naver, "coupang": coupang, "cafe24": cafe24}
CAFE24_BOARD_KEY = "CAFE24_INQUIRY_BOARDS"   # .env 키 — 문의를 모을 카페24 게시판 번호(쉼표)


def _row(row_id, channel, kind, received, product, customer, question) -> dict:
    return {"id": row_id, "채널": channel, "종류": kind, "접수일": received,
            "상품": product or "", "고객": customer or "", "문의 원문": (question or "").strip(),
            "답변": "", "상태": ST_NEW}


# ====================================================================== 네이버
# 문서: 고객 문의 조회(037 · GET /v1/pay-user/inquiries) · 상품 문의 목록 조회(040 · GET /v1/contents/qnas)
def naver_fetch(days: int) -> list:
    rows = []
    end = now_kst()
    start = end - timedelta(days=min(days, 365))     # 고객 문의 최대 365일(문서 오류코드 4003)
    page = 1
    while True:
        data = naver.request("GET", "/v1/pay-user/inquiries", {
            "page": page, "size": 200, "answered": "false",
            "startSearchDate": start.strftime("%Y-%m-%d"), "endSearchDate": end.strftime("%Y-%m-%d")})
        rows += naver_parse_customer(data)
        if page >= int(data.get("totalPages") or 0) or data.get("last") is True:
            break
        page += 1
    utc = timezone.utc
    page = 1
    while True:
        data = naver.request("GET", "/v1/contents/qnas", {
            "page": page, "size": 100, "answered": "false",
            "fromDate": start.astimezone(utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "toDate": end.astimezone(utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")})
        rows += naver_parse_qna(data)
        if page >= int(data.get("totalPages") or 0) or data.get("last") is True:
            break
        page += 1
    return rows


def naver_parse_customer(data: dict) -> list:
    out = []
    for it in data.get("content") or []:
        if it.get("answered") is True:
            continue
        product = it.get("productName") or ""
        if it.get("productOrderOption"):
            product = f"{product} ({it['productOrderOption']})"
        head = f"[{it['category']}] " if it.get("category") else ""
        question = f"{head}{it.get('title') or ''}\n{it.get('inquiryContent') or ''}"
        out.append(_row(f"naver:inquiry:{it['inquiryNo']}", "네이버", "고객문의",
                        to_kst_text(it.get("inquiryRegistrationDateTime")),
                        product, mask_name(it.get("customerName")), question))
    return out


def naver_parse_qna(data: dict) -> list:
    out = []
    for it in data.get("contents") or []:
        if it.get("answered") is True:
            continue
        out.append(_row(f"naver:qna:{it['questionId']}", "네이버", "상품문의",
                        to_kst_text(it.get("createDate")), it.get("productName") or "",
                        mask_name(it.get("maskedWriterId")), it.get("question") or ""))
    return out


# ====================================================================== 쿠팡
# 문서(CS APIs): 상품별 고객문의 조회(360033400754 · GET v5 …/onlineInquiries)
#                쿠팡 고객센터 문의조회(360033645354 · GET v5 …/callCenterInquiries)
_CP = "/v2/providers/openapi/apis/api"
COUPANG_WINDOW = 7     # 두 조회 API 모두 조회 기간 최대 7일


def _coupang_ok(data: dict) -> dict:
    code = str(data.get("code", "200"))
    if code != "200":
        raise ChannelError(f"쿠팡 응답 code={code} — {data.get('message', '')}")
    return data


def _coupang_windows(days: int):
    end = now_kst().date()
    s = end - timedelta(days=days)
    while s <= end:
        e = min(s + timedelta(days=COUPANG_WINDOW - 1), end)
        yield s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d")
        s = e + timedelta(days=1)


def _coupang_pages(path: str, params: dict):
    page = 1
    while True:
        body = _coupang_ok(coupang.request("GET", path, {**params, "pageNum": page})).get("data") or {}
        yield body
        if page >= int((body.get("pagination") or {}).get("totalPages") or 0):
            break
        page += 1


def coupang_fetch(days: int) -> list:
    vid = coupang.vendor_id()
    rows = []
    for s, e in _coupang_windows(days):
        for body in _coupang_pages(f"{_CP}/v5/vendors/{vid}/onlineInquiries", {
                "vendorId": vid, "answeredType": "NOANSWER",
                "inquiryStartAt": s, "inquiryEndAt": e, "pageSize": 50}):
            rows += coupang_parse_online(body)
        for body in _coupang_pages(f"{_CP}/v5/vendors/{vid}/callCenterInquiries", {
                "vendorId": vid, "partnerCounselingStatus": "NO_ANSWER",
                "inquiryStartAt": s, "inquiryEndAt": e, "pageSize": 30}):
            rows += coupang_parse_callcenter(body)
    return rows


def coupang_parse_online(body: dict) -> list:
    out = []
    for it in body.get("content") or []:
        if it.get("commentDtoList"):        # 이미 답이 달린 건
            continue
        # 응답에 상품명 필드가 없다(문서) → 등록상품 ID 로 표시
        product = f"등록상품 {it['sellerProductId']}" if it.get("sellerProductId") else ""
        out.append(_row(f"coupang:online:{it['inquiryId']}", "쿠팡", "상품문의",
                        to_kst_text(it.get("inquiryAt")), product, "", it.get("content") or ""))
    return out


def coupang_parse_callcenter(body: dict) -> list:
    out = []
    for it in body.get("content") or []:
        # '판매자 답변 요청(requestAnswer)' 상태의 이관글 — 답변 API 가 이 answerId 를 parentAnswerId 로 요구(완성하기.md)
        parent = None
        for rep in it.get("replies") or []:
            if rep.get("partnerTransferStatus") == "requestAnswer":
                parent = rep
        # 미확인 — 실측 필요: 문서 예시의 최상위 content 는 "상담이력" 같은 요약이라 이관글 본문을 문의 원문으로 쓴다
        question = (parent or {}).get("content") or it.get("content") or ""
        if it.get("receiptCategory"):
            question = f"[{it['receiptCategory']}]\n{question}"
        parent_id = (parent or {}).get("answerId") or ""
        out.append(_row(f"coupang:cs:{it['inquiryId']}:{parent_id}", "쿠팡", "고객센터",
                        to_kst_text(it.get("inquiryAt")), it.get("itemName") or "", "", question))
    return out


# ====================================================================== 카페24
# 문서(05_Community): 게시판 목록(GET /boards) · 게시물 목록(GET /boards/{board_no}/articles)
def cafe24_boards() -> list:
    # 미확인 — 실측 필요: 응답 최상위 키 'boards' — 문서 응답 예시가 비어 있어 카페24 공통 규칙(리소스 이름이 키)으로 맞춤
    return cafe24.request("GET", "/boards").get("boards") or []


def cafe24_fetch(days: int) -> list:
    nos = [b.strip() for b in (env.get(CAFE24_BOARD_KEY) or "").split(",") if b.strip()]
    if not nos:
        raise ChannelError(f"{CAFE24_BOARD_KEY} 가 비어 있습니다 — `python3 .claude/skills/inquiry-inbox/scripts/fetch.py --cafe24-boards` 로 "
                           f"게시판 번호를 보고 `python3 shared/setup_keys.py --key {CAFE24_BOARD_KEY}` 로 넣어 주세요(예: 6,9)")
    kinds = {}
    try:
        for b in cafe24_boards():
            kinds[str(b.get("board_no"))] = "상품문의" if str(b.get("board_type")) == "5" else "고객문의"
    except ChannelError:
        pass   # 종류 이름만 못 정할 뿐 — 모으기는 계속
    end = now_kst()
    start = end - timedelta(days=min(days, 365))      # 한 호출에 1년 이상 검색 불가(문서)
    rows = []
    for no in nos:
        offset = 0
        while True:
            data = cafe24.request("GET", f"/boards/{no}/articles", {
                "start_date": start.strftime("%Y-%m-%d"), "end_date": end.strftime("%Y-%m-%d"),
                "comment": "F",            # 댓글 없는 글 = 아직 답 안 한 글
                "article_type": "normal",  # 공지·고정글 제외
                "limit": 100, "offset": offset})
            items = data.get("articles") or []   # 미확인 — 실측 필요: 최상위 키 'articles' — boards 와 같은 이유
            rows += cafe24_parse_articles(no, items, kinds.get(str(no), "고객문의"))
            if len(items) < 100 or offset + 100 > 8000:   # offset 최대 8000(문서)
                break
            offset += 100
    return rows


def cafe24_parse_articles(board_no, items: list, kind: str) -> list:
    out = []
    for it in items:
        if str(it.get("deleted") or "F") != "F":
            continue
        if str(it.get("reply_status") or "") == "C":     # 1:1 게시판 '처리완료'
            continue
        try:
            if int(it.get("reply_depth") or 0) > 0:      # 답변글(운영자가 단 글) 제외
                continue
        except (TypeError, ValueError):
            pass
        body = re.sub(r"(?i)<br\s*/?>|</p>", "\n", it.get("content") or "")   # 줄바꿈 태그는 줄바꿈으로
        body = html.unescape(re.sub(r"<[^>]+>", " ", body)).replace("\xa0", " ")
        body = "\n".join(re.sub(r"[ \t]+", " ", ln).strip() for ln in body.splitlines()).strip()
        pno = it.get("product_no")
        product = f"상품번호 {pno}" if pno not in (None, "", 0, "0") else ""
        out.append(_row(f"cafe24:{board_no}:{it['article_no']}", "카페24", kind,
                        to_kst_text(it.get("created_date")), product,
                        mask_name(it.get("writer") or it.get("member_id")),
                        f"{it.get('title') or ''}\n{body}"))
    return out


FETCH = {"naver": naver_fetch, "coupang": coupang_fetch, "cafe24": cafe24_fetch}
