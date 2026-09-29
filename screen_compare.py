"""화면 두 곳을 찍어 달라진 자리를 짚어 준다.

결재자가 말없이 고쳐서 결재한 공문을, 한글 창 두 개를 나란히 띄운 채
드래그로 영역만 지정하면 무엇이 달라졌는지 표시해 준다.

글자를 읽지 않는다(OCR 이 아니다). 모양만 본다:

1. 찍은 그림에서 글자가 있는 가로 띠(글줄)를 찾는다
2. 글줄마다 좌우 여백을 떼어 낸다 — 두 창의 위치가 달라도 맞물리게
3. 글줄끼리 맞춘다 — 줄이 끼어들어 아래가 밀려도 따라간다
4. 짝지어진 줄 안에서 칸 단위로 다시 비교해 달라진 구간을 돌려준다

표준 라이브러리만 쓴다. 화면은 `ctypes` 로 윈도우 GDI 를 직접 부르고,
맞추는 일은 `difflib` 가 한다. 새 꾸러미를 들이면 배포 라이선스 고지가
늘어난다.

**개인정보 — 지켜야 할 규칙**

화면에 무엇이 있을지 프로그램은 알 수 없다. 공문 폴더에 넣은 파일과
달리 이용자가 "이건 읽어도 된다" 고 정해 준 것이 아니다. 그래서:

- 지정한 사각형만 찍는다. 화면 전체를 미리 찍어 두지 않는다.
- 찍은 그림은 **메모리에만** 둔다. 저장소·임시파일·설정파일 어디에도
  쓰지 않는다. 이 파일에는 파일을 여는 코드가 없어야 한다.
- 예외 메시지에 찍은 내용을 담지 않는다. `widget.py` 의 전역 처리기가
  예외 메시지를 `.gongmun-submisson/오류기록.txt` 에 적고 안내창에도 띄운다.

`tests/test_screen_compare.py` 가 이 셋을 지킨다.
"""

from __future__ import annotations

import ctypes
import difflib
import sys
from ctypes import wintypes

# 이보다 어두우면 글자로 본다. 흐린 회색 글씨도 잡되 종이 바탕은 거른다.
INK = 140

# 칸을 이만큼씩 묶어 글줄끼리 맞춘다. 잘게 보면 느리고, 크게 묶으면 둔해진다.
BUCKET = 3

# 두 글줄이 이만큼도 안 닮았으면 같은 줄이 고쳐진 것으로 보지 않는다.
PAIRABLE = 0.55

# 이보다 밝으면 종이로 본다. 그 바깥의 회색 바탕과 가르는 선.
PAPER = 225

# 한 줄(칸)이 이 비율 넘게 밝아야 종이로 친다. 글자가 있는 줄도 대부분은 흰
# 바탕이므로 넉넉히 잡아도 된다.
PAPER_SHARE = 0.55

# 이보다 작게 잡히면 종이를 찾은 것이 아니다.
PAPER_MIN = 80

# 같은 너비가 이 줄 수 넘게 나와야 종이로 인정한다. 어쩌다 한 줄 넓게
# 비어 있는 것과 가른다.
PAPER_ROWS = 12

# 글줄 높이가 이 비율 넘게 다르면 확대 배율이 어긋난 것으로 본다. 배율을
# 10% 만 올려도 높이가 15% 늘어나므로 이 정도면 충분히 가른다.
ZOOM_SLACK = 0.12

# 끊기지 않고 이 길이(픽셀) 넘게 이어지는 칸은 글자가 아니라 선으로 본다.
# 그림이 크면 글자도 크므로 높이에 따라 함께 키운다.
RUN_MIN = 40

SAME, EDITED, ADDED, REMOVED = "same", "edited", "added", "removed"


class ScreenError(Exception):
    """찍거나 비교할 수 없는 경우.

    메시지에 찍은 내용을 담지 않는다 — 오류 기록에 그대로 남기 때문이다.
    """


