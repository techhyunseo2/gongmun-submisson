"""화면 비교의 창 부분.

그림을 tkinter 가 읽을 수 있는 형태로 만드는 일과, 결과 머리말 문구를
지킨다. 드래그로 고르는 부분은 사람이 마우스를 움직여야 해서 여기서
시험하지 못한다 — 그 대신 창을 실제로 띄워 확인했다.
"""

from __future__ import annotations

import base64
import ctypes
import gc
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

WINDOWS = sys.platform == "win32"

if WINDOWS:
    import compare_window as cw
    import screen_compare as sc


def grey_shot(width=40, height=12, value=200):
    return sc.Shot(width, height, bytes([value]) * (width * height))


@unittest.skipUnless(WINDOWS, "화면 비교는 윈도우에서만 됩니다")
class Picture(unittest.TestCase):
    """Tk 는 base64 로 넘긴 PPM 을 못 읽는다. PNG 여야 한다.

    처음에 PPM 으로 만들었다가 `couldn't recognize image data` 로 막혔다.
    """

    def test_it_is_a_real_png(self):
        raw = base64.b64decode(cw._as_png(grey_shot()))
        self.assertEqual(raw[:8], bytes([137, 80, 78, 71, 13, 10, 26, 10]))
        self.assertEqual(raw[12:16], b"IHDR")
        self.assertTrue(raw.rstrip().endswith(b"IEND\xae\x42\x60\x82"))

    def test_the_size_survives(self):
        raw = base64.b64decode(cw._as_png(grey_shot(37, 19)))
        width, height = struct.unpack(">II", raw[16:24])
        self.assertEqual((width, height), (37, 19))

    def test_it_stays_one_grey_layer(self):
        """회색 한 겹이라야 자료가 3분의 1 이고, 빨강이 눈에 띈다."""
        raw = base64.b64decode(cw._as_png(grey_shot()))
        depth, colour = raw[24], raw[25]
        self.assertEqual((depth, colour), (8, 0), "8비트 회색 한 겹이어야 합니다")


@unittest.skipUnless(WINDOWS, "화면 비교는 윈도우에서만 됩니다")
class Headline(unittest.TestCase):
    """받는 분이 읽을 말이라 문구를 못박아 둔다."""

    def one(self, state):
        return sc.Change(state, 10, 24, [(5, 20)])

    def test_nothing_changed(self):
        said = cw._Result._headline([])
        self.assertIn("찾지 못했습니다", said)

    def test_counts_each_kind(self):
        said = cw._Result._headline([
            self.one(sc.EDITED), self.one(sc.EDITED),
            self.one(sc.ADDED), self.one(sc.REMOVED)])
        self.assertIn("고쳐진 곳 2", said)
        self.assertIn("새로 들어온 줄 1", said)
        self.assertIn("빠진 줄 1", said)

    def test_it_does_not_mention_kinds_that_did_not_happen(self):
        said = cw._Result._headline([self.one(sc.EDITED)])
        self.assertIn("고쳐진 곳 1", said)
        self.assertNotIn("빠진 줄", said)
        self.assertNotIn("새로 들어온 줄", said)


class _Nothing:
    """창 없이 고르기 로직만 돌리기 위한 허수아비.

    무엇을 물어도 또 다른 허수아비를 내놓고, 불러도 아무 일도 안 한다.
    그래서 캔버스·창·타이머를 흉내 내지 않아도 된다.
    """

    def __getattr__(self, name):
        child = _Nothing()
        setattr(self, name, child)
        return child

    def __call__(self, *args, **kwargs):
        return None


