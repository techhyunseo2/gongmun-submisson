"""화면 비교.

결재자가 말없이 고친 곳을 찾아 준다. 판단이 틀리면 "안 바뀌었다" 를
믿고 넘어가게 만드는 도구라, 놓치는 것이 잘못 알리는 것보다 위험하다.

글자를 창 없이 메모리에 그려서 시험한다(GDI). 윈도우의 실제 글자
렌더링을 그대로 쓰므로 진짜에 가깝고, 창이 안 뜨니 CI 에서도 돈다.
"""

from __future__ import annotations

import ctypes
import sys
import unittest
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import screen_compare as sc  # noqa: E402

WINDOWS = sys.platform == "win32"

BEFORE = [
    "예시중학교",
    "수신    내부결재",
    "(경유)",
    "제목   (중)2026학년도 방과후학교(요리반) 물품 구매",
    "1. 관련: 예시중학교-2949(2026. 5. 14., 2026 학교교육계획)",
    "2. 2026학년도 방과후학교(요리반) 운영에 필요한 물품을 구매하고자 합니다.",
    "   가. 일    시: 2026. 8. 24.(월) 7, 8교시",
    "   나. 장    소: 기술실",
    "   다. 대    상: 수강생 7명",
    "   라. 품목내역: 지출품의서 참조",
    "   마. 소요예산: 금75,000원(금칠만오천원).  끝.",
]


# ------------------------------------------------------- 창 없이 글자 그리기