class Shot:
    """찍은 그림 한 장. 밝기만 남긴다(색은 비교에 필요 없다)."""

    def __init__(self, width: int, height: int, grey: bytes):
        self.width, self.height, self.grey = width, height, grey
        self._rules: frozenset[int] | None = None

    @property
    def rules(self) -> frozenset[int]:
        """세로로 거의 끝까지 이어지는 칸. 쪽 테두리·창 테두리·표 선이다.

        **이걸 안 걸러 내면 도구가 통째로 망가진다.** 그 칸 때문에 모든
        가로줄에 잉크가 있게 되어, 문서 전체가 글줄 하나로 뭉친다. 그러면
        달라진 곳을 문서만큼 커다란 상자 하나로 표시해서 아무것도 못
        알아본다. 한글 창을 실제로 찍었을 때 그렇게 됐다.
        """
        if self._rules is None:
            self._rules = _find_rules(self)
        return self._rules

    def row_has_ink(self, y: int) -> bool:
        row = self.grey[y * self.width:(y + 1) * self.width]
        rules = self.rules
        if not rules:
            return any(v < INK for v in row)
        return any(v < INK for x, v in enumerate(row) if x not in rules)

    def columns(self, top: int, bottom: int) -> list[int]:
        """글줄 하나를 칸별로 훑어 어느 높이에 획이 있는지를 비트로 모은다.

        잉크의 양만 세면 획 수가 같은 글자(마/바)를 구별하지 못한다.
        실제로 항목 번호가 바뀐 것을 놓쳤다. 높이별 유무를 비트로 쌓으면
        같은 양이라도 모양이 다르면 값이 달라지고, 정수 하나라 비교 비용은
        그대로다.
        """
        out = [0] * self.width
        rules = self.rules
        for step, y in enumerate(range(top, bottom)):
            row = self.grey[y * self.width:(y + 1) * self.width]
            bit = 1 << step
            for x in range(self.width):
                if row[x] < INK and x not in rules:
                    out[x] |= bit
        return out


class Change:
    """수정본에서 표시할 자리 하나."""

    def __init__(self, state: str, top: int, bottom: int,
                 spans: list[tuple[int, int]]):
        self.state, self.top, self.bottom, self.spans = state, top, bottom, spans

    def __repr__(self) -> str:   # 내용은 담지 않는다. 좌표뿐.
        return (f"Change({self.state}, y={self.top}~{self.bottom}, "
                f"{len(self.spans)}곳)")


# ------------------------------------------------------------------ 화면 찍기

class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


def to_grey(raw: bytes) -> bytes:
    """32비트 화면 자료에서 초록 채널만 남긴다. 밝기 대신 쓰기 충분하다."""
    return bytes(raw[i + 1] for i in range(0, len(raw), 4))


class _Point(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


def cursor_at() -> tuple[int, int]:
    """마우스가 지금 있는 자리. 화면을 찍을 때와 **같은 좌표계** 로 돌려준다.

    tkinter 가 알려 주는 자리를 쓰면 안 된다. 화면 배율이 걸린 컴퓨터에서는
    tkinter 가 보는 좌표와 윈도우가 보는 좌표가 어긋나서, 끌어낸 자리가
    아니라 엉뚱한 데가 찍힌다. 실제로 그런 컴퓨터가 있었다.

    여기서 물어본 자리는 `capture()` 가 쓰는 좌표계와 같으므로, 배율이
    어떻든 끌어낸 그 자리가 찍힌다.
    """
    point = _Point()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def capture(left: int, top: int, width: int, height: int) -> Shot:
    """화면의 그 사각형만 찍는다. 바깥은 애초에 복사되지 않는다."""
    if sys.platform != "win32":
        raise ScreenError("화면 비교는 윈도우에서만 됩니다.")
    if width < 8 or height < 8:
        raise ScreenError("고른 자리가 너무 좁습니다. 조금 더 넓게 끌어 주세요.")

    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    screen = user32.GetDC(0)
    memory = gdi32.CreateCompatibleDC(screen)
    bitmap = gdi32.CreateCompatibleBitmap(screen, width, height)
    try:
        gdi32.SelectObject(memory, bitmap)
        # SRCCOPY. 요청한 사각형만 옮긴다.
        if not gdi32.BitBlt(memory, 0, 0, width, height,
                            screen, left, top, 0x00CC0020):
            raise ScreenError("화면을 찍지 못했습니다. "
                              "보안 프로그램이 막고 있을 수 있습니다.")
        head = _BitmapInfoHeader()
        head.biSize = ctypes.sizeof(_BitmapInfoHeader)
        head.biWidth, head.biHeight = width, -height    # 음수 = 위에서 아래로
        head.biPlanes, head.biBitCount = 1, 32
        buffer = ctypes.create_string_buffer(width * height * 4)
        gdi32.GetDIBits(memory, bitmap, 0, height, buffer, ctypes.byref(head), 0)
        raw = buffer.raw
    finally:
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory)
        user32.ReleaseDC(0, screen)
    return Shot(width, height, to_grey(raw))


