"""공문 본문을 읽고 개인 업무 유형과 날짜를 판단한다.

유형은 부서가 아니라 '내가 무엇을 해야 하는가' 기준이다.
  submit      기한 안에 자료를 만들어 보내야 하는 것
  event       참석하거나 학교에서 실시해야 하는 날짜가 있는 것
  apply       신청할지 말지 내가 고르는 것 (공모, 연수 모집)
  distribute  학생이나 학부모에게 전달해야 하는 것
  notice      읽고 알아두면 끝나는 것
  other       위 어디에도 확실히 걸리지 않는 것
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

CATEGORIES = {
    "submit": "제출·보고",
    "event": "일정·행사",
    "apply": "신청·공모",
    "distribute": "배포·전달",
    "notice": "안내·참고",
    "other": "미분류",
}

CATEGORY_ORDER = ["submit", "event", "apply", "distribute", "notice", "other"]

# (키워드, 가중치) — 제목에서 걸리면 가중치가 두 배로 반영된다.
_RULES: dict[str, list[tuple[str, int]]] = {
    "submit": [
        ("제출", 5), ("회신", 5), ("보고", 4), ("수요조사", 5), ("현황 조사", 4),
        ("실태조사", 4), ("명단", 3), ("취합", 4), ("작성하여", 3), ("등록 요청", 3),
        ("입력 요청", 4), ("결과 보고", 4), ("자료 요청", 4), ("협조 요청", 2),
        ("기한", 3), ("마감", 3), ("업로드", 2), ("나이스", 2), ("에듀파인", 2),
    ],
    "event": [
        ("실시", 4), ("개최", 5), ("운영", 2), ("연수", 3), ("회의", 4), ("행사", 4),
        ("대회", 4), ("점검", 3), ("훈련", 4), ("방문", 3), ("컨설팅", 3),
        ("워크숍", 4), ("설명회", 4), ("간담회", 4), ("체험", 3), ("일정", 3),
        ("참석", 4), ("출장", 3),
    ],
    "apply": [
        ("신청", 5), ("공모", 6), ("모집", 5), ("접수", 3), ("선발", 4), ("추천", 3),
        ("응모", 5), ("희망자", 4), ("참가 신청", 5), ("지원 사업", 4), ("공고", 3),
    ],
    "distribute": [
        ("가정통신문", 6), ("학부모", 4), ("학생 대상", 4), ("안내문", 4),
        ("배포", 5), ("게시", 3), ("홍보 요청", 4), ("리플릿", 4), ("포스터", 4),
        ("전달", 3), ("탑재", 2),
    ],
    "notice": [
        ("안내", 4), ("알림", 5), ("변경", 3), ("공지", 4), ("참고", 3),
        ("개정", 4), ("시행", 3), ("결과 알림", 4), ("홍보", 2), ("자료 제공", 3),
    ],
}

# 이 말이 붙은 날짜는 '마감'으로 본다.
_DEADLINE_CUES = (
    "까지", "기한", "마감", "제출", "회신", "신청", "접수", "이내", "한하여", "종료",
)

_WEEKDAY = r"(?:\s*\([월화수목금토일]\))?"
_DATE_PATTERNS = [
    # 2026. 9. 5.(금) / 2026-09-05 / 2026년 9월 5일
    re.compile(r"(?P<y>20\d{2})\s*[.\-년]\s*(?P<m>1[0-2]|0?[1-9])\s*[.\-월]\s*(?P<d>3[01]|[12]\d|0?[1-9])\s*[.일]?" + _WEEKDAY),
    # '26. 9. 5.
    re.compile(r"'(?P<y2>\d{2})\s*[.\-]\s*(?P<m>1[0-2]|0?[1-9])\s*[.\-]\s*(?P<d>3[01]|[12]\d|0?[1-9])\s*\.?" + _WEEKDAY),
    # 9월 5일 / 9. 5.(금)  — 연도 없음
    re.compile(r"(?<!\d)(?P<m>1[0-2]|0?[1-9])\s*[.월]\s*(?P<d>3[01]|[12]\d|0?[1-9])\s*[.일]" + _WEEKDAY),
]

_SENTENCE_SPLIT = re.compile(r"[\n。]|(?<=[다음임함])\.\s|(?<=\))\s{2,}")


def _sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(text) if p and p.strip()]
    return [p for p in parts if len(p) > 1]


# 다른 공문을 인용하는 줄. 여기 붙은 날짜는 내 일정이 아니다.
_REFERENCE_LINE = re.compile(r"^\s*\d?\s*\.?\s*관련\s*[:：]|관련\s*근거|^\s*근\s*거\s*[:：]")

# "1. 관련" / "관련:" / "근거" 처럼 인용 블록을 여는 머리줄. 뒤에 다른 내용이
# 붙지 않고 그 말만 있는 경우다. 이 다음에 오는 들여쓴 하위 항목들
# (가. 나. / 1) / ① / - )은 전부 다른 공문을 가리키는 인용이므로 날짜를 읽지
# 않는다. 최상위 항목("2." 등)이나 빈 줄이 나오면 블록이 끝난다.
_REF_BLOCK_HEADER = re.compile(
    r"^\s*[※*\-]?\s*(?:\d+\s*[.)]\s*)?(?:관\s*련|근\s*거)(?:\s*근거|\s*사항)?\s*[:：]?\s*$")
_REF_SUBITEM = re.compile(
    r"^\s*(?:[가-힣]\s*[.)]|[a-zA-Z]\s*[.)]|\d+\s*\)|[①-⑮㉠-㉭]|[▪▶◦○·•*∙]|-\s)\s*")

# "교원인사과-14453호(2026. 7. 31.)" 처럼 문서번호 바로 뒤에 괄호 날짜가 붙은
# 인용. 한 문장에 실제 기한과 섞여 있어도 이 부분만 지우고 나머지를 읽는다.
_CITATION_DATE = re.compile(
    r"[가-힣A-Za-z][가-힣A-Za-z\d]{1,19}\s*-\s*\d{3,7}\s*호?\s*"
    r"[,(]?\s*\(?\s*20\d{2}\s*[.\-]\s*\d{1,2}\s*[.\-]\s*\d{1,2}\s*\.?\s*\)?자?")

# 공문 아래쪽 결재선과 시행·접수 줄. 여기 날짜는 문서를 주고받은 날이지
# 내가 지켜야 할 날이 아니다.
_ROUTING_LINE = re.compile(
    r"시\s*행\s+\S+\s*-\s*\d+|접\s*수\s+\S+\s*-\s*\d+|협조자|전결|대결|"
    r"우\s*\d{5}|전화\s*\d{2,4}\s*-|전송\s*\d{2,4}\s*-|[\w.]+@[\w.]+|https?://")


def find_dates(text: str, base: date | None = None) -> list[tuple[list[date], str]]:
    """본문을 문장 단위로 훑어 (그 문장에 나온 날짜들, 문장) 목록을 만든다."""
    base = base or date.today()
    found: list[tuple[list[date], str]] = []
    in_ref_block = False

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            in_ref_block = False
            continue
        if _REF_BLOCK_HEADER.match(line):
            in_ref_block = True
            continue
        if in_ref_block:
            if _REF_SUBITEM.match(line):
                continue          # 인용 블록의 하위 항목 — 날짜를 읽지 않는다
            in_ref_block = False   # 최상위 항목·본문이 시작되면 블록이 끝남

        for sentence in _sentences(line):
            if _REFERENCE_LINE.search(sentence) or _ROUTING_LINE.search(sentence):
                continue
            scrubbed = _CITATION_DATE.sub("  ", sentence)
            dates = _dates_in(scrubbed, base)
            if dates:
                found.append((dates, sentence))
    return found


def _dates_in(sentence: str, base: date) -> list[date]:
    """한 문장에서 날짜를 뽑아 정렬해 돌려준다 (위치 정보 없이)."""
    return sorted({d for d, _ in _dated_spans(sentence, base)})


def _dated_spans(sentence: str, base: date) -> list[tuple[date, int]]:
    """(날짜, 시작위치) 목록. 같은 자리를 두 번 세지 않는다.

    "2004. 3. 1." 은 연도까지 있는 패턴이 먼저 통째로 잡는다. 뒤이어
    연도 없는 패턴이 "3. 1." 을 또 잡으면 있지도 않은 올해 3월 1일이
    생겨 버리므로, 이미 쓴 자리는 건너뛴다.
    """
    used: list[tuple[int, int]] = []
    out: list[tuple[date, int]] = []
    for pattern in _DATE_PATTERNS:                # 연도가 있는 것부터 본다
        for match in pattern.finditer(sentence):
            span = match.span()
            if any(span[0] < end and start < span[1] for start, end in used):
                continue
            parsed = _to_date(match, base)
            if parsed is None:
                continue
            used.append(span)
            out.append((parsed, span[0]))
    return out


def flatten_dates(found: list[tuple[list[date], str]]) -> list[date]:
    return sorted({d for dates, _ in found for d in dates})


def _to_date(match: re.Match, base: date) -> date | None:
    groups = match.groupdict()
    month, day = int(groups["m"]), int(groups["d"])
    if groups.get("y"):
        year = int(groups["y"])
    elif groups.get("y2"):
        year = 2000 + int(groups["y2"])
    else:
        # 연도가 없으면 기준일에 가장 가까운 해로 본다.
        year = base.year
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None
        if candidate < base - timedelta(days=120):
            year += 1
    try:
        return date(year, month, day)
    except ValueError:
        return None


# 규정이나 지침에는 부칙의 시행일처럼 아주 오래된 날짜가 섞여 있다.
# 이만큼 지난 날짜는 내가 지켜야 할 기한일 리 없다.
_STALE_DAYS = 400


def _is_deadline_sentence(sentence: str) -> bool:
    return any(cue in sentence for cue in _DEADLINE_CUES)


def _deadline_date_in(sentence: str, dates: list[date], base: date) -> date:
    """마감 문장에서 실제 마감일을 고른다.

    "10. 5. 실시하며, 명단은 9. 30.까지 제출"처럼 한 문장에 행사일과
    마감일이 같이 있으면 '까지' 앞에 있는 날짜가 마감이다. '까지'가 없으면
    (기간 표기 '9. 1.~9. 5.' 등) 마지막 날짜를 끝으로 본다.
    """
    cut = sentence.find("까지")
    if cut == -1:
        return dates[-1]
    # '까지' 바로 앞(위치상 가장 나중)에 있는 날짜가 마감이다.
    before = [(pos, d) for d, pos in _dated_spans(sentence, base) if pos < cut]
    return max(before)[1] if before else dates[-1]


def pick_deadline(found: list[tuple[list[date], str]],
                  base: date | None = None) -> tuple[date | None, str]:
    """마감 문장에서 마감일을 고른다.

    한 문장에 '9. 1. ~ 9. 5.'처럼 기간이 적혀 있으면 끝 날짜가 마감이다.
    마감 문장이 여러 개면 그중 가장 이른 것을 따른다.
    """
    base = base or date.today()
    floor = base - timedelta(days=_STALE_DAYS)
    candidates = []
    for dates, sentence in found:
        if not _is_deadline_sentence(sentence):
            continue
        chosen_date = _deadline_date_in(sentence, dates, base)
        if chosen_date >= floor:
            candidates.append((chosen_date, sentence))
    if not candidates:
        return None, ""
    chosen = min(candidates, key=lambda item: item[0])
    return chosen[0], chosen[1][:120]


def pick_event_date(found: list[tuple[list[date], str]], base: date | None = None) -> date | None:
    """행사일 후보 — 마감 문장이 아닌 곳에 적힌 날짜 중 오늘 이후 가장 이른 것."""
    base = base or date.today()
    upcoming = [d for dates, sentence in found if not _is_deadline_sentence(sentence)
                for d in dates if d >= base]
    return min(upcoming) if upcoming else None


_ORG_SUFFIX = re.compile(
    r"(교육청|교육지원청|교육부|교육원|연수원|재단|연구원|진흥원|협회|공단|공사|"
    r"시청|구청|군청|위원회|본부|센터|경찰서|소방서|보건소)\s*$")


_LABEL_ONLY = re.compile(r"^제\s*목\s*[:：]?$")
_ITEM_START = re.compile(r"^(\d+\s*\.|[가-힣]\s*\.|[①-⑮]|[ⅠⅡⅢⅣⅤ])\s")


def guess_title(text: str, fallback: str) -> str:
    """본문 머리에서 제목을 찾는다. 없으면 파일명을 쓴다."""
    lines = [line.strip() for line in text.split("\n")]

    # "제목: 내용" 처럼 한 줄에 같이 있는 경우
    for line in lines[:40]:
        stripped = re.sub(r"^제\s*목\s*[:：]?\s+", "", line)
        if stripped != line and stripped:
            return stripped[:120]

    # PDF는 "제목" 이 라벨만 한 줄을 차지하고 내용이 다음 줄부터 온다.
    # 제목이 길면 두세 줄로 접혀 있으므로 항목 번호가 나올 때까지 이어 붙인다.
    for index, line in enumerate(lines[:40]):
        if not _LABEL_ONLY.match(line):
            continue
        collected: list[str] = []
        for following in lines[index + 1:index + 6]:
            if not following or _ITEM_START.match(following):
                break
            collected.append(following)
        if collected:
            return re.sub(r"\s+", " ", " ".join(collected))[:120]

    for line in text.split("\n")[:15]:
        line = line.strip(" .·-")
        if not 6 <= len(line) <= 80:
            continue
        if re.search(r"(수신|발신|경유|참조|담당자|전화|팩스)", line):
            continue
        if _ORG_SUFFIX.search(line):      # 기관명 줄은 제목이 아니다
            continue
        return line[:120]
    return fallback


def guess_sender(text: str) -> str:
    match = re.search(r"(?:발\s*신|기\s*관\s*명)\s*[:：]?\s*(.{2,30})", text)
    if match:
        return match.group(1).strip().split()[0][:30]
    for line in text.split("\n")[:12]:
        line = line.strip()
        if 2 <= len(line) <= 22 and _ORG_SUFFIX.search(line):
            return line[:30]
    return ""


def guess_doc_number(text: str) -> str:
    """보낸 쪽 문서번호. 공문 아래 '시행 OO과-12345' 가 가장 정확하다."""
    match = re.search(r"시\s*행\s+([가-힣A-Za-z]{2,15}\s*-\s*\d{3,7})", text)
    if match:
        return re.sub(r"\s+", "", match.group(1))[:40]
    match = re.search(r"(?:문서번호|문서\s*번호)\s*[:：]?\s*([\w가-힣\-]+\s*-?\s*\d+)", text)
    if match:
        return re.sub(r"\s+", "", match.group(1))[:40]
    return ""


def guess_receipt_number(text: str) -> str:
    """우리 학교 접수번호. 본문과 첨부를 하나로 묶는 열쇠가 된다."""
    match = re.search(r"접\s*수\s+([가-힣A-Za-z]{2,15}\s*-\s*\d{2,7})", text)
    return re.sub(r"\s+", "", match.group(1))[:40] if match else ""


def classify(title: str, body: str, has_deadline: bool, has_future_date: bool) -> tuple[str, dict[str, int]]:
    scores = {key: 0 for key in _RULES}
    head = body[:1500]

    for category, keywords in _RULES.items():
        for word, weight in keywords:
            if word in title:
                scores[category] += weight * 2
            if word in head:
                scores[category] += weight

    if has_deadline:
        scores["submit"] += 6
        scores["apply"] += 3
        scores["notice"] -= 3
    if has_future_date:
        scores["event"] += 4
    if not has_deadline and not has_future_date:
        scores["notice"] += 4

    best = max(scores, key=lambda key: scores[key])
    if scores[best] < 5:
        return "other", scores
    return best, scores


def analyze(title_fallback: str, body: str, base: date | None = None) -> dict:
    """파일 하나에 대한 분석 결과를 돌려준다."""
    base = base or date.today()
    title = guess_title(body, title_fallback)
    found = find_dates(body, base)
    deadline, deadline_context = pick_deadline(found, base)
    event_date = pick_event_date(found, base)

    category, scores = classify(
        title=title,
        body=body,
        has_deadline=deadline is not None,
        has_future_date=event_date is not None,
    )

    top = sorted(scores.items(), key=lambda item: -item[1])[:2]
    confidence = "높음" if top[0][1] >= 14 and top[0][1] - top[1][1] >= 5 else "보통"
    if top[0][1] < 5:
        confidence = "낮음"

    return {
        "title": title,
        "sender": guess_sender(body),
        "doc_number": guess_doc_number(body),
        "receipt_number": guess_receipt_number(body),
        "category": category,
        "confidence": confidence,
        "deadline": deadline.isoformat() if deadline else None,
        "deadline_context": deadline_context,
        "event_date": event_date.isoformat() if event_date else None,
        "all_dates": [d.isoformat() for d in flatten_dates(found)],
        "summary": _first_meaningful_lines(body),
    }


def _first_meaningful_lines(body: str, limit: int = 220) -> str:
    skip = re.compile(r"(수신|발신|경유|참조|담당자|전화|팩스|주소|누리집|전자우편|우\s*\d{5})")
    picked: list[str] = []
    for line in body.split("\n"):
        line = line.strip()
        if len(line) < 8 or skip.search(line):
            continue
        picked.append(line)
        if sum(len(p) for p in picked) > limit:
            break
    return " ".join(picked)[:limit]


def days_left(deadline: str | None, base: date | None = None) -> int | None:
    if not deadline:
        return None
    base = base or date.today()
    return (datetime.strptime(deadline, "%Y-%m-%d").date() - base).days