class _Rect(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


def render(lines, width=900, height=380, left=12, step=30, size=-15):
    """메모리에 글자를 그려 Shot 을 만든다. 창을 띄우지 않는다."""
    gdi32, user32 = ctypes.windll.gdi32, ctypes.windll.user32
    dc = gdi32.CreateCompatibleDC(0)
    head = sc._BitmapInfoHeader()
    head.biSize = ctypes.sizeof(sc._BitmapInfoHeader)
    head.biWidth, head.biHeight = width, -height
    head.biPlanes, head.biBitCount = 1, 32
    bits = ctypes.c_void_p()
    bitmap = gdi32.CreateDIBSection(dc, ctypes.byref(head), 0,
                                    ctypes.byref(bits), None, 0)
    white = gdi32.CreateSolidBrush(0x00FFFFFF)
    font = gdi32.CreateFontW(size, 0, 0, 0, 400, 0, 0, 0, 129, 0, 0, 4, 0,
                             "맑은 고딕")
    try:
        gdi32.SelectObject(dc, bitmap)
        whole = _Rect(0, 0, width, height)
        user32.FillRect(dc, ctypes.byref(whole), white)
        gdi32.SelectObject(dc, font)
        gdi32.SetBkMode(dc, 1)              # TRANSPARENT
        gdi32.SetTextColor(dc, 0x00000000)
        for row, line in enumerate(lines):
            box = _Rect(left, 10 + row * step, width, 10 + (row + 1) * step)
            user32.DrawTextW(dc, line, -1, ctypes.byref(box), 0x00000004)
        gdi32.GdiFlush()
        raw = ctypes.string_at(bits, width * height * 4)
    finally:
        gdi32.DeleteObject(font)
        gdi32.DeleteObject(white)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(dc)
    return sc.Shot(width, height, sc.to_grey(raw))


@unittest.skipUnless(WINDOWS, "화면 비교는 윈도우에서만 됩니다")
class Rendering(unittest.TestCase):
    """시험 도구 자체가 멀쩡한지부터. 이게 깨지면 아래가 다 무의미하다."""

    def test_text_actually_gets_drawn(self):
        shot = render(BEFORE)
        ink = sum(1 for v in shot.grey if v < sc.INK)
        self.assertGreater(ink, 2000, "글자가 그려지지 않았습니다")

    def test_every_line_becomes_a_band(self):
        self.assertEqual(len(sc.bands(render(BEFORE))), len(BEFORE))


def changed(rows):
    return [row for row in rows if row.state != sc.SAME]


@unittest.skipUnless(WINDOWS, "화면 비교는 윈도우에서만 됩니다")
class Finding(unittest.TestCase):

    def test_same_content_at_a_different_place_is_quiet(self):
        """두 창의 가로 위치가 달라도 오탐이 없어야 한다.

        나란히 띄운 두 창은 결코 같은 자리에 있지 않다. 여기서 오탐이
        나면 온 문서가 빨개져서 도구가 쓸모없어진다.
        """
        rows = sc.compare(render(BEFORE, left=12), render(BEFORE, left=45))
        self.assertEqual(changed(rows), [])

    def test_the_real_case(self):
        """실제로 겪은 사례. 따옴표가 씌워지고 '호' 가 붙었다."""
        after = list(BEFORE)
        after[4] = ("1. 관련: 예시중학교-2949(2026. 5. 14., "
                    "“2026 학교교육계획”)호")
        rows = changed(sc.compare(render(BEFORE), render(after)))
        self.assertEqual(len(rows), 1, f"고친 한 줄만 잡혀야 합니다: {rows}")
        self.assertEqual(rows[0].state, sc.EDITED)
        self.assertTrue(rows[0].spans, "어디가 달라졌는지 짚어야 합니다")
        # 줄 전체가 아니라 일부만 표시해야 한다.
        marked = sum(end - start for start, end in rows[0].spans)
        self.assertLess(marked, 200, "너무 넓게 표시했습니다")

    def test_one_box_per_changed_line(self):
        """상자는 줄마다 하나. 처음 달라진 데서 마지막까지 감싼다.

        글자가 끼어들면 그 뒤가 옆으로 밀리고, 밀린 자리의 글자는 같은
        글자라도 픽셀이 미묘하게 달라진다. 잘게 나누면 멀쩡한 글자에도
        상자가 붙어 무더기가 된다 — 따옴표 둘과 '호' 를 넣었을 뿐인데
        상자가 넷 떴다.
        """
        after = list(BEFORE)
        after[4] = ("1. 관련: 예시중학교-2949(2026. 5. 14., "
                    "“2026 학교교육계획”)호")
        for mark in changed(sc.compare(render(BEFORE), render(after))):
            with self.subTest(mark=mark):
                self.assertEqual(len(mark.spans), 1, "상자가 흩어졌습니다")

    def test_tightened_spacing_gives_one_box_too(self):
        """자간을 줄이면 줄 전체가 조금씩 밀린다.

        눈으로 찾기 가장 어려운 종류인데, 정작 그때 상자 무더기가 쏟아지면
        도구가 도움이 안 된다.
        """
        after = list(BEFORE)
        after[5] = BEFORE[5].replace(" ", "")
        marks = changed(sc.compare(render(BEFORE), render(after)))
        self.assertTrue(marks)
        for mark in marks:
            with self.subTest(mark=mark):
                self.assertEqual(len(mark.spans), 1, "상자가 흩어졌습니다")

    def test_two_far_apart_edits_share_one_box(self):
        """한 줄에 떨어진 수정이 둘이어도 하나로 묶는다. 그 줄은 통째로 볼 줄이다."""
        after = list(BEFORE)
        after[10] = "   바. 소요예산: 금80,000원(금팔만원).  끝."
        marks = changed(sc.compare(render(BEFORE), render(after)))
        self.assertEqual(len(marks), 1)
        self.assertEqual(len(marks[0].spans), 1)
        start, end = marks[0].spans[0]
        self.assertLess(start, 80, "앞쪽 항목 번호부터 감싸야 합니다")
        self.assertGreater(end, 180, "뒤쪽 금액까지 감싸야 합니다")

    def test_inserted_line_does_not_flag_the_rest(self):
        """줄이 끼어들면 아래가 전부 밀린다. 그걸 다 바뀐 것으로 보면 안 된다."""
        after = BEFORE[:8] + ["   다. 준비물: 앞치마"] + BEFORE[8:]
        rows = changed(sc.compare(render(BEFORE), render(after)))
        self.assertTrue(any(row.state == sc.ADDED for row in rows))
        self.assertLessEqual(len(rows), 4, f"너무 많이 잡혔습니다: {rows}")

    def test_item_letter_change_is_caught(self):
        """마 → 바 처럼 획 수가 같은 글자도 잡아야 한다.

        칸별 잉크의 양만 세던 판에서 실제로 놓쳤다. 높이별 유무를 비트로
        쌓도록 고쳐서 잡는다.
        """
        after = list(BEFORE)
        after[10] = BEFORE[10].replace("마. 소요예산", "바. 소요예산")
        rows = changed(sc.compare(render(BEFORE), render(after)))
        self.assertEqual(len(rows), 1)
        first = min(start for start, _ in rows[0].spans)
        self.assertLess(first, 80, "줄 앞머리의 항목 번호를 짚어야 합니다")

    def test_amount_change_is_caught(self):
        after = list(BEFORE)
        after[10] = "   마. 소요예산: 금80,000원(금팔만원).  끝."
        rows = changed(sc.compare(render(BEFORE), render(after)))
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].spans)