@unittest.skipUnless(WINDOWS, "화면 비교는 윈도우에서만 됩니다")
class PickedRegion(unittest.TestCase):
    """끌어낸 그 자리가 찍혀야 한다.

    화면 배율이 걸린 컴퓨터에서는 tkinter 가 보는 좌표와 윈도우가 보는
    좌표가 어긋난다. 섞어 쓰면 끌어낸 데가 아니라 엉뚱한 곳이 찍힌다 —
    다른 컴퓨터에서 실제로 그렇게 나왔다.
    """

    def drag(self, corners, tk_start=(10, 10)):
        """마우스를 그 자리에서 끌었다고 하고, 무엇을 찍으려 했는지 본다."""
        moves = list(corners)
        asked = []
        real = (cw.screen_compare.cursor_at, cw.screen_compare.capture)
        cw.screen_compare.cursor_at = lambda: moves.pop(0)
        cw.screen_compare.capture = lambda *box: asked.append(box)
        try:
            stand = _Nothing()
            stand.start = None
            stand.from_screen = None
            stand.picked = None
            press = _Nothing()
            press.x, press.y = tk_start
            cw._Picker._down(stand, press)
            cw._Picker._up(stand, None)
            cw._Picker.run(stand)
        finally:
            cw.screen_compare.cursor_at, cw.screen_compare.capture = real
        return asked

    def test_the_rectangle_is_the_one_the_mouse_drew(self):
        asked = self.drag([(300, 200), (900, 640)])
        self.assertEqual(asked, [(300, 200, 600, 440)])

    def test_dragging_up_and_left_works_too(self):
        asked = self.drag([(900, 640), (300, 200)])
        self.assertEqual(asked, [(300, 200, 600, 440)])

    def test_a_second_monitor_on_the_left_is_fine(self):
        """왼쪽에 붙인 모니터는 좌표가 음수다. 그대로 찍어야 한다."""
        asked = self.drag([(-1500, 100), (-900, 500)])
        self.assertEqual(asked, [(-1500, 100, 600, 400)])

    def test_the_tkinter_place_never_leaks_into_the_shot(self):
        """막 위에 사각형을 그리는 자리와 찍을 자리는 따로다."""
        one = self.drag([(300, 200), (900, 640)], tk_start=(10, 10))
        two = self.drag([(300, 200), (900, 640)], tk_start=(777, 555))
        self.assertEqual(one, two, "tkinter 좌표가 찍는 자리에 섞였습니다")


@unittest.skipUnless(WINDOWS, "화면 비교는 윈도우에서만 됩니다")
class HidingTheWidget(unittest.TestCase):
    """고르는 동안 위젯이 감춰져야 한다.

    위젯은 항상 위에 떠 있다. 그대로 두면 화면을 찍을 때 자기가 같이
    찍혀서, 결과 그림 한구석에 위젯이 박혀 나온다. 실사용에서 그랬다.
    """

    def setUp(self):
        self.log = []
        self.picks = [object(), object()]

        class FakePicker:
            def __init__(inner, root, message):
                self.log.append("고르기")

            def run(inner):
                return self.picks.pop(0) if self.picks else None

        self.real = (cw._Picker, cw._Result, cw.screen_compare.compare,
                     cw.screen_compare.prepare, cw._Notice)
        # 안내창도 바꿔 두지 않으면 진짜 창이 떠서 영원히 기다린다.
        class SaysYes:
            def __init__(inner, root, step):
                self.log.append("안내")

            def run(inner):
                return self.notice_says_yes

        self.notice_says_yes = True
        cw._Notice = SaysYes
        cw._Picker = FakePicker
        cw._Result = lambda root, shot, changes: self.log.append("결과")
        cw.screen_compare.compare = lambda before, after: []
        cw.screen_compare.prepare = lambda before, after: (before, after)
        self.addCleanup(self.restore)

    def restore(self):
        (cw._Picker, cw._Result, cw.screen_compare.compare,
         cw.screen_compare.prepare, cw._Notice) = self.real

    def test_hidden_before_picking_and_back_before_the_result(self):
        cw.run(None, lambda *_: None,
               hide=lambda: self.log.append("감춤"),
               show=lambda: self.log.append("되돌림"))
        self.assertEqual(self.log,
                         ["감춤", "안내", "고르기", "안내", "고르기",
                          "되돌림", "결과"])

    def test_it_comes_back_even_if_the_user_gives_up(self):
        """Esc 로 그만둬도 위젯이 사라진 채 남으면 안 된다."""
        self.picks = [None]
        cw.run(None, lambda *_: None,
               hide=lambda: self.log.append("감춤"),
               show=lambda: self.log.append("되돌림"))
        self.assertEqual(self.log, ["감춤", "안내", "고르기", "되돌림"])

    def test_it_comes_back_even_if_capturing_blows_up(self):
        def boom(root, message):
            raise cw.screen_compare.ScreenError("찍지 못했습니다")
        cw._Picker = boom
        said = []
        cw.run(None, lambda title, text: said.append(text),
               hide=lambda: self.log.append("감춤"),
               show=lambda: self.log.append("되돌림"))
        self.assertEqual(self.log, ["감춤", "안내", "되돌림"])
        self.assertTrue(said, "무엇이 잘못됐는지 알려 줘야 합니다")

    def test_saying_no_at_the_notice_stops_there(self):
        """안내창에서 그만두면 고르기까지 가지 않고, 위젯은 돌아온다."""
        self.notice_says_yes = False
        cw.run(None, lambda *_: None,
               hide=lambda: self.log.append("감춤"),
               show=lambda: self.log.append("되돌림"))
        self.assertEqual(self.log, ["감춤", "안내", "되돌림"])

    def test_the_widget_knows_how_to_hide_and_come_back(self):
        source = (ROOT / "widget.py").read_text(encoding="utf-8")
        self.assertIn("hide=self._hide_self", source)
        self.assertIn("show=self._show_self", source)
        # deiconify 는 창 꾸밈을 되돌려 놓는다. 다시 걸어 주지 않으면
        # 위젯에 제목 표시줄이 생기고 투명도가 풀린다.
        back = source[source.index("def _show_self"):]
        back = back[:back.index("\n    def ", 10)]
        for needed in ("deiconify", "overrideredirect", "-topmost",
                       "-alpha", "geometry"):
            with self.subTest(needed=needed):
                self.assertIn(needed, back)


