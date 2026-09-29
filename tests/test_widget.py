"""위젯 설정 회귀 테스트 (창을 띄우지 않는 부분만).

tkinter 창이 필요한 부분은 CI 에서 띄우기 어려우므로, 창 없이 확인할 수
있는 규칙과 소스의 모양만 지킨다.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import widget  # noqa: E402


def _iss_section(name: str) -> str:
    """installer.iss 의 [절] 하나만 떼어 온다.

    주석에도 "[Icons]" 같은 말이 나오므로 줄 첫머리의 절 이름만 센다.
    """
    import re
    body = (ROOT / "installer.iss").read_text(encoding="utf-8")
    found = re.search(rf"^\[{name}\]\s*$(.*?)(?=^\[|\Z)", body, re.M | re.S)
    assert found, f"installer.iss 에 [{name}] 절이 없습니다"
    return found.group(1)


class Opacity(unittest.TestCase):

    def test_floor_keeps_the_widget_findable(self):
        """더 흐려지면 위젯을 찾지 못해 오른쪽 버튼도 못 누른다."""
        self.assertEqual(widget.clamp_opacity(0.1), widget.OPACITY_MIN)
        self.assertEqual(widget.clamp_opacity(0), widget.OPACITY_MIN)
        self.assertEqual(widget.clamp_opacity(-5), widget.OPACITY_MIN)

    def test_ceiling(self):
        self.assertEqual(widget.clamp_opacity(1.4), 1.0)

    def test_passes_through_normal_values(self):
        for value in (0.5, 0.7, 0.96, 1.0):
            with self.subTest(value=value):
                self.assertEqual(widget.clamp_opacity(value), value)

    def test_broken_config_does_not_crash(self):
        """설정 파일이 손상돼도 뜨기는 해야 한다."""
        for junk in (None, "", "밝게", [], {}):
            with self.subTest(junk=junk):
                self.assertEqual(widget.clamp_opacity(junk), 1.0)

    def test_floor_is_actually_usable(self):
        self.assertGreaterEqual(widget.OPACITY_MIN, 0.4,
                                "이보다 흐리면 위젯이 사실상 안 보인다")


class GlyphFlow(unittest.TestCase):
    """자주 쓰는 문자를 늘어놓는 방식.

    예전에는 여섯 개마다 줄을 잘랐다. 한 글자짜리만 담아 두면 오른쪽이
    절반 넘게 비었고(320px 중 150px 가량), grid 는 열 너비를 모든 줄이
    나눠 쓰기 때문에 아래에 긴 것이 하나 있으면 위쪽 줄까지 그만큼
    벌어져 빈자리가 생겼다.
    """

    def setUp(self):
        self.source = (ROOT / "widget.py").read_text(encoding="utf-8")
        block = self.source[self.source.index("glyphs = list(self.config.get"):]
        self.block = block[:block.index("담아 둔 글")]

    def test_it_no_longer_cuts_every_six(self):
        for count in ("i // 6", "i % 6"):
            with self.subTest(count=count):
                self.assertNotIn(count, self.block,
                                 "아직 개수로 줄을 자르고 있습니다")

    def test_the_width_decides_where_the_line_breaks(self):
        self.assertIn("used + span > GLYPH_ROW_WIDTH", self.block)

    def test_the_width_is_measured_not_guessed(self):
        """여백과 테두리가 몇 px 인지는 tk 판과 화면 배율에 따라 다르다.

        숫자로 적어 두면 어긋난 만큼 마지막 칸이 오른쪽 벽을 넘어 잘린다.
        같은 차림의 칸을 하나 만들어 실제 요청 폭을 재야 한다.
        """
        self.assertIn("probe.winfo_reqwidth()", self.block)
        self.assertIn("probe.destroy()", self.block, "재고 나면 치워야 합니다")

    def test_the_gap_between_cells_is_counted(self):
        """칸 사이 간격도 줄 폭을 먹는다.

        빠뜨리면 한 줄에 여럿 놓일수록 간격이 쌓여(아홉 개면 36px) 줄
        끝이 창 밖으로 밀려난다. 실제로 그렇게 잘렸다.
        """
        self.assertIn("probe.winfo_reqwidth() + GLYPH_GAP", self.block)
        self.assertIn("padx=(0, GLYPH_GAP)", self.block,
                      "세는 간격과 실제로 벌리는 간격이 같아야 합니다")

    def test_each_line_is_its_own_frame(self):
        """grid 로 두면 긴 항목 하나가 다른 줄까지 벌려 놓는다."""
        self.assertNotIn(".grid(", self.block, "줄마다 따로 배치해야 합니다")
        self.assertIn('line = tk.Frame(grid, bg=PAPER)', self.block)
        self.assertIn('cell.pack(side="left"', self.block)

    def test_the_usable_width_follows_the_widget(self):
        """위젯 폭이 바뀌어도 따라가야 한다. 숫자를 박아 두면 어긋난다."""
        self.assertIn("GLYPH_ROW_WIDTH = WIDTH - 12 * 2", self.source)
        self.assertEqual(widget.GLYPH_ROW_WIDTH, widget.WIDTH - 24)

    def test_no_line_can_overflow_the_widget(self):
        """실제로 배치해 보고 어느 줄도 벽을 넘지 않는지 확인한다.

        소스만 훑으면 셈이 틀린 것은 잡지 못한다. 여기서 창을 하나 띄우되
        화면에는 내보내지 않는다(withdraw). 화면이 없는 곳에서는 건너뛴다.
        """
        import tkinter as tk

        try:
            root = tk.Tk()
        except tk.TclError as exc:            # 화면 없는 CI
            self.skipTest(f"화면이 없습니다: {exc}")
        root.withdraw()
        try:
            from tkinter import font as tkfont
            f_row = tkfont.Font(family="맑은 고딕", size=9)
            grid = tk.Frame(root)
            probe = tk.Label(grid, font=f_row, padx=7, pady=3, highlightthickness=1)

            # 한 글자짜리와 긴 것을 섞는다 — 실제로 잘렸던 구성이다
            glyphs = (["○", "※", "℃", "→", "·", "①", "②", "③", "㈜", "√"]
                      + list("asdfg") + ["ga", "sasdasd", "제출기한", "담당자"])
            widths, used = [], 0
            for text in glyphs:
                probe.config(text=widget._one_line(text, 6))
                span = probe.winfo_reqwidth() + widget.GLYPH_GAP
                if not widths or used + span > widget.GLYPH_ROW_WIDTH:
                    widths.append(0)
                    used = 0
                used += span
                widths[-1] = used

            for i, line in enumerate(widths, 1):
                with self.subTest(line=i):
                    self.assertLessEqual(
                        line, widget.GLYPH_ROW_WIDTH,
                        f"{i}번째 줄이 {line - widget.GLYPH_ROW_WIDTH}px 넘칩니다")
            # 넘치지만 않으면 되는 게 아니라, 남는 자리도 적어야 뜻이 있다
            self.assertGreater(max(widths), widget.GLYPH_ROW_WIDTH * 0.8,
                               "폭을 채우지 못하고 있습니다")
        finally:
            root.destroy()


class QuickBar(unittest.TestCase):
    """복사한 글 담아 두기 + 자주 쓰는 특수문자 고정."""

    def setUp(self):
        self.source = (ROOT / "widget.py").read_text(encoding="utf-8")

    def test_one_line_flattens_and_trims(self):
        self.assertEqual(widget._one_line("가\n나  다", 10), "가 나 다")
        self.assertEqual(widget._one_line("x" * 50, 5), "xxxx…")

    def test_stash_and_glyphs_are_persisted(self):
        """담아 둔 글과 특수문자 배치는 껐다 켜도 남아야 한다(config.json)."""
        for key in ('"clips"', '"glyphs"', '"quickbar_open"'):
            with self.subTest(key=key):
                self.assertIn(key, self.source)
        stash = self.source[self.source.index("def _stash_clipboard"):]
        stash = stash[:stash.index("\n    def ", 10)]
        self.assertIn("save_config(self.config)", stash)
        self.assertIn("del clips[CLIP_MAX:]", stash, "오래된 것부터 밀어내야 한다")

    def test_order_can_be_edited(self):
        """저장한 텍스트와 특수문자의 자리를 바꿀 수 있어야 한다."""
        move = self.source[self.source.index("def _move_clip"):]
        move = move[:move.index("\n    def ", 10)]
        self.assertIn("clips.insert(there, clips.pop(here))", move)
        # 특수문자는 줄 편집기의 줄 순서가 곧 배치 순서다
        editor = self.source[self.source.index("def _edit_glyphs"):]
        editor = editor[:editor.index("\n    def ", 10)]
        self.assertIn("splitlines()", editor)
        self.assertIn("줄 순서가 곧 배치 순서", self.source)

    def test_click_copies_to_clipboard(self):
        copy = self.source[self.source.index("def _copy_text"):]
        copy = copy[:copy.index("\n    @staticmethod")]
        self.assertIn("clipboard_clear", copy)
        self.assertIn("clipboard_append", copy)


class ToolDrawer(unittest.TestCase):
    """도구 서랍 — 등록한 프로그램·폴더·파일·웹 주소를 눌러 연다."""

    def setUp(self):
        self.source = (ROOT / "widget.py").read_text(encoding="utf-8")

    def _block(self, name):
        block = self.source[self.source.index(f"def {name}"):]
        return block[:block.index("\n    def ", 10)]

    def test_launcher_button_in_header_with_a_tip(self):
        self.assertIn('self._draw_tools, "도구 서랍"', self.source)

    def test_icon_is_a_three_by_three_grid(self):
        block = self._block("_draw_tools")
        self.assertIn("range(3)", block)
        self.assertIn("create_rectangle", block)
        self.assertIn("SLATE if on else SOFT", block, "켜지면 칸이 차야 합니다")

    def test_registrations_are_persisted(self):
        for key in ('"tools"', '"tools_open"'):
            with self.subTest(key=key):
                self.assertIn(key, self.source)
        block = self._block("_edit_tools")
        self.assertIn("save_config(self.config)", block)
        for field in ('"name"', '"path"', '"icon"'):
            with self.subTest(field=field):
                self.assertIn(field, block)

    def test_order_can_be_reordered(self):
        block = self._block("_edit_tools")
        self.assertIn("self._tool_rows.insert(j, self._tool_rows.pop(i))", block)
        self.assertIn("줄 순서가 곧 서랍의 배치 순서", self.source)

    def test_clicking_a_tile_opens_the_target(self):
        block = self._block("_open_tool")
        self.assertIn("open_in_os", block)
        self.assertIn("webbrowser.open", block)   # 웹 주소도 연다

    def test_a_folder_can_be_picked_not_just_typed(self):
        """윈도우 파일 고르기 창으로는 폴더를 집을 수 없다.

        예전에는 "찾기" 가 파일만 골라서, 폴더를 등록하려면 경로를 손으로
        쳐야 했다. 자주 여는 것은 오히려 폴더 쪽이다.
        """
        block = self._block("_pick_tool_path")
        self.assertIn("askdirectory", block)
        self.assertIn("askopenfilename", block)
        self.assertIn('self._foot_button(r, "폴더"', self.source)
        self.assertIn("self._pick_tool_path(ep, folder=True)", self.source)

    def test_missing_target_does_not_crash(self):
        block = self._block("_open_tool")
        self.assertIn("spot.exists()", block)

    def test_blank_icon_falls_back_to_the_program_own_icon(self):
        """이모지를 안 넣으면 그 프로그램·폴더의 실제 아이콘을 뽑아 쓴다."""
        self.assertIn("def _win_file_icon", self.source)
        self.assertIn("SHGetFileInfoW", self.source)
        self.assertIn("DrawIconEx", self.source)
        tile = self._block("_tool_tile")
        self.assertIn("_tool_icon_image", tile)
        # 사용자 이모지가 있으면 그게 먼저, 없을 때만 실제 아이콘
        self.assertIn("None if custom else self._tool_icon_image", tile)
        self.assertIn("name[:1]", tile, "그것마저 없으면 별명 첫 글자")

    def test_icon_extraction_never_breaks_the_drawer(self):
        block = self._block("_tool_icon_image")
        self.assertIn("except Exception", block)
        self.assertIn('sys.platform != "win32"', block)
        self.assertIn("self._icon_cache[key] = image", block)  # None 도 캐시

    def test_all_drawers_close_cleanly_and_reflow(self):
        """세 서랍(클립보드·도구·결재 비교)이 같은 방식으로 열고 닫힌다.
        닫으면 하단부까지 사라지고, 하나를 닫으면 아래 것이 올라온다."""
        block = self._block("_render_drawers")
        self.assertIn("self.quick, self.tools, self.compare", block)
        self.assertIn("drawer.pack_forget()", block)
        # 매번 전부 뗐다가 열린 것만 순서대로 다시 붙인다
        self.assertLess(block.index("pack_forget"), block.index('self.quick.pack(fill="x")'))
        self.assertLess(block.index('self.quick.pack(fill="x")'),
                        block.index('self.tools.pack(fill="x")'))
        self.assertLess(block.index('self.tools.pack(fill="x")'),
                        block.index('self.compare.pack(fill="x")'))
        # 서랍을 미리 깔아 두지 않는다 (빈 자리가 남던 원인)
        build = self._block("_build")
        for pre in ("self.tools.pack(", "self.compare.pack("):
            self.assertNotIn(pre, build)


class CompareDrawer(unittest.TestCase):
    """결재 전후 비교 — 다른 도구처럼 머리말 아이콘을 누르면 서랍이 열린다."""

    NOTE = ("결재 창의 '이력보기' 탭에서 활용 가능하며 픽셀 단위로 결재 "
            "문서 전후를 비교하여 줍니다. 결재 문서의 내용은 읽지 못하며 "
            "픽셀이 변경된 부분만 감지하기 때문에 오차가 있을 수 있습니다.")

    def setUp(self):
        self.source = (ROOT / "widget.py").read_text(encoding="utf-8")

    def _block(self, name):
        block = self.source[self.source.index(f"def {name}"):]
        return block[:block.index("\n    def ", 10)]

    def test_header_icon_toggles_a_drawer_now(self):
        self.assertIn('self._draw_compare, "결재 전후 비교"', self.source)
        self.assertIn("self._toggle_compare", self.source)
        self.assertIn('"compare_open"', self.source)

    def test_drawer_carries_the_exact_guidance_text(self):
        # 사용자가 그대로 정한 문구다. 다듬지 말 것.
        self.assertEqual(widget.COMPARE_NOTE, self.NOTE)
        self.assertIn("COMPARE_NOTE", self._block("_build_compare"))

    def test_a_crop_button_runs_the_original_compare(self):
        block = self._block("_build_compare")
        self.assertIn("_draw_crop", block)
        self.assertIn("self.compare_screens()", block)
        crop = self._block("_draw_crop")
        self.assertIn("create_line", crop)


class Wording(unittest.TestCase):
    """사용자가 직접 정한 문구. 업데이트 때 되돌리지 말 것.

    이 문구는 사용자가 커밋 6499304 에서 손수 고친 것이다. "더 나은 표현"
    으로 바꾸지 말고 그대로 둔다. 1.7.2 부터는 투명도 슬라이더가 머리말
    바로 아래로 옮겨졌고, 이 문구는 그 슬라이더의 설명풍선으로 산다.
    """

    HEADING = "최대 50%까지 투명도를 조절할 수 있습니다"

    def setUp(self):
        self.source = (ROOT / "widget.py").read_text(encoding="utf-8")

    def test_slider_heading_is_untouched(self):
        self.assertIn(
            self.HEADING, self.source,
            "슬라이더 설명풍선 문구는 사용자가 정한 것입니다. "
            f'"{self.HEADING}" 그대로 두세요.')

    def test_heading_matches_the_actual_floor(self):
        """문구의 50% 와 OPACITY_MIN 이 어긋나면 거짓말이 된다."""
        floor = round(widget.OPACITY_MIN * 100)
        self.assertIn(f"{floor}%", self.HEADING,
                      f"OPACITY_MIN 을 {floor}% 로 바꿨으면 머리말도 함께 "
                      "고치고, 이 검사의 HEADING 도 같이 고쳐 주세요.")


class Menu(unittest.TestCase):

    def setUp(self):
        self.source = (ROOT / "widget.py").read_text(encoding="utf-8")

    def test_fixed_opacity_presets_are_gone(self):
        """세 단계 고정값 대신 손잡이로 조절한다."""
        for gone in ("선명하게", "조금 투명하게", "많이 투명하게"):
            with self.subTest(label=gone):
                self.assertNotIn(gone, self.source,
                                 f'메뉴에서 "{gone}" 를 뺐어야 합니다')

    def test_opacity_slider_is_inline_not_in_the_menu(self):
        """투명도는 머리말 아래 슬라이더로 바로 조절한다. 메뉴 항목은 없앴다."""
        self.assertNotIn("투명도 조절", self.source, "메뉴 항목이 남아 있습니다")
        self.assertIn("def _draw_opacity_slider", self.source)
        self.assertIn("def _drag_opacity", self.source)

    def test_right_click_menu_is_only_update_and_version(self):
        """나머지는 모두 머리말 아이콘·슬라이더·폴더 박스로 옮겼다."""
        block = self.source[self.source.index("def _menu"):]
        block = block[:block.index("\n    def ", 10)]
        self.assertIn("업데이트 확인", block)
        self.assertIn("버전 {VERSION}", block)
        for gone in ("항상 위에 두기", "공문 폴더", "결재 전후 비교",
                     "자동 실행", "전체 화면 열기", "커스텀 클립보드"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, block, f'메뉴에 "{gone}" 가 남아 있습니다')


class HeaderControls(unittest.TestCase):
    """우클릭 메뉴에 있던 것들을 머리말 아이콘·슬라이더로 옮겼다."""

    def setUp(self):
        self.source = (ROOT / "widget.py").read_text(encoding="utf-8")

    def test_three_icon_buttons_with_tips(self):
        for maker in ('self._draw_ontop, "항상 위에 두기"',
                      'self._draw_compare, "결재 전후 비교"',
                      'self._draw_clip, "커스텀 클립보드"'):
            with self.subTest(maker=maker):
                self.assertIn(maker, self.source)

    def test_ontop_icon_is_stacked_pages_with_a_fillable_front(self):
        """압정이 아니라, 페이지가 겹친 모양. 맨 앞 장이 차 있으면 켜짐."""
        block = self.source[self.source.index("def _draw_ontop"):]
        block = block[:block.index("\n    def ", 10)]
        self.assertIn("create_rectangle", block)
        self.assertIn("SLATE if on else PAPER", block, "맨 앞 장의 채움으로 상태를 표시해야 합니다")
        self.assertNotIn("바늘", block, "압정 그림이 남아 있습니다")

    def test_every_header_button_shows_a_tip(self):
        """아이콘에 마우스를 올리면 무슨 기능인지 떠야 한다."""
        for fn in ("def _icon_button", "def _text_button"):
            block = self.source[self.source.index(fn):]
            block = block[:block.index("\n    def ", 10)]
            self.assertIn("_tip_schedule", block, f"{fn} 에 설명풍선이 없습니다")
        # ✕ 와 — 도 _text_button 으로 만들어 풍선이 붙는다
        self.assertIn('self._text_button("✕", "닫기"', self.source)
        self.assertIn('self._text_button("—", "접기"', self.source)

    def test_compare_icon_is_split_green_and_red(self):
        block = self.source[self.source.index("def _draw_compare"):]
        block = block[:block.index("\n    def ", 10)]
        self.assertIn("MOSS", block)
        self.assertIn("SEAL", block)

    def test_folder_is_a_rounded_box_that_brightens_on_hover(self):
        block = self.source[self.source.index("def _paint_folder"):]
        block = block[:block.index("\n    def ", 10)]
        self.assertIn("_round_rect", block)
        self.assertIn("GLOW if self._folder_hover", block)

    def test_opacity_row_shares_a_line_with_the_folder_box(self):
        """슬라이더는 절반만 쓰고, 남은 자리를 폴더 경로 박스가 채운다.

        따로 폴더 단추는 두지 않는다 — 폴더 박스를 눌러서 확인·열기·바꾸기.
        """
        build = self.source[self.source.index("def _build"):]
        build = build[:build.index("\n    def ", 10)]
        self.assertIn('self.opacity_slider = tk.Canvas(self.opacity_row', build)
        self.assertIn('width=40', build, "슬라이더 폭을 작게 고정해야 폴더 박스가 넓어집니다")
        self.assertIn('self.folderchip = tk.Canvas(self.opacity_row', build,
                      "폴더 박스가 투명도 줄과 같은 줄에 있어야 합니다")
        self.assertNotIn('"폴더 확인"', build)
        self.assertNotIn('"폴더 변경"', build)
        # "처리할 것 N건" 요약은 폴더 박스 다음, 목록 바로 위에 온다
        self.assertLess(build.index("self.folderchip"), build.index("self.summary ="))
        self.assertLess(build.index("self.summary ="), build.index("self.body ="))

    def test_folder_path_is_trimmed_to_fit_by_pixels(self):
        self.assertIn('_fit_text("폴더  " + short', self.source)

        class FakeFont:
            def measure(self, s):
                return len(s) * 7

        short = widget._fit_text("D:/아주/긴/폴더/경로/공문 정리함/공문", FakeFont(), 70)
        self.assertTrue(short.endswith("…"))
        self.assertLessEqual(FakeFont().measure(short), 70)
        # 짧으면 그대로 둔다
        self.assertEqual(widget._fit_text("공문", FakeFont(), 300), "공문")


class RowMenu(unittest.TestCase):
    """공문 한 줄에서 오른쪽 버튼 — 고정·폴더 열기·문서 바로 열기.

    tkinter 창을 실제로 띄우는 부분은 CI 에서 믿을 수 없으므로(파일 머리말
    참고), 오른쪽 버튼이 걸려 있는지와 두 메뉴가 겹쳐 뜨지 않는지만
    소스로 확인한다.
    """

    def setUp(self):
        self.source = (ROOT / "widget.py").read_text(encoding="utf-8")

    def _block(self, name):
        block = self.source[self.source.index(f"def {name}"):]
        return block[:block.index("\n    def ", 10)]

    def test_row_is_bound_to_right_click(self):
        self.assertIn('bind("<Button-3>", lambda e, d=doc: self._row_menu(e, d))',
                      self.source)

    def test_pinning_stays_in_the_menu(self):
        """1.7.6 에서 넣은 고정 기능이 파일 열기에 밀려나면 안 된다."""
        block = self._block("_row_menu")
        self.assertIn("맨 위에 고정", block)
        self.assertIn("self._set_pinned(doc, not pinned)", block)

    def test_row_menu_does_not_stack_with_widget_menu(self):
        """위젯 전체 메뉴도 오른쪽 버튼(root 의 <Button-3>)을 쓴다.

        줄 메뉴가 "break" 를 돌려주지 않으면 위젯 전체 메뉴까지 겹쳐 뜬다.
        """
        self.assertIn('return "break"', self._block("_row_menu"))

    def test_folder_open_and_document_open_share_open_in_os(self):
        block = self._block("_row_menu")
        self.assertIn('command=lambda: open_in_os(folder)', block)
        self.assertIn('command=lambda p=member["path"]: open_in_os(Path(p))', block)

    def test_missing_files_are_left_out(self):
        """옮기거나 지운 파일을 눌러 오류창이 뜨면 안 된다."""
        self.assertIn('Path(m["path"]).exists()', self._block("_row_menu"))


class TipStaysOnScreen(unittest.TestCase):
    """쪽지가 화면 밖으로 나가지 않게 자리를 고른다.

    위젯은 화면 가장자리에 붙여 두는 일이 많다(기본 자리부터 오른쪽
    위다). 손질이 없으면 잘린 글을 보려고 마우스를 올렸는데 쪽지마저
    반쯤 잘린 채 뜬다.
    """

    AREA = (0, 0, 1920, 1032)        # 작업 표시줄을 뺀 범위
    SIZE = (220, 60)                 # 쪽지 크기

    def test_it_sits_below_when_there_is_room(self):
        got = widget.fit_tip((800, 400), self.SIZE, self.AREA, above=330)
        self.assertEqual(got, (800, 400))

    def test_it_flips_above_when_the_bottom_is_tight(self):
        """아래가 좁으면 글자 위로 넘긴다."""
        got = widget.fit_tip((800, 1000), self.SIZE, self.AREA, above=900)
        self.assertEqual(got, (800, 900))

    def test_it_is_pushed_in_from_the_right_wall(self):
        """위젯을 오른쪽 끝에 붙여 두었을 때가 바로 이 경우다."""
        x, _ = widget.fit_tip((1850, 400), self.SIZE, self.AREA, above=330)
        self.assertLessEqual(x + self.SIZE[0], 1920)

    def test_it_is_pushed_in_from_the_left_wall(self):
        x, _ = widget.fit_tip((-40, 400), self.SIZE, self.AREA, above=330)
        self.assertGreaterEqual(x, 0)

    def test_it_stays_on_screen_when_both_sides_are_tight(self):
        """위아래 모두 좁아도 화면 안에는 있어야 한다."""
        _, y = widget.fit_tip((800, 1020), self.SIZE, self.AREA, above=-30)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(y + self.SIZE[1], 1032)

    def test_long_text_wraps_instead_of_running_off(self):
        self.assertLessEqual(widget.TIP_WRAP, widget.WIDTH,
                             "쪽지가 위젯보다 넓으면 가장자리에서 삐져나옵니다")


class ClipRowKeepsItsButtons(unittest.TestCase):
    """담아 둔 글이 길어도 오른쪽 단추가 밀려나지 않아야 한다.

    실사용에서 걸리셨다. 긴 글을 담아 두면 말줄임표가 붙은 글이 순서
    바꾸기(▴▾)와 지우기(✕)를 칸 밖으로 밀어내, 그 글을 지울 수가 없었다.
    원인이 둘이었다 — pack 순서(먼저 붙인 것이 공간을 먼저 가져간다)와,
    글자 수로 자른 것(한글은 영문보다 두 배 가까이 넓다).
    """

    def setUp(self):
        self.source = (ROOT / "widget.py").read_text(encoding="utf-8")
        block = self.source[self.source.index('tk.Label(q, text="담아 둔 글"'):]
        self.block = block[:block.index("다른 곳에서 복사한 뒤")]

    def test_the_buttons_are_packed_first(self):
        """글을 먼저 붙이면 긴 글이 단추를 밖으로 밀어낸다."""
        for mark in ('drop.pack(side="right")', 'down.pack(side="right")',
                     'up.pack(side="right")'):
            with self.subTest(mark=mark):
                self.assertLess(self.block.index(mark),
                                self.block.index('label.pack(side="left"'),
                                "단추를 글보다 먼저 붙여야 자리를 지킵니다")

    def test_the_text_is_cut_by_pixels_not_letters(self):
        self.assertIn("_fit_text(", self.block)
        self.assertNotIn("_one_line(text, 30)", self.block,
                         "글자 수로 자르면 한글이 든 글은 칸을 넘어섭니다")

    def test_the_button_width_is_measured(self):
        self.assertIn("self._clip_controls_width(box)", self.block)
        gauge = self.source[self.source.index("    def _clip_controls_width"):]
        gauge = gauge[:gauge.index("\n    def ", 10)]
        self.assertIn("gauge.update_idletasks()", gauge,
                      "재우지 않으면 요청 폭이 1px 로 나온다")
        self.assertIn("gauge.destroy()", gauge)

    def test_the_room_follows_the_widget_width(self):
        self.assertIn("CLIP_TEXT_WIDTH = WIDTH - 12 * 2 - 2 - 12", self.source)

    def test_long_text_really_fits_beside_the_buttons(self):
        """실제로 재 본다. 소스만 훑으면 셈이 틀린 것은 못 잡는다."""
        import tkinter as tk

        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"화면이 없습니다: {exc}")
        root.withdraw()
        try:
            from tkinter import font as tkfont
            f_small = tkfont.Font(family="맑은 고딕", size=8)
            box = tk.Frame(root)

            class Borrow:
                pass
            borrow = Borrow()
            borrow.f_small = f_small
            controls = widget.Widget._clip_controls_width(borrow, box)
            self.assertGreater(controls, 20, "단추 폭이 1px 로 나오고 있습니다")
            room = widget.CLIP_TEXT_WIDTH - controls

            for text in ("짧은 글",
                         "2026학년도 1학기 방과후학교 운영 계획 및 강사 채용 공고 안내 말씀드립니다",
                         "부산광역시교육청 교원인사과-12345 (본문) 2026학년도 하반기 운영 계획",
                         "a" * 80):
                with self.subTest(text=text[:16]):
                    shown = widget._fit_text(" ".join(text.split()), f_small, room)
                    self.assertLessEqual(
                        f_small.measure(shown), room,
                        "글이 단추 자리까지 넘어갑니다 — 지울 수가 없어집니다")
        finally:
            root.destroy()


class PeekOnClippedText(unittest.TestCase):
    """말줄임표로 잘린 글에만 쪽지를 건다."""

    def setUp(self):
        self.source = (ROOT / "widget.py").read_text(encoding="utf-8")
        block = self.source[self.source.index("    def _peek"):]
        self.block = block[:block.index("\n    def ", 10)]

    def test_nothing_is_shown_when_the_text_fits(self):
        """다 보이는 글에 쪽지가 뜨면 가리기만 한다."""
        self.assertIn('widget._peek_text = "" if full == shown.strip() else full',
                      self.block)

    def test_it_binds_only_once_per_widget(self):
        """폴더 줄은 마우스만 올려도 다시 그린다.

        그릴 때마다 걸면 바인딩이 쌓여 쪽지가 여러 번 뜬다.
        """
        self.assertIn('if getattr(widget, "_peek_bound", False):', self.block)
        self.assertIn("widget._peek_bound = True", self.block)

    def test_it_does_not_trample_other_handlers(self):
        """도구 타일은 이미 <Enter>/<Leave> 로 테두리를 밝힌다."""
        self.assertEqual(self.block.count('add="+"'), 2)

    def test_every_place_that_cuts_text_is_covered(self):
        """자르는 자리마다 들여다볼 길이 있어야 한다."""
        for spot in ("self._peek(cell, text, label)",          # 자주 쓰는 문자
                     "self._peek(label, text, shown)",         # 담아 둔 글
                     "self._peek(w, f\"{name} — {path}\"",      # 도구 타일
                     "self._peek(name, title, shown)",         # 공문 제목
                     "self._peek(c, str(self.folder)"):        # 폴더 줄
            with self.subTest(spot=spot):
                self.assertIn(spot, self.source)


class SnappingToEdges(unittest.TestCase):
    """벽 가까이 끌어다 놓으면 자석처럼 딱 붙는다.

    창 크기 320x400, 작업 영역은 작업 표시줄(아래 40px)을 뺀 범위로 둔다.
    """

    AREA = (0, 0, 1920, 1040)            # 왼쪽, 위, 오른쪽, 아래
    SIZE = (320, 400)

    def snap(self, x, y):
        return widget.snap_to_edge((x, y), self.SIZE, self.AREA)

    def test_near_the_right_wall_it_sticks(self):
        # 오른쪽 끝은 1920 - 320 = 1600
        self.assertEqual(self.snap(1595, 300), (1600, 300))
        self.assertEqual(self.snap(1610, 300), (1600, 300))

    def test_near_the_left_wall_it_sticks(self):
        self.assertEqual(self.snap(12, 300), (0, 300))
        self.assertEqual(self.snap(-8, 300), (0, 300))

    def test_away_from_the_wall_it_stays_put(self):
        """언제나 붙어 버리면 가운데에 두고 싶을 때 성가시다."""
        self.assertEqual(self.snap(800, 300), (800, 300))
        # 문턱(20px) 바로 바깥은 손이 가는 대로
        self.assertEqual(self.snap(21, 300), (21, 300))

    def test_the_top_and_bottom_snap_too(self):
        self.assertEqual(self.snap(800, 9), (800, 0))
        # 아래 끝은 1040 - 400 = 640
        self.assertEqual(self.snap(800, 635), (800, 640))

    def test_a_corner_snaps_on_both_sides_at_once(self):
        self.assertEqual(self.snap(1608, 12), (1600, 0))

    def test_it_never_hides_under_the_taskbar(self):
        """작업 영역을 쓰므로 아래에 붙여도 표시줄에 가리지 않는다.

        화면은 1080 이지만 작업 표시줄 40px 을 뺀 1040 이 바닥이다.
        화면 전체를 기준으로 삼으면 창 아랫부분이 표시줄 뒤로 들어간다.
        """
        _, y = self.snap(800, 645)          # 아래 벽에서 5px 떨어진 자리
        self.assertEqual(y + self.SIZE[1], 1040, "표시줄 위에 서야 합니다")
        self.assertLess(y + self.SIZE[1], 1080)

    def test_a_monitor_on_the_left_has_negative_coordinates(self):
        """왼쪽에 붙인 모니터는 좌표가 음수다. 그 모니터의 벽에도 붙어야 한다."""
        left_screen = (-1920, 0, 0, 1040)
        self.assertEqual(
            widget.snap_to_edge((-1912, 300), self.SIZE, left_screen), (-1920, 300))
        self.assertEqual(
            widget.snap_to_edge((-330, 300), self.SIZE, left_screen), (-320, 300))

    def test_the_collapsed_widget_snaps_by_its_own_height(self):
        """접으면 높이가 54 다. 펼쳤을 때 높이로 재면 허공에 뜬다."""
        _, y = widget.snap_to_edge((800, 980), (320, 54), self.AREA)
        self.assertEqual(y + 54, 1040)

    def test_the_distance_is_small_enough_to_aim_past(self):
        self.assertLessEqual(widget.SNAP_DISTANCE, 24,
                             "너무 넓으면 벽 근처에 자유롭게 둘 수 없습니다")

    def test_dragging_really_goes_through_the_snap(self):
        """셈만 시험하면 정작 끌 때 안 붙어도 통과한다.

        실제로 이 시험이 없을 때, 붙이는 줄을 통째로 빼도 전부 통과했다.
        """
        source = (ROOT / "widget.py").read_text(encoding="utf-8")
        block = source[source.index("    def _drag_move"):]
        block = block[:block.index("\n    def ", 10)]
        self.assertIn("snap_to_edge(where, size, area)", block,
                      "끌 때 붙이기를 거치지 않습니다")
        self.assertIn("self._work_area()", block)
        self.assertIn("winfo_height()", block,
                      "접었을 때와 펼쳤을 때 높이가 달라 실제로 재야 합니다")

    def test_it_gives_up_quietly_when_the_area_is_unknown(self):
        """작업 영역을 못 알아내도 창은 끌려야 한다.

        붙이기는 있으면 좋은 것이지, 없다고 창을 못 옮기게 될 일이 아니다.
        """
        source = (ROOT / "widget.py").read_text(encoding="utf-8")
        block = source[source.index("    def _work_area"):]
        block = block[:block.index("\n    def ", 10)]
        self.assertIn('sys.platform != "win32"', block)
        self.assertIn("except Exception", block)
        self.assertIn("return None", block)
        drag = source[source.index("    def _drag_move"):]
        drag = drag[:drag.index("\n    def ", 10)]
        self.assertIn("if area:", drag, "못 알아냈을 때를 살펴야 합니다")


class BringingItBack(unittest.TestCase):
    """가려지거나 화면 밖으로 나간 위젯을 되찾는 길.

    위젯은 테두리 없는 창이라 **작업 표시줄에 뜨지 않는다.** 바탕화면
    보기로 가려지면 되살릴 방법이 없었다 — 다시 실행해도 "이미 실행 중"
    이라는 말만 들었다. 실사용에서 갇히셨다.
    """

    BOUNDS = (0, 0, 1920, 1080)          # 모니터 한 대

    def test_a_place_on_screen_is_left_alone(self):
        self.assertEqual(widget.onto_screen((300, 300), self.BOUNDS), (300, 300))

    def test_off_to_the_right_comes_back(self):
        x, _ = widget.onto_screen((9000, 300), self.BOUNDS)
        self.assertEqual(x, 1920 - widget.WIDTH)

    def test_below_the_screen_comes_back(self):
        _, y = widget.onto_screen((300, 9000), self.BOUNDS)
        self.assertEqual(y, 1080 - 80)
        self.assertLess(y, 1080, "화면 안이어야 합니다")

    def test_above_and_left_comes_back(self):
        self.assertEqual(widget.onto_screen((-500, -500), self.BOUNDS), (0, 0))

    def test_a_second_monitor_on_the_left_is_still_screen(self):
        """모니터를 왼쪽에 붙이면 좌표가 음수다. 그걸 화면 밖으로 보면 안 된다."""
        wide = (-1920, 0, 3840, 1080)
        self.assertEqual(widget.onto_screen((-1500, 100), wide), (-1500, 100))

    def test_it_leaves_room_to_grab_the_widget(self):
        """맨 아래에 붙어도 머리말은 남아야 끌어서 옮길 수 있다."""
        _, y = widget.onto_screen((300, 9000), self.BOUNDS)
        self.assertLessEqual(y + 40, 1080, "잡을 자리가 없습니다")

    def test_running_again_tries_both_ways_to_bring_it_back(self):
        """다시 실행하는 것이 곧 되살리기여야 한다. **길이 둘이어야 한다.**

        `/api/show` 로 부탁하는 길은 상대가 그 길을 아는 판일 때만 듣는다.
        옛 버전이 돌고 있으면 404 가 나고, 다시 설치해도 파일만 바뀔 뿐
        이미 돌던 옛 프로세스는 그대로라 영영 낫지 않는다. 실제로 몇 분이
        지웠다 설치하기를 되풀이하셨다.

        창을 밖에서 직접 세우는 길은 상대가 어느 판이든 듣는다.
        """
        source = (ROOT / "widget.py").read_text(encoding="utf-8")
        start = source.index("running = running_port(")
        block = source[start:start + 900]
        self.assertIn("ask_to_surface(running)", block, "부탁하는 길이 없습니다")
        self.assertIn("raise_running_widget()", block, "직접 세우는 길이 없습니다")
        # 둘 다 실패했을 때만 안내창으로 물러난다
        self.assertLess(block.index("raise_running_widget()"),
                        block.index("_say_it_is_already_running"),
                        "되살려 보지도 않고 안내창부터 띄웁니다")

    def test_the_last_resort_notice_cannot_hide_behind_things(self):
        """되살리지 못했을 때의 안내창마저 숨으면 '아무 반응 없음' 이 된다."""
        source = (ROOT / "widget.py").read_text(encoding="utf-8")
        block = source[source.index("def _say_it_is_already_running"):]
        block = block[:block.index("\ndef ", 10)]
        self.assertIn('"-topmost", True', block, "안내창이 뒤로 숨을 수 있습니다")
        # 지웠다 다시 설치하기를 되풀이하시던 분들께 그럴 필요가 없다고
        # 알려 주는 것이 이 문구의 핵심이다.
        self.assertIn("지우고 다시 설치하실 필요는 없습니다", block)
        self.assertIn("작업 관리자", block)

    def test_raising_from_outside_needs_no_help_from_the_running_copy(self):
        """밖에서 세우는 길은 떠 있는 판의 협조에 기대면 안 된다."""
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        block = source[source.index("def raise_running_widget"):]
        block = block[:block.index("\n# SetWindowPos")]
        for needed in ("EnumWindows", "GetWindowTextW", "SetWindowPos",
                       "AttachThreadInput", "GetCurrentProcessId"):
            with self.subTest(needed=needed):
                self.assertIn(needed, block)
        # 우리 자신을 세우려 들면 안 된다
        self.assertIn("owner.value == ours", block)

    def test_the_signal_is_watched_on_the_main_thread(self):
        """tkinter 는 요청 스레드에서 만지면 안 된다.

        그래서 서버는 숫자만 올리고, 위젯이 메인 스레드에서 그 숫자를 본다.
        """
        source = (ROOT / "widget.py").read_text(encoding="utf-8")
        watch = source[source.index("def _watch_for_calls"):]
        watch = watch[:watch.index("\n    def ", 10)]
        self.assertIn("Handler.show_calls", watch)
        self.assertIn("self.root.after(", watch)

    def test_the_taskbar_button_is_claimed_but_the_old_ways_stay(self):
        """작업 표시줄 아이콘은 되살리는 길을 하나 더 늘리는 것이지,

        밖에서 창을 직접 세우는 기존 길(아주 오래된 판에도 듣는다)을
        치우는 게 아니다. 둘 다 있어야 한다.
        """
        source = (ROOT / "widget.py").read_text(encoding="utf-8")
        claim = source[source.index("def _claim_taskbar_button"):]
        claim = claim[:claim.index("\n    def _finish_taskbar_button")]
        self.assertIn("WS_EX_APPWINDOW", claim, "팝업 창은 이 스타일 없이는 안 뜬다")
        self.assertIn("withdraw", claim, "작업 표시줄은 다시 보일 때만 살핀다")
        self.assertIn("sys.platform != \"win32\"", claim, "다른 OS 에서 터지면 안 된다")
        # 되살리기 다른 길은 그대로 있어야 한다
        self.assertIn("raise_running_widget", source)
        self.assertIn("_say_it_is_already_running", source)
        # 숨겼다 띄운 뒤 테두리 없애기를 다시 걸어야 한다
        finish = source[source.index("def _finish_taskbar_button"):]
        finish = finish[:finish.index("\n    def ", 10)]
        self.assertIn("overrideredirect(True)", finish)

    def test_installer_leaves_the_original_app_alone(self):
        """기존 "공문 정리함"과는 따로 깔리는 앱이다. 그쪽 것을 건드리면 안 된다.

        같은 AppId 면 설치가 기존 앱을 덮어쓰고, 옛 이름의 바로가기·exe 를
        치우는 줄이 남아 있으면 기존 앱의 자동 실행이 조용히 사라진다.
        """
        iss = (ROOT / "installer.iss").read_text(encoding="utf-8-sig")
        self.assertNotIn("7C3F1E2A-9B41-4D6E-8A25-5F0C7D9E1B33", iss)
        for name in ("공문정리함.lnk", "공문정리함.bat", "공문정리함.exe", '"gongmun.exe"',
                     r"\.gongmun'"):
            with self.subTest(name=name):
                self.assertNotIn(name, iss)

    def test_installer_no_longer_offers_autorun(self):
        """설치할 때 자동 실행을 켜 주지 않는다.

        무심코 체크했다가 나중에 끄는 길을 못 찾는 일이 있었다. 시작
        프로그램은 사람마다 사정이 다르므로(느린 컴퓨터, 공용 컴퓨터)
        원하는 분만 사용설명서 11절대로 바로가기를 직접 넣게 한다.
        """
        # 설치 창의 체크 목록과, 그 체크가 만들던 바로가기 양쪽을 본다.
        # (주석에서 옛 기능을 설명하는 것은 그대로 두어야 하므로 절 단위로 본다)
        self.assertNotIn("startupicon", _iss_section("Tasks"),
                         "설치 창에 자동 실행 체크가 남아 있습니다")
        self.assertNotIn("{userstartup}", _iss_section("Icons"),
                         "설치할 때 시작 폴더에 바로가기를 만들고 있습니다")
        # 예전 판이 만들어 둔 바로가기는 업그레이드할 때 치운다
        self.assertIn("{userstartup}", _iss_section("InstallDelete"))

    def test_the_manual_still_shows_how_to_do_it_by_hand(self):
        """기능을 없앴으면 직접 하는 길은 더 또렷해야 한다."""
        manual = (ROOT / "사용설명서.txt").read_text(encoding="utf-8")
        self.assertIn("shell:startup", manual)
        self.assertNotIn('설치할 때 "컴퓨터를 켤 때 자동으로 띄우기" 를 체크하셨으면', manual,
                         "없앤 설치 옵션을 설명서가 아직 안내하고 있습니다")

    def test_uninstaller_asks_before_deleting_records(self):
        """설정·기록(.gongmun-submisson)은 물어보고, 기본은 남기는 쪽이어야 한다."""
        iss = (ROOT / "installer.iss").read_text(encoding="utf-8")
        self.assertIn(".gongmun-submisson", iss)
        self.assertIn("MB_DEFBUTTON2", iss, "기본 단추가 '아니오' 여야 실수로 안 지운다")
        self.assertIn("UninstallSilent", iss, "조용히 지울 때는 묻지 말고 남겨야 한다")

    def test_it_respects_the_always_on_top_setting(self):
        """잠깐 맨 위로 올리되, 꺼 두신 분에게는 되돌려 놓아야 한다."""
        source = (ROOT / "widget.py").read_text(encoding="utf-8")
        rise = source[source.index("    def surface(self):"):]
        rise = rise[:rise.index("\n    def ", 10)]
        self.assertIn("deiconify", rise)
        self.assertIn("_pull_onto_screen", rise)
        self.assertIn('on_top', rise)
        self.assertIn('"-topmost", False', rise)


if __name__ == "__main__":
    unittest.main(verbosity=2)