def with_rules(lines, width=900, height=380, thickness=6, covers=1.0, **kwargs):
    """한글 창처럼 양옆에 세로 테두리가 있는 그림.

    `covers` 는 테두리가 그림 높이의 얼마를 차지하는지. 고른 자리가
    테두리보다 넓으면 1.0 이 안 된다 — 실사용에서 이게 문제였다.
    """
    shot = render(lines, width=width, height=height, **kwargs)
    grey = bytearray(shot.grey)
    for y in range(int(height * covers)):
        for x in list(range(thickness)) + list(range(width - thickness, width)):
            grey[y * width + x] = 90
    return sc.Shot(width, height, bytes(grey))


@unittest.skipUnless(WINDOWS, "화면 비교는 윈도우에서만 됩니다")
class VerticalRules(unittest.TestCase):
    """세로로 이어지는 선이 있으면 글줄 찾기가 통째로 무너진다.

    한글 창에는 쪽 테두리와 창 테두리가 세로로 끝까지 이어진다. 그 칸
    때문에 모든 가로줄에 잉크가 있게 되어 문서 전체가 글줄 하나로 뭉치고,
    달라진 곳을 문서만 한 상자 하나로 표시해 아무것도 못 알아보게 된다.

    실사용에서 처음 써 보셨을 때 바로 이것 때문에 "아무것도 표시되지
    않는다" 가 됐다. 표는 세로선이 더 많으니 그대로 두면 늘 이렇다.
    """

    def test_rules_are_found(self):
        found = with_rules(BEFORE).rules
        self.assertTrue(found)
        self.assertLessEqual(max(found), 899)
        self.assertIn(0, found)

    def test_borders_shorter_than_the_pick_are_still_found(self):
        """고른 자리가 테두리보다 넓어도 찾아야 한다.

        처음에는 "그림 높이의 80% 넘게 어두운 칸" 으로 쟀다. 그랬더니
        테두리가 고른 자리의 72~79% 만 차지할 때 그냥 지나가 버렸고,
        글줄이 통째로 뭉쳐 상자가 문서만 해졌다. 실사용에서 그렇게 나왔다.
        이제는 '끊기지 않고 이어진 길이' 로 재므로 비율과 무관하다.
        """
        for covers in (1.0, 0.79, 0.72, 0.5, 0.25):
            with self.subTest(covers=covers):
                shot = with_rules(BEFORE, height=500, covers=covers)
                self.assertTrue(shot.rules, "테두리를 못 찾았습니다")
                self.assertEqual(len(sc.bands(shot)), len(BEFORE),
                                 "글줄이 뭉쳤습니다")

    def test_marks_stay_about_one_line_tall(self):
        """상자는 고쳐진 글자에 붙어야지 문서를 감싸면 안 된다.

        보기 싫다는 말씀이 있었고, 실제로는 글줄 뭉침의 증상이었다.
        """
        after = list(BEFORE)
        after[4] = ("1. 관련: 예시중학교-2949(2026. 5. 14., "
                    "“2026 학교교육계획”)호")
        for covers in (1.0, 0.72):
            with self.subTest(covers=covers):
                a = with_rules(BEFORE, height=500, covers=covers)
                b = with_rules(after, height=500, covers=covers)
                for mark in changed(sc.compare(a, b)):
                    self.assertLess(mark.bottom - mark.top, 40,
                                    "글줄 하나보다 훨씬 큽니다")

    def test_lines_are_still_counted_right(self):
        self.assertEqual(len(sc.bands(with_rules(BEFORE))), len(BEFORE))

    def test_the_answer_matches_the_borderless_case(self):
        after = list(BEFORE)
        after[4] = ("1. 관련: 예시중학교-2949(2026. 5. 14., "
                    "“2026 학교교육계획”)호")
        plain = changed(sc.compare(render(BEFORE), render(after)))
        ruled = changed(sc.compare(with_rules(BEFORE), with_rules(after)))
        self.assertEqual([(c.state, c.top, c.bottom, c.spans) for c in plain],
                         [(c.state, c.top, c.bottom, c.spans) for c in ruled])

    def test_marks_never_swallow_the_whole_picture(self):
        """상자가 그림 높이만큼 커지면 표시가 아니라 테두리다."""
        after = list(BEFORE)
        after[4] = ("1. 관련: 예시중학교-2949(2026. 5. 14., "
                    "“2026 학교교육계획”)호")
        shot = with_rules(after)
        for mark in changed(sc.compare(with_rules(BEFORE), shot)):
            with self.subTest(mark=mark):
                self.assertLess(mark.bottom - mark.top, shot.height // 3,
                                "글줄 하나보다 훨씬 큽니다. 글줄이 뭉쳤습니다.")

    def test_same_content_with_rules_is_quiet(self):
        rows = sc.compare(with_rules(BEFORE, left=12), with_rules(BEFORE, left=45))
        self.assertEqual(changed(rows), [])

    def test_a_short_pick_keeps_its_letters(self):
        """한 줄만 바짝 잘라 골라도 글자가 살아 있어야 한다."""
        shot = render(BEFORE[:1], width=300, height=24, step=24)
        self.assertEqual(shot.rules, frozenset(), "글자를 선으로 봤습니다")
        self.assertTrue(sc.bands(shot), "글줄이 사라졌습니다")

    def test_it_backs_off_when_everything_looks_like_a_rule(self):
        """다 지워질 판이면 잘못 짚은 것이다. 그대로 두고 넘어간다.

        선만 있는 그림(표 눈금만 걸린 자리 따위)을 만나면 잉크가 하나도
        안 남아 글줄을 못 찾는다. 그럴 바엔 거르지 않는 편이 낫다.
        """
        width, height = 80, 100
        grey = bytearray([255] * (width * height))
        for y in range(height):                 # 세로선 세 개뿐인 그림
            for x in (10, 11, 40, 41, 70, 71):
                grey[y * width + x] = 60
        shot = sc.Shot(width, height, bytes(grey))
        self.assertEqual(shot.rules, frozenset(),
                         "다 지워 놓고 글줄이 없다고 하면 안 됩니다")


