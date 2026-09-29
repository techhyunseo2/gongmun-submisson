"""결재 전후 공문 비교.

공문을 기안하면 결재자가 말없이 고쳐서 결재하는 일이 흔하다. 지금은
한글 비교 창을 띄워 두 문서를 눈으로 훑어야 하는데, 따옴표가 붙거나
'호' 한 글자가 늘어난 것 같은 변화는 잘 보이지 않는다.

두 파일의 본문을 뽑아 줄 단위로 맞춘 뒤, 짝이 지어진 줄 안에서는
글자 단위까지 좁혀서 어디가 달라졌는지 알려 준다. 표준 라이브러리
`difflib` 만 쓴다 — 새 꾸러미를 들이면 배포 라이선스 고지가 늘어난다.
"""

from __future__ import annotations

import difflib
from pathlib import Path

import extract

# 두 줄이 이만큼도 안 닮았으면 같은 줄이 고쳐진 것으로 보지 않는다.
# 결재자가 문장을 통째로 다시 쓴 경우인데, 억지로 글자 단위로 쪼개면
# '입'/'매' 같은 파편이 흩뿌려져 오히려 읽기 어려워진다.
SIMILAR_ENOUGH = 0.6

# 바뀐 덩어리 안에서 어느 줄과 어느 줄이 같은 줄인지 맞출 때의 하한.
PAIRABLE = 0.5

# difflib 은 열이 200개가 넘으면 자주 나오는 값을 '잡음' 으로 보고 버린다
# (autojunk). 실제 공문 형태로 재현해 보려 했으나 결과가 달라지는 경우를
# 찾지 못했다 — 흔한 줄이나 글자가 그만큼 많지 않기 때문이다. 화면 비교
# (`screen_compare.py`) 쪽도 마찬가지였다. 그래도 끄고 쓴다. 값의 성격상
# 잡음 판정이 맞지 않고, 비용이 없다.

SAME, EDITED, ADDED, REMOVED = "same", "edited", "added", "removed"
KEPT, PUT, CUT = "kept", "put", "cut"


class CompareError(Exception):
    """비교할 수 없는 경우. 사용자에게 그대로 보여 줄 말로 적는다."""


def compare_files(old_path: str | Path, new_path: str | Path) -> dict:
    """원본과 수정본 두 파일을 비교한다."""
    old, new = Path(old_path), Path(new_path)
    for path in (old, new):
        if not path.is_file():
            raise CompareError(f"파일을 찾을 수 없습니다: {path.name}")

    # 형식이 다르면 추출기가 줄을 다르게 끊어서, 글자가 하나도 안 바뀌어도
    # 온 문서가 고쳐진 것처럼 나온다. 조용히 틀린 답을 주느니 막는다.
    if old.suffix.lower() != new.suffix.lower():
        raise CompareError(
            f"같은 형식끼리만 비교할 수 있습니다 "
            f"({old.suffix or '확장자 없음'} ↔ {new.suffix or '확장자 없음'}). "
            f"형식이 다르면 글자가 그대로여도 전부 바뀐 것처럼 보입니다."
        )

    try:
        old_text = extract.extract_text(old)
        new_text = extract.extract_text(new)
    except extract.ExtractError as exc:
        raise CompareError(str(exc)) from exc

    rows = compare_text(old_text, new_text)
    return {
        "old": old.name,
        "new": new.name,
        "rows": rows,
        "changed": sum(1 for row in rows if row["state"] != SAME),
    }


def compare_text(old_text: str, new_text: str) -> list[dict]:
    """두 본문을 줄 단위로 맞추고, 짝지어진 줄은 글자 단위까지 좁힌다."""
    old = old_text.split("\n")
    new = new_text.split("\n")
    rows: list[dict] = []
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            rows += [_row(SAME, line) for line in new[j1:j2]]
        elif tag == "insert":
            rows += [_row(ADDED, line) for line in new[j1:j2]]
        elif tag == "delete":
            rows += [_row(REMOVED, line) for line in old[i1:i2]]
        else:
            rows += _replaced(old[i1:i2], new[j1:j2])
    return rows


def _row(state: str, text: str, spans: list[dict] | None = None) -> dict:
    return {"state": state, "text": text, "spans": spans}


def _replaced(old: list[str], new: list[str]) -> list[dict]:
    """바뀐 덩어리. 닮은 줄끼리 짝지어 고쳐진 것으로 보고, 나머지는 추가/삭제."""
    rows = []
    for before, after in _pairs(old, new):
        if before is None:
            rows.append(_row(ADDED, after))
        elif after is None:
            rows.append(_row(REMOVED, before))
        else:
            rows.append(_row(EDITED, after, marks(before, after)))
    return rows


def _pairs(old: list[str], new: list[str]) -> list[tuple[str | None, str | None]]:
    """어느 줄이 어느 줄로 고쳐졌는지 맞춘다. 수정본 순서를 지킨다."""
    taken: dict[int, str] = {}
    dropped: list[str] = []
    for before in old:
        best, score = None, PAIRABLE
        for k, after in enumerate(new):
            if k in taken:
                continue
            ratio = difflib.SequenceMatcher(None, before, after,
                                            autojunk=False).ratio()
            if ratio > score:
                best, score = k, ratio
        if best is None:
            dropped.append(before)
        else:
            taken[best] = before

    out: list[tuple[str | None, str | None]] = [(line, None) for line in dropped]
    out += [(taken.get(k), after) for k, after in enumerate(new)]
    return out


def marks(before: str, after: str) -> list[dict]:
    """고쳐진 줄 안에서 어디가 달라졌는지. 수정본 기준으로 조각을 낸다.

    많이 달라진 줄은 쪼개지 않고 통째로 표시한다 — 조각이 잘게 흩어지면
    읽는 사람이 오히려 무엇이 바뀌었는지 알기 어렵다.
    """
    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    if matcher.ratio() < SIMILAR_ENOUGH:
        return [{"kind": PUT, "text": after}, {"kind": CUT, "text": before}]

    spans: list[dict] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            spans.append({"kind": KEPT, "text": after[j1:j2]})
        else:
            if tag in ("insert", "replace"):
                spans.append({"kind": PUT, "text": after[j1:j2]})
            if tag in ("delete", "replace"):
                spans.append({"kind": CUT, "text": before[i1:i2]})
    return spans