# ------------------------------------------------------------------ 비교

def prepare(before: Shot, after: Shot) -> tuple[Shot, Shot]:
    """견주기 전에 종이만 남기고, 배율이 어긋났는지 살핀다.

    둘 다에서 종이를 찾았을 때만 자른다. 한쪽만 찾았다면 무엇을 보고
    있는지 확신할 수 없으므로 손대지 않는다.
    """
    one, two = _paper_box(before), _paper_box(after)
    if one is None or two is None:
        return before, after

    cut_before, cut_after = _crop(before, one), _crop(after, two)
    _check_zoom(cut_before, cut_after)
    return cut_before, cut_after


def _check_zoom(before: Shot, after: Shot) -> None:
    """배율이 어긋났으면 못 하겠다고 말한다. **글줄 높이** 로 잰다.

    처음에는 종이 너비로 쟀는데 틀렸다. 끌어낸 자리가 종이보다 좁으면
    종이가 잘려서, 보이는 너비가 종이 너비가 아니라 **끌어낸 폭** 이 된다.
    두 번 끄는 폭이 조금만 달라도 배율이 같은데 다르다고 나왔다 — 다른
    컴퓨터에서 실제로 그 오류가 났다.

    글줄 높이는 잘려도 그대로다. 실측으로 배율을 그대로 따라간다:
    100% 13px, 110% 15px, 125% 17px, 150% 22px, 200% 29px.
    """
    one, two = _line_height(before), _line_height(after)
    if not one or not two:
        return
    if abs(one - two) > max(1, max(one, two) * ZOOM_SLACK):
        raise ScreenError("두 문서의 확대 배율이 서로 다른 것 같습니다.\n\n"
                          "같은 배율(예: 둘 다 100%)로 맞춘 뒤 다시 해 주세요.")


def _line_height(shot: Shot) -> float:
    """글줄 높이의 가운데 값. 제목처럼 유난히 큰 줄에 휘둘리지 않는다."""
    found = sorted(bottom - top for top, bottom in bands(shot))
    if not found:
        return 0.0
    middle = len(found) // 2
    if len(found) % 2:
        return float(found[middle])
    return (found[middle - 1] + found[middle]) / 2


def crop_to_paper(shot: Shot) -> Shot:
    """찍은 그림에서 흰 종이 부분만 잘라낸다. 못 찾으면 그대로 돌려준다.

    한글 문서비교 창은 늘 같은 모양이다 — 흰 종이가 있고 그 바깥은 회색
    바탕이며, 아래에 상태표시줄, 옆에 스크롤바가 붙는다. 그 부속들은
    공문 내용이 아닌데도 견주는 대상에 들어가 애먼 표시를 만든다. 실제로
    상태표시줄에 빨간 상자가 쳐졌다.

    종이만 잘라내면 셋이 한꺼번에 풀린다.

    - 창 부속이 비교에서 빠진다
    - 드래그를 대충 해도 같은 자리가 잘려 나와, 두 번 끄는 범위가 달라도
      결과가 같다
    - 두 종이의 너비를 견주면 확대 배율이 어긋난 것을 알아챌 수 있다
    """
    place = _paper_box(shot)
    return shot if place is None else _crop(shot, place)