def pane(lines, pad_left=40, pad_top=30, extra_right=0, extra_bottom=0,
         paper_width=760, paper_height=360, zoom=1.0):
    """한글 문서비교 창 한 쪽 흉내.

    회색 바탕 위에 흰 종이가 있고, 아래에 상태표시줄, 옆에 스크롤바가
    붙는다. 창은 늘 이 모양이라 종이를 찾아낼 수 있다.
    """
    paper_width = int(paper_width * zoom)
    paper_height = int(paper_height * zoom)
    doc = render(lines, width=paper_width, height=paper_height,
                 size=int(-15 * zoom), step=int(30 * zoom))
    width = pad_left + paper_width + 20 + extra_right
    height = pad_top + paper_height + 26 + extra_bottom
    grey = bytearray([128] * (width * height))          # 종이 바깥 회색 바탕
    for y in range(paper_height):
        start = (pad_top + y) * width + pad_left
        grey[start:start + paper_width] = doc.grey[y * paper_width:
                                                   (y + 1) * paper_width]
    for y in range(pad_top, pad_top + paper_height):    # 종이 테두리 선
        grey[y * width + pad_left - 1] = 60
        grey[y * width + pad_left + paper_width] = 60
    for y in range(height - 24, height - 20):           # 상태표시줄 글자
        for x in range(10, width - 10, 3):
            grey[y * width + x] = 40
    for y in range(pad_top, pad_top + 120):             # 스크롤바 손잡이
        for x in range(width - 14, width - 4):
            grey[y * width + x] = 90
    return sc.Shot(width, height, bytes(grey))