@unittest.skipUnless(WINDOWS, "화면 비교는 윈도우에서만 됩니다")
class Notice(unittest.TestCase):
    """고르기 전에 뜨는 안내창.

    안내를 어두운 막 위에 얹었더니 모니터 두 대를 쓰시는 분들에게 글이
    반씩 잘렸다. 화면 전체의 한가운데가 곧 두 화면이 갈리는 자리이기
    때문이다. 선생님들 대부분이 두 대를 쓰신다.
    """

    def setUp(self):
        import tkinter as tk
        try:
            self.root = tk.Tk()
        except Exception as exc:            # noqa: BLE001 — 화면이 없는 환경
            self.skipTest(f"창을 띄울 수 없습니다: {exc}")
        self.root.withdraw()
        # 창을 지운 뒤 **메인 스레드에서** 조각까지 치운다. 안 그러면
        # 남은 조각이 나중에 다른 스레드(예: 시험용 HTTP 서버)에서
        # 수거되면서 `Tcl_AsyncDelete` 로 파이썬이 통째로 터진다.
        # 간헐적이라 CI 가 이따금 붉어진다.
        self.addCleanup(gc.collect)
        self.addCleanup(self.root.destroy)

    def open(self, step="① 원본(기안한 것) 쪽을 끌어 주세요"):
        notice = cw._Notice(self.root, step)
        self.root.update()
        self.addCleanup(lambda: notice.window.winfo_exists()
                        and notice.window.destroy())
        return notice

    def test_it_fits_inside_one_monitor(self):
        notice = self.open()
        left, top, width, height = cw._monitor_at(*sc.cursor_at())
        x, y = notice.window.winfo_x(), notice.window.winfo_y()
        wide, high = notice.window.winfo_width(), notice.window.winfo_height()
        self.assertGreaterEqual(x, left)
        self.assertGreaterEqual(y, top)
        self.assertLessEqual(x + wide, left + width)
        self.assertLessEqual(y + high, top + height)

    def test_it_never_straddles_the_seam_between_monitors(self):
        """화면 전체의 한가운데가 바로 두 화면이 갈리는 자리다."""
        notice = self.open()
        whole = cw._virtual_screen()
        seam = whole[0] + whole[2] // 2
        x, wide = notice.window.winfo_x(), notice.window.winfo_width()
        if whole[2] > 2000:                 # 모니터가 한 대뿐이면 볼 것이 없다
            self.assertFalse(x < seam < x + wide, "경계선을 가로지릅니다")

    def test_it_is_actually_visible(self):
        """부모(위젯)가 감춰진 채로 뜨므로 딸린 창으로 만들면 안 된다.

        `transient()` 를 쓰면 부모가 숨어 있을 때 이 창도 같이 숨는다.
        고르는 동안 위젯을 감추므로 안내창이 아예 안 뜨게 된다.
        """
        self.assertTrue(self.open().window.winfo_viewable())
        self.assertNotIn(".transient(", (ROOT / "compare_window.py")
                         .read_text(encoding="utf-8"),
                         "딸린 창으로 만들면 부모가 숨을 때 같이 숨습니다")

    def test_confirm_goes_ahead_and_giving_up_does_not(self):
        going = self.open()
        going._go()
        self.assertTrue(going.run())
        quitting = self.open()
        quitting.window.destroy()
        self.assertFalse(quitting.run())

    def test_it_says_how_to_drag_and_how_to_quit(self):
        import tkinter as tk
        notice = self.open()
        said = []

        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child, (tk.Label, tk.Button)):
                    said.append(child.cget("text"))
                walk(child)

        walk(notice.window)
        joined = " ".join(said)
        self.assertIn("좌우가 다 들어오게", joined)
        self.assertIn("비교할 수 없으므로", joined)
        self.assertIn("Esc", joined)
        self.assertIn("오른쪽 버튼", joined)
        self.assertIn("확인", joined)

    def test_the_veil_carries_no_words_any_more(self):
        """막 위의 글이 경계선에 걸리던 것이 애초의 문제였다."""
        picker = cw._Picker(self.root, "① 원본 쪽을 끌어 주세요")
        self.root.update()
        try:
            words = [item for item in picker.canvas.find_all()
                     if picker.canvas.type(item) == "text"]
        finally:
            picker.window.destroy()
        self.assertEqual(words, [], "막에 아직 글이 남아 있습니다")