def _crop(shot: Shot, place: tuple[int, int, int, int]) -> Shot:
    left, top, right, bottom = place
    rows = [shot.grey[y * shot.width + left:y * shot.width + right]
            for y in range(top, bottom)]
    return Shot(right - left, bottom - top, b"".join(rows))


def _paper_box(shot: Shot) -> tuple[int, int, int, int] | None:
    """흰 종이의 네 귀퉁이. 찾지 못하면 None.

    가로는 **줄마다 가장 긴 흰 구간을 모아 가장 흔한 것** 을 고른다.
    글줄 사이의 빈 줄들이 종이 너비를 정확히 알려 주기 때문이다. 그림
    전체에서 밝은 칸의 비율을 재는 방법은 쓰지 않는다 — 끄는 범위에 여백을
    얼마나 넉넉히 넣었느냐에 따라 비율이 흔들려서, 같은 종이가 번번이 다른
    너비로 잡혔다.
    """
    seen: dict[tuple[int, int], int] = {}
    for y in range(shot.height):
        row = shot.grey[y * shot.width:(y + 1) * shot.width]
        span = _widest_bright(row)
        if span is not None and span[1] - span[0] >= PAPER_MIN:
            seen[span] = seen.get(span, 0) + 1
    if not seen:
        return None
    (left, right), often = max(seen.items(), key=lambda pair: pair[1])
    if often < PAPER_ROWS:
        return None

    # 세로는 그 너비 안에서 대체로 흰 줄이 이어지는 구간. 글이 있는 줄도
    # 대부분은 흰 바탕이므로 넉넉한 기준으로 잡힌다.
    need = (right - left) * PAPER_SHARE
    white = [sum(1 for value in shot.grey[y * shot.width + left:
                                          y * shot.width + right]
                 if value >= PAPER) >= need
             for y in range(shot.height)]
    span = _longest_true(white)
    if span is None:
        return None
    top, bottom = span

    # 테두리 선을 피해 안쪽으로 물러나는 여유를 뒀다가 뺐다. 선은 어두워서
    # 애초에 밝은 구간에 들어오지 않고, 혹 들어와도 세로선으로 걸러진다.
    # 막는 것이 없는 여유를 남기면 뜻이 있는 것처럼 보여 더 나쁘다.
    if right - left < PAPER_MIN or bottom - top < PAPER_MIN:
        return None
    return left, top, right, bottom


def _widest_bright(row: bytes) -> tuple[int, int] | None:
    """그 줄에서 밝은 점이 가장 길게 이어진 구간."""
    best = start = None
    for x, value in enumerate(row):
        if value >= PAPER:
            start = x if start is None else start
            if best is None or x + 1 - start > best[1] - best[0]:
                best = (start, x + 1)
        else:
            start = None
    return best


def _longest_true(flags: list[bool]) -> tuple[int, int] | None:
    """True 가 가장 길게 이어진 구간."""
    best = run = None
    for i, on in enumerate(flags + [False]):
        if on:
            run = i if run is None else run
        elif run is not None:
            if best is None or i - run > best[1] - best[0]:
                best = (run, i)
            run = None
    return best