@unittest.skipUnless(WINDOWS, "화면 비교는 윈도우에서만 됩니다")
class Paper(unittest.TestCase):
    """문서비교 창에서 흰 종이만 잘라낸다.

    창은 늘 같은 모양이다 — 종이 바깥은 회색이고, 아래에 상태표시줄,
    옆에 스크롤바가 붙는다. 그 부속들이 견주는 대상에 들어가면 공문
    내용이 아닌데도 표시가 뜬다. 실제로 상태표시줄에 상자가 쳐졌다.
    """

    def test_the_paper_is_found(self):
        cut = sc.crop_to_paper(pane(BEFORE))
        self.assertEqual((cut.width, cut.height), (760, 360))
        self.assertEqual(len(sc.bands(cut)), len(BEFORE))

    def test_the_same_paper_comes_out_however_you_drag(self):
        """대충 끌어도 같은 자리가 잘려야 한다. 손으로 끄는 범위는 매번 다르다."""
        sizes = set()
        for args in ({}, {"pad_left": 110, "pad_top": 70,
                          "extra_right": 60, "extra_bottom": 90},
                     {"extra_right": 120}, {"pad_top": 200, "extra_bottom": 260}):
            cut = sc.crop_to_paper(pane(BEFORE, **args))
            sizes.add((cut.width, cut.height))
        self.assertEqual(len(sizes), 1, f"자른 크기가 제각각입니다: {sizes}")

    def test_window_furniture_never_reaches_the_comparison(self):
        """상태표시줄과 스크롤바는 공문이 아니다."""
        after = list(BEFORE)
        after[4] = ("1. 관련: 예시중학교-2949(2026. 5. 14., "
                    "“2026 학교교육계획”)호")
        one, two = sc.prepare(pane(BEFORE), pane(after, pad_left=130,
                                                 pad_top=90, extra_right=80))
        marks = changed(sc.compare(one, two))
        self.assertEqual(len(marks), 1, f"창 부속까지 잡혔습니다: {marks}")
        # 스크롤바가 있던 자리는 잘려 나가 아예 없다
        self.assertLess(marks[0].bottom, two.height)

    def test_dragging_differently_gives_the_same_answer(self):
        after = list(BEFORE)
        after[4] = ("1. 관련: 예시중학교-2949(2026. 5. 14., "
                    "“2026 학교교육계획”)호")
        answers = set()
        for one, two in (({}, {}),
                         ({}, {"pad_left": 130, "pad_top": 90, "extra_right": 80}),
                         ({"pad_left": 150, "extra_bottom": 80}, {})):
            a, b = sc.prepare(pane(BEFORE, **one), pane(after, **two))
            marks = changed(sc.compare(a, b))
            answers.add(tuple((m.state, tuple(m.spans)) for m in marks))
        self.assertEqual(len(answers), 1, f"끄는 범위마다 답이 다릅니다: {answers}")

    def test_a_different_zoom_is_refused(self):
        """배율이 다르면 글자가 다르게 그려져 온 문서가 바뀐 것처럼 나온다."""
        with self.assertRaises(sc.ScreenError) as caught:
            sc.prepare(pane(BEFORE), pane(BEFORE, zoom=1.25))
        self.assertIn("배율", str(caught.exception))

    def test_a_wider_paper_at_the_same_zoom_is_fine(self):
        """종이가 넓은 것과 배율이 다른 것은 다르다. 글자 크기가 같으면 통과."""
        sc.prepare(pane(BEFORE, paper_width=760), pane(BEFORE, paper_width=900))

    def test_a_narrow_drag_does_not_look_like_a_different_zoom(self):
        """끌어낸 자리가 종이보다 좁으면 종이가 잘린다.

        예전에는 그 잘린 폭을 종이 너비로 알고 배율이 다르다고 했다.
        다른 컴퓨터에서 실제로 난 오류다. 글줄 높이로 재면 흔들리지 않는다.
        """
        full = pane(BEFORE)
        def clip(shot, left, right):
            width = shot.width - left - right
            rows = [shot.grey[y * shot.width + left:
                              (y + 1) * shot.width - right]
                    for y in range(shot.height)]
            return sc.Shot(width, shot.height, b"".join(rows))
        for one, two in ((60, 0), (0, 60), (60, 120), (100, 40)):
            with self.subTest(one=one, two=two):
                sc.prepare(clip(full, one, 0), clip(full, 0, two))

    def test_a_plain_white_shot_loses_nothing(self):
        """문서비교 창이 아니라 흰 바탕만 찍었을 때.

        온통 흰색이면 그림 전체가 종이로 잡힌다. 바깥 여백만 깎일 뿐
        글은 하나도 잃지 않아야 한다.
        """
        plain = render(BEFORE)
        cut = sc.crop_to_paper(plain)
        self.assertEqual(len(sc.bands(cut)), len(BEFORE), "글줄을 잃었습니다")
        self.assertEqual(cut.width, plain.width)

    def test_nothing_bright_enough_is_left_alone(self):
        """밝은 데가 없으면 종이를 찾은 것이 아니다. 그대로 둔다."""
        dark = sc.Shot(200, 200, bytes([90] * (200 * 200)))
        self.assertIs(sc.crop_to_paper(dark), dark)
        one, two = sc.prepare(dark, dark)
        self.assertIs(one, dark)