@unittest.skipUnless(WINDOWS, "화면 비교는 윈도우에서만 됩니다")
class GivingUp(unittest.TestCase):
    """고르다 그만둘 길이 막히면 안 된다.

    Esc 가 안 듣는다는 말씀이 있었다. 테두리 없는 창은 윈도우가 키보드
    초점을 순순히 주지 않는데, 특히 위젯을 감춘 직후가 그렇다. 그래서
    초점을 확실히 가져오되, 초점과 무관한 길도 함께 둔다.
    """

    def setUp(self):
        import tkinter as tk
        try:
            self.root = tk.Tk()
        except Exception as exc:            # noqa: BLE001 — 화면이 없는 환경
            self.skipTest(f"창을 띄울 수 없습니다: {exc}")
        self.root.withdraw()
        # 창을 지운 뒤 **메인 스레드에서** 조각까지 치운다. 안 그러면
        # 남은 조각이 나중에 다른 스레드(예: 시험용 HTTP 서버)에서
        # 수거되면서 `Tcl_AsyncDelete` 로 파이썬이 통째로 터진다.
        # 간헐적이라 CI 가 이따금 붉어진다.
        self.addCleanup(gc.collect)
        self.addCleanup(self.root.destroy)

    def close_with(self, sequence):
        picker = cw._Picker(self.root, "① 원본 쪽을 끌어 주세요")
        self.root.update()
        picker.canvas.event_generate(sequence, when="now")
        self.root.update()
        alive = bool(picker.window.winfo_exists())
        if alive:
            picker.window.destroy()
        return not alive

    def test_escape_closes_it(self):
        self.assertTrue(self.close_with("<Escape>"), "Esc 가 듣지 않습니다")

    def test_the_right_button_closes_it_too(self):
        """키보드 초점이 없어도 듣는 길. Esc 가 막혔을 때의 대비다."""
        self.assertTrue(self.close_with("<Button-3>"),
                        "오른쪽 버튼이 듣지 않습니다")

    def test_it_takes_the_keyboard_focus(self):
        picker = cw._Picker(self.root, "① 원본 쪽을 끌어 주세요")
        self.root.update()
        try:
            front = ctypes.windll.user32.GetForegroundWindow()
            self.assertEqual(front, picker.window.winfo_id(),
                             "막이 앞에 서지 못했습니다")
            self.assertIsNotNone(picker.window.focus_get())
        finally:
            picker.window.destroy()


@unittest.skipUnless(WINDOWS, "화면 비교는 윈도우에서만 됩니다")
class Privacy(unittest.TestCase):
    """찍은 화면이 파일로 새지 않아야 한다. `screen_compare` 와 같은 규칙."""

    SOURCE = (ROOT / "compare_window.py").read_text(encoding="utf-8")

    def test_it_never_writes_the_capture_anywhere(self):
        for forbidden in ("open(", "write_text", "write_bytes", "tempfile",
                          "mkstemp", "urllib", "socket"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.SOURCE,
                                 f"찍은 화면이 나갈 길이 생겼습니다: {forbidden}")

    def test_the_veil_is_lifted_before_capturing(self):
        """막이 덮인 채로 찍으면 그 아래가 아니라 막이 찍힌다.

        `destroy()` 는 요청일 뿐이라, 창이 닫히기를 기다리는 것만으로는
        모자라다. 윈도우가 가려졌던 자리를 다시 그릴 틈까지 줘야 한다.
        """
        source = self.SOURCE
        wait = source.index("self.window.wait_window()")
        settle = source.index("time.sleep(SETTLE)")
        shoot = source.index("screen_compare.capture(")
        self.assertLess(wait, settle, "막을 걷기 전에 기다리고 있습니다")
        self.assertLess(settle, shoot, "화면이 다시 그려지기 전에 찍습니다")
        self.assertGreaterEqual(cw.SETTLE, 0.05, "기다리는 시간이 너무 짧습니다")

    def test_the_result_can_be_scrolled_both_ways(self):
        """실제로 찍은 화면은 창보다 넓다. 가로로도 움직일 수 있어야 한다.

        세로만 있으면 오른쪽에 그려진 빨간 상자를 영영 못 본다.
        """
        self.assertIn('orient="horizontal"', self.SOURCE)
        self.assertIn("xscrollcommand", self.SOURCE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