def _find_rules(shot: Shot) -> frozenset[int]:
    """세로로 길게 이어지는 칸을 찾는다. `Shot.rules` 가 부른다.

    **'그림 높이의 몇 % 인가' 로 재면 안 된다.** 고른 자리가 테두리보다
    넓으면 테두리가 그 비율에 못 미쳐 그냥 지나가고, 그 순간 글줄이 통째로
    하나로 뭉친다. 실사용에서 정확히 이렇게 됐다 — 테두리가 고른 자리의
    72~79% 를 차지해 8할 기준을 아슬아슬하게 비껴갔다.

    대신 **끊기지 않고 이어진 길이** 로 본다. 테두리·표 눈금은 글줄
    높이의 몇 배씩 이어지지만 글자의 세로획은 글줄 하나를 넘지 못한다.
    고른 자리가 테두리를 얼마나 넉넉히 감쌌든 상관이 없어진다.
    """
    limit = max(RUN_MIN, shot.height // 8)
    run = [0] * shot.width          # 지금 이어지고 있는 길이
    longest = [0] * shot.width      # 그 칸에서 가장 길게 이어진 길이
    inked = [False] * shot.width
    for y in range(shot.height):
        row = shot.grey[y * shot.width:(y + 1) * shot.width]
        for x, value in enumerate(row):
            if value < INK:
                inked[x] = True
                run[x] += 1
                if run[x] > longest[x]:
                    longest[x] = run[x]
            else:
                run[x] = 0

    found = frozenset(x for x, length in enumerate(longest) if length >= limit)

    # 걸러 낸 뒤 글자가 하나도 안 남으면 잘못 짚은 것이다. 그대로 둔다.
    if found and all(x in found for x, on in enumerate(inked) if on):
        return frozenset()
    return found


def bands(shot: Shot, gap: int = 4) -> list[tuple[int, int]]:
    """글자가 있는 가로 띠. 사이가 gap 줄 이하로 벌어지면 같은 글줄로 본다."""
    ink = [shot.row_has_ink(y) for y in range(shot.height)]
    found, y = [], 0
    while y < shot.height:
        if not ink[y]:
            y += 1
            continue
        start, blank = y, 0
        while y < shot.height and blank <= gap:
            y += 1
            blank = 0 if (y < shot.height and ink[y]) else blank + 1
        found.append((start, y - blank))
    return [(a, b) for a, b in found if b - a >= 5]


def _trim(columns: list[int]) -> tuple[list[int], int]:
    """좌우 여백을 떼어 낸다. 두 창의 가로 위치가 달라도 맞물리게."""
    marked = [i for i, v in enumerate(columns) if v]
    if not marked:
        return [], 0
    return columns[marked[0]:marked[-1] + 1], marked[0]


def _sign(columns: list[int]) -> tuple:
    """글줄의 지문. 똑같이 그려진 줄은 똑같은 값이 나온다."""
    return tuple(sum(columns[i:i + BUCKET])
                 for i in range(0, len(columns), BUCKET))


def _ratio(one, other) -> float:
    # autojunk 는 꺼 둔다. difflib 은 열이 200개를 넘으면 자주 나오는 값을
    # 잡음으로 보고 버리는데, 여기 값은 글자 모양이지 잡음이 아니다.
    #
    # 다만 정직하게 적어 둔다 — 실제로 그려 본 글줄로 전수 확인했더니
    # 켜고 끄고가 결과를 바꾸지 않았다(200칸 넘는 줄 다섯 개 모두 동일).
    # 칸마다 획 위치를 비트로 쌓아 값이 제각각이라 버릴 만큼 흔한 값이
    # 없기 때문이다. 그래도 끄는 쪽이 뜻에 맞고 비용이 없어 그대로 둔다.
    return difflib.SequenceMatcher(None, one, other, autojunk=False).ratio()


def _spans(before: list[int], after: list[int]) -> list[tuple[int, int]]:
    """같은 글줄 안에서 달라진 자리. **처음부터 끝까지 하나로 묶는다.**

    잘게 나누면 안 되는 이유가 있다. 글자 하나가 끼어들면 그 뒤가 통째로
    옆으로 밀리는데, 밀린 자리의 글자는 **같은 글자라도 픽셀이 미묘하게
    달라진다**(글꼴이 자리에 맞춰 획을 다듬기 때문). 그래서 진짜로 바뀐
    곳 말고 중간중간 멀쩡한 글자까지 함께 잡힌다. 실제로 따옴표 두 개와
    '호' 가 붙었을 뿐인데 상자가 네 개 떴다.

    자간을 줄이는 식의 수정은 줄 전체가 조금씩 밀리므로 더 심하다. 그런
    수정이 눈으로 찾기 가장 어려운 종류인데, 정작 그때 상자 무더기가
    쏟아지면 도구가 도움이 안 된다.

    그래서 **처음 달라진 자리부터 마지막으로 달라진 자리까지** 를 하나로
    감싼다. "이 안 어딘가가 바뀌었다" 는 정확한 말이고, 흩어진 상자를
    좇는 것보다 눈이 편하다. 한 줄에 멀리 떨어진 수정이 둘 있으면 그
    사이까지 함께 묶이지만, 어차피 그 줄은 통째로 봐야 하는 줄이다.
    """
    marks = [(start, max(end, start + 2))
             for tag, _, _, start, end in difflib.SequenceMatcher(
                 None, before, after, autojunk=False).get_opcodes()
             if tag != "equal"]
    if not marks:
        return []
    left = marks[0][0]
    right = min(marks[-1][1], len(after))
    if right <= left:
        right = min(left + 2, len(after))
    return [(left, right)]


def compare(before: Shot, after: Shot) -> list[Change]:
    """두 그림을 견주어, 수정본에서 표시할 자리를 돌려준다."""
    rows_before, rows_after = bands(before), bands(after)
    if not rows_after:
        raise ScreenError("고른 자리에서 글자를 찾지 못했습니다. "
                          "글이 있는 곳을 끌어 주세요.")

    cut_before = [_trim(before.columns(*box)) for box in rows_before]
    cut_after = [_trim(after.columns(*box)) for box in rows_after]
    sign_before = [_sign(columns) for columns, _ in cut_before]
    sign_after = [_sign(columns) for columns, _ in cut_after]

    changes: list[Change] = []
    for tag, b1, b2, a1, a2 in difflib.SequenceMatcher(
            None, sign_before, sign_after, autojunk=False).get_opcodes():
        if tag == "equal":
            changes += [Change(SAME, rows_after[i][0], rows_after[i][1], [])
                        for i in range(a1, a2)]
        elif tag == "insert":
            changes += [_whole(rows_after[i], cut_after[i])
                        for i in range(a1, a2)]
        elif tag == "delete":
            changes += [Change(REMOVED, rows_before[i][0], rows_before[i][1], [])
                        for i in range(b1, b2)]
        else:
            changes += _paired(rows_before, cut_before, sign_before, b1, b2,
                               rows_after, cut_after, sign_after, a1, a2)
    return changes


def _whole(box, cut) -> Change:
    """줄이 통째로 새로 생긴 경우. 그 줄 전체를 표시한다."""
    columns, offset = cut
    return Change(ADDED, box[0], box[1], [(offset, offset + len(columns))])


def _paired(rows_before, cut_before, sign_before, b1, b2,
            rows_after, cut_after, sign_after, a1, a2) -> list[Change]:
    """바뀐 덩어리. 닮은 줄끼리 짝지어 고쳐진 것으로 본다."""
    taken: set[int] = set()
    out = []
    for after in range(a1, a2):
        best, score = None, PAIRABLE
        for before in range(b1, b2):
            if before in taken:
                continue
            found = _ratio(sign_before[before], sign_after[after])
            if found > score:
                best, score = before, found
        if best is None:
            out.append(_whole(rows_after[after], cut_after[after]))
            continue
        taken.add(best)
        offset = cut_after[after][1]
        spans = [(offset + start, offset + end)
                 for start, end in _spans(cut_before[best][0],
                                          cut_after[after][0])]
        out.append(Change(EDITED, rows_after[after][0], rows_after[after][1],
                          spans))
    return out