class Privacy(unittest.TestCase):
    """찍은 화면이 어디에도 남지 않아야 한다.

    화면에 무엇이 있을지 프로그램은 알 수 없다. 공문 폴더의 파일과 달리
    이용자가 읽어도 된다고 정해 준 것이 아니다. 셋 다 빠져도 프로그램은
    멀쩡히 돌아서 알아채기 어렵다.
    """

    SOURCE = (ROOT / "screen_compare.py").read_text(encoding="utf-8")

    def test_it_never_touches_the_disk(self):
        for forbidden in ("open(", "write_text", "write_bytes", "tempfile",
                          "NamedTemporary", "mkstemp", "shutil"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.SOURCE,
                                 f"찍은 화면이 디스크로 나갈 길이 생겼습니다: {forbidden}")

    def test_it_never_touches_the_store(self):
        for forbidden in ("import store", "sqlite3", "import app"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.SOURCE)

    def test_it_never_sends_anything_out(self):
        for forbidden in ("urllib", "http", "socket", "requests"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.SOURCE)

    def test_errors_do_not_carry_what_was_captured(self):
        """예외 메시지는 오류기록.txt 와 안내창에 그대로 나간다."""
        change = sc.Change(sc.EDITED, 10, 20, [(3, 9)])
        self.assertNotIn("grey", repr(change))
        shot = sc.Shot(2, 2, bytes([0, 1, 2, 3]))
        self.assertNotIn("grey", repr(shot))

    def test_a_too_small_pick_is_refused_before_capturing(self):
        with self.assertRaises(sc.ScreenError):
            sc.capture(0, 0, 2, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
