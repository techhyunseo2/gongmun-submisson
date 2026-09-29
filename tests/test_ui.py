"""ui.html 의 눈에 안 보이는 규칙들.

CSS 한 줄이 사라져도 화면은 그럭저럭 나오기 때문에 알아채기 어렵다.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

HTML = (ROOT / "ui.html").read_text(encoding="utf-8")


def z_of(selector: str) -> int:
    """그 선택자 규칙 안의 z-index 값."""
    pattern = re.escape(selector) + r"\s*\{[^}]*?z-index\s*:\s*(\d+)"
    found = re.search(pattern, HTML, re.S)
    assert found, f"{selector} 에 z-index 가 없습니다"
    return int(found.group(1))


class Checkbox(unittest.TestCase):
    """네모는 작게 두되 누르는 자리는 넓혀야 한다.

    좁으면 옆을 눌러 미리보기가 열려서, 여러 건을 골라 한꺼번에 처리할 때
    번번이 방해가 된다. 브라우저에서 15px 네모 / 23px 판정(1.53배)을 확인했다.
    """

    def test_hit_area_is_widened(self):
        self.assertRegex(
            HTML, r"\.pick::before\s*\{[^}]*inset\s*:\s*-\d+px",
            ".pick::before 로 누르는 자리를 넓혀 두어야 합니다")

    def test_visible_size_unchanged(self):
        """사용자가 요청한 것은 판정 범위만 넓히는 것이었다."""
        found = re.search(r"\.pick\s*\{[^}]*?width\s*:\s*(\d+)px", HTML, re.S)
        self.assertIsNotNone(found)
        self.assertEqual(int(found.group(1)), 15, "보이는 네모 크기는 그대로 둡니다")

    def test_hit_area_is_about_one_and_a_half(self):
        inset = int(re.search(r"\.pick::before\s*\{[^}]*inset\s*:\s*-(\d+)px",
                              HTML, re.S).group(1))
        ratio = (15 + inset * 2) / 15
        self.assertGreater(ratio, 1.3, f"{ratio:.2f}배 — 너무 좁습니다")
        self.assertLess(ratio, 1.8, f"{ratio:.2f}배 — 옆 칸을 가로챕니다")

    def test_checkmark_still_uses_after(self):
        """::after 는 체크 표시가 쓴다. 판정 범위는 ::before 로 넓힌다."""
        self.assertIn('.pick[aria-checked="true"]::after', HTML)


class Layering(unittest.TestCase):
    """고른 건수를 알리는 검은 막대가 미리보기를 가리면 안 된다.

    공문 내용을 확인하면서 고르는 흐름이라, 막대가 위로 오면 정작 읽어야
    할 내용이 가려진다.
    """

    def test_panel_sits_above_the_selection_bar(self):
        self.assertGreater(z_of("aside"), z_of(".picked"),
                           "미리보기 패널이 검은 막대보다 위여야 합니다")

    def test_scrim_sits_above_the_selection_bar(self):
        self.assertGreater(z_of(".scrim"), z_of(".picked"),
                           "가림막이 검은 막대보다 위여야 합니다")

    def test_panel_sits_above_its_own_scrim(self):
        self.assertGreater(z_of("aside"), z_of(".scrim"))

    def test_toast_stays_on_top(self):
        """패널을 열어 둔 채 기한을 바꿔도 알림이 보여야 한다."""
        self.assertGreater(z_of("#toast"), z_of("aside"),
                           "알림이 패널 뒤로 숨습니다")


class DocumentPreview(unittest.TestCase):
    """미리보기는 글자를 늘어놓는 대신 문서 모양 그대로 보여 준다.

    한글 문서는 파일 안에 든 첫 쪽 그림, PDF 는 브라우저 뷰어를 쓴다.
    그림을 못 꺼내는 문서도 있으므로 글자 미리보기로 물러나는 길이
    반드시 살아 있어야 한다 — 없으면 빈 칸만 남는다.
    """

    def test_hangul_asks_for_the_embedded_image(self):
        self.assertIn('src="/api/preview-image?id=${id}"', HTML)

    def test_pdf_uses_the_browser_viewer(self):
        self.assertIn('class="pdfview" src="/api/file?id=${id}"', HTML)

    def test_a_broken_image_falls_back_to_text(self):
        self.assertIn("onerror=\"this.parentNode.classList.add('noimg')\"", HTML)
        for rule in (".pagewrap.noimg .pageview{display:none}",
                     ".pagewrap.noimg .pagefallback{display:block}"):
            with self.subTest(rule=rule):
                self.assertIn(rule, HTML, "그림이 없을 때 글자로 물러나지 못합니다")

    def test_text_view_is_still_reachable(self):
        """글자를 복사해야 할 때가 있다. 돌아가는 길을 막으면 안 된다."""
        self.assertIn("글자만 보기", HTML)
        self.assertIn("문서 그대로 보기", HTML)

    def test_switching_view_keeps_the_file_you_were_reading(self):
        """첨부를 보다 보기를 바꿨는데 본문으로 튕기면 안 된다."""
        self.assertIn("openPanel(id, viewingFile)", HTML)

    def test_only_the_first_page_is_promised(self):
        self.assertIn("문서에 저장된 첫 쪽이며", HTML,
                      "한 쪽만 보인다는 것을 알려야 합니다")


class PeekAtClippedText(unittest.TestCase):
    """자리가 모자라 잘린 글은 전문을 볼 길이 있어야 한다.

    브라우저 기본 title 풍선을 쓰지 않는다 — 뜨기까지 1초 넘게 걸리고,
    화면 끝에서 잘리며, 어디에 뜰지 우리가 정할 수 없다.
    """

    def test_there_is_a_place_to_show_it(self):
        self.assertIn('id="peek"', HTML)
        self.assertIn('role="tooltip"', HTML)

    def test_hidden_actually_hides_it(self):
        self.assertIn("#peek[hidden]{display:none}", HTML)

    def test_it_flips_up_when_the_bottom_is_tight(self):
        self.assertIn("if (top + size.height > room.h - PEEK_EDGE)", HTML)
        self.assertIn("const above = box.top - size.height - PEEK_GAP", HTML)

    def test_it_is_pushed_in_from_the_right_and_left(self):
        self.assertIn("if (left + size.width > room.w - PEEK_EDGE)", HTML)
        self.assertIn("if (left < PEEK_EDGE) left = PEEK_EDGE", HTML)

    def test_it_only_shows_when_the_text_is_really_cut(self):
        """다 보이는 글에 쪽지가 뜨면 가리기만 한다."""
        self.assertIn("function _isClipped", HTML)
        self.assertIn("el.scrollWidth > el.clientWidth + 1", HTML)
        self.assertIn("if (_isClipped(el)) showPeek(el)", HTML)

    def test_text_we_cut_ourselves_is_compared_by_the_full_value(self):
        """CSS 가 자른 것과 우리가 잘라 넣은 것은 재는 법이 다르다."""
        self.assertIn("if (el.dataset.full) return el.dataset.full !== el.textContent", HTML)

    def test_every_clipped_spot_is_marked(self):
        for spot in ('class="folder" id="folder" data-peek',      # 폴더 줄
                     'class="name" data-peek',                    # 공문 제목
                     'class="meta" data-peek data-full=',         # 기관·파일 이름
                     'class="nm" data-peek'):                     # 딸린 문서
            with self.subTest(spot=spot):
                self.assertIn(spot, HTML)

    def test_it_goes_away_when_the_page_scrolls(self):
        """스크롤하면 쪽지만 제자리에 남아 엉뚱한 곳을 가리킨다."""
        self.assertIn('window.addEventListener("scroll", hidePeek, true)', HTML)

    def test_keyboard_users_get_it_too(self):
        self.assertIn('document.addEventListener("focusin"', HTML)


class KindBadge(unittest.TestCase):
    """유형표를 왼쪽 세로줄과 같은 색의 작은 라운드 박스로."""

    def test_it_takes_the_same_colour_as_the_left_rule(self):
        self.assertIn("const tone = CAT_COLOR[doc.category]", HTML)
        self.assertIn('style="border-left-color:${tone}"', HTML)
        self.assertIn('style="--kind-ink:${tone}"', HTML)

    def test_it_is_a_rounded_box(self):
        kind = HTML[HTML.index("  .kind{"):]
        kind = kind[:kind.index("}")]
        self.assertIn("border-radius:999px", kind)
        self.assertIn("padding:", kind)
        self.assertIn("border:1px solid", kind)

    def test_the_type_is_still_written_out(self):
        """색만으로 뜻을 전하면 색을 구별하기 어려운 분이 읽지 못한다."""
        self.assertIn('<span class="kind" style="--kind-ink:${tone}">${cats[doc.category]}</span>',
                      HTML)

    def test_there_is_a_fallback_where_color_mix_is_unknown(self):
        self.assertIn("@supports not (background: color-mix", HTML)


class DoneFromTheList(unittest.TestCase):
    """목록에서 바로 처리하는 단추."""

    def test_the_button_is_there(self):
        self.assertIn('class="done-btn"', HTML)
        self.assertIn('aria-pressed="${doc.done}"', HTML)

    def test_clicking_it_does_not_open_the_preview(self):
        """줄 전체가 미리보기를 여는 단추다. 막지 않으면 같이 열린다."""
        block = HTML[HTML.index('list.querySelectorAll(".done-btn")'):]
        block = block[:block.index("_bindPickedBar")]
        self.assertIn("event.stopPropagation()", block)

    def test_it_toggles_both_ways(self):
        block = HTML[HTML.index('list.querySelectorAll(".done-btn")'):]
        block = block[:block.index("_bindPickedBar")]
        self.assertIn("const was = doc.done", block)
        self.assertIn("done: !was", block)

    def test_the_whole_bundle_moves_together(self):
        """본문만 처리하고 첨부가 남으면 목록에 반쪽이 떠 있게 된다."""
        block = HTML[HTML.index('list.querySelectorAll(".done-btn")'):]
        block = block[:block.index("_bindPickedBar")]
        self.assertIn("const members = (doc.members || []).map(m => m.id)", block)
        self.assertIn("members});", block)

    def test_it_can_be_pressed_by_keyboard(self):
        block = HTML[HTML.index('list.querySelectorAll(".done-btn")'):]
        block = block[:block.index("_bindPickedBar")]
        self.assertIn("el.onkeydown", block)

    def test_the_badge_and_button_have_fixed_lanes(self):
        """글자 수가 달라도 세로줄이 맞아야 목록이 정돈돼 보인다."""
        row = HTML[HTML.index("  .row{"):]
        row = row[:row.index("}")]
        self.assertIn("grid-template-columns:20px 58px 1fr 74px 30px", row)


class UndoingAMistake(unittest.TestCase):
    """실수로 처리 단추를 눌렀을 때 되돌아오는 길.

    예전에는 "처리한 것도 보기" 를 켜고, 목록에서 그 공문을 다시 찾고,
    열어서 맨 아래 단추를 눌러야 했다. 되돌릴 자리는 실수한 바로 그
    자리여야 한다 — 알림에 되돌리기를 함께 단다.
    """

    def _block(self, start, end):
        body = HTML[HTML.index(start):]
        return body[:body.index(end)]

    def test_the_toast_can_carry_an_undo(self):
        self.assertIn("function toast(text, undo)", HTML)
        self.assertIn('btn.className = "undo"', HTML)

    def test_it_waits_longer_when_there_is_something_to_undo(self):
        """2.2초는 실수를 알아채고 누르기에 짧다."""
        self.assertIn("undo ? 7000 : 2200", HTML)

    def test_the_toast_only_catches_clicks_when_it_has_a_button(self):
        """평소에는 알림이 클릭을 가로채면 뒤에 있는 목록을 못 쓴다."""
        self.assertIn("#toast{", HTML)
        toast = self._block("  #toast{", "}")
        self.assertIn("pointer-events:none", toast)
        self.assertIn("#toast.actionable{pointer-events:auto}", HTML)

    def test_ctrl_z_does_the_same(self):
        self.assertIn('e.key.toLowerCase() === "z" && _undo', HTML)
        self.assertIn("runUndo()", HTML)

    def test_typing_is_not_hijacked(self):
        """검색칸에서 Ctrl+Z 는 글자를 되돌리는 것이어야 한다."""
        self.assertIn('e.target.matches("input, textarea")', HTML)

    def test_undo_runs_only_once(self):
        """두 번 눌러 도로 처리해 버리면 더 헷갈린다."""
        run = self._block("async function runUndo()", "\n}")
        self.assertIn("_undo = null;", run)

    def test_every_way_of_marking_done_can_be_undone(self):
        for spot, tag in (('list.querySelectorAll(".done-btn")', "목록 단추"),
                          ('$("toggledone").onclick', "미리보기 단추"),
                          ("go.onclick = async () =>", "여러 건 한꺼번에")):
            with self.subTest(tag=tag):
                block = HTML[HTML.index(spot):]
                block = block[:block.index("render();") + 400]
                self.assertIn("async () => {", block, f"{tag}에 되돌리기가 없습니다")

    def test_the_shortcut_is_written_on_the_button(self):
        """단축키는 알려 주지 않으면 아무도 모른다."""
        self.assertIn("Ctrl+Z", HTML)


class BandPickButton(unittest.TestCase):
    """구간마다 있는 고르기 단추 — 링크가 아니라 단추로 보이게."""

    def test_it_no_longer_looks_like_a_link(self):
        band = HTML[HTML.index("  .bandpick{"):]
        band = band[:band.index("}")]
        self.assertNotIn("border-bottom:1px dashed", band,
                         "점선 밑줄이면 링크처럼 보여 눌러 볼 생각을 못 합니다")
        self.assertIn("border:1px solid", band)
        self.assertIn("border-radius:999px", band)

    def test_period_bands_say_period(self):
        self.assertIn('"모두 해제" : "이 기간 모두"', HTML)

    def test_pinned_and_done_are_not_periods(self):
        """고정·처리함은 기간이 아니다. 기간이라 하면 틀린 말이 된다."""
        self.assertIn('"모두 해제" : "이 구간 모두"', HTML)

    def test_it_shows_whether_it_is_on(self):
        self.assertIn('aria-pressed="${allPicked}"', HTML)
        self.assertIn('.bandpick[aria-pressed="true"]', HTML)


class ZoomingThePreview(unittest.TestCase):
    """미리보기 그림을 눌러 크게 보기.

    그림 원본은 724px 인데 패널은 480px 라 늘 줄여서 보여 준다. 글씨가
    작아 읽기 어려우므로 누르면 화면 가운데에 원본 크기로 띄운다.
    """

    def test_clicking_the_image_opens_it(self):
        self.assertRegex(HTML, r'e\.target\.closest\(["\']\.pageview["\']\)')
        self.assertIn("openZoom(shot.src)", HTML)

    def test_hidden_actually_hides_it(self):
        """class 규칙이 hidden 의 기본 스타일을 이긴다.

        이 줄이 빠지면 확대창이 처음부터 화면을 덮은 채로 뜬다.
        """
        self.assertIn(".zoomview[hidden]{display:none}", HTML)

    def test_it_sits_above_the_panel_but_below_the_toast(self):
        self.assertGreater(z_of(".zoomview"), z_of("aside"),
                           "패널 뒤에서 열리면 보이지 않습니다")
        self.assertGreater(z_of("#toast"), z_of(".zoomview"))

    def test_it_never_upscales_past_the_original(self):
        """원본보다 크게 늘리면 글씨가 뭉갠다. 키우는 뜻이 없어진다."""
        self.assertIn("max-width:min(724px, 94vw)", HTML)

    def test_escape_closes_the_zoom_first(self):
        """함께 닫히면 보던 공문을 다시 찾아 들어가야 한다."""
        self.assertIn('if (!$("zoom").hidden) return closeZoom();', HTML)

    def test_closing_lets_go_of_the_image(self):
        self.assertIn('removeAttribute("src")', HTML)

    def test_people_are_told_they_can_click(self):
        self.assertIn("그림을 누르면 크게 볼 수 있습니다", HTML)

    def test_the_box_really_exists_in_the_page(self):
        """글자만 맞춰 보면 정작 요소가 없어도 통과한다. 실제로 파싱해 본다.

        확대창은 패널 안이 아니라 body 바로 아래에 있어야 한다 — 패널
        안에 있으면 패널의 스크롤과 폭에 갇힌다.
        """
        from html.parser import HTMLParser

        class Finder(HTMLParser):
            def __init__(self):
                super().__init__()
                self.depth = []
                self.box = None
                self.has_image = False

            def handle_starttag(self, tag, attrs):
                got = dict(attrs)
                if got.get("id") == "zoom":
                    self.box = (got, list(self.depth))
                if tag == "img" and self.box and "zoom" in [
                        d.get("id", "") for _, d in self.depth]:
                    self.has_image = True
                if tag not in ("img", "br", "input", "meta", "link", "hr"):
                    self.depth.append((tag, got))

            def handle_endtag(self, tag):
                while self.depth and self.depth[-1][0] != tag:
                    self.depth.pop()
                if self.depth:
                    self.depth.pop()

        found = Finder()
        found.feed(HTML)
        self.assertIsNotNone(found.box, 'id="zoom" 요소가 없습니다')
        attrs, outer = found.box
        self.assertIn("hidden", attrs, "처음부터 열린 채로 뜹니다")
        self.assertEqual([t for t, _ in outer], ["html", "body"],
                         "확대창이 body 바로 아래에 있지 않습니다")
        self.assertTrue(found.has_image, "확대창 안에 그림 자리가 없습니다")


class FileRow(unittest.TestCase):
    """딸린 문서 목록 — 한 번 누르면 미리보기, 두 번 누르면 열기."""

    def test_double_click_opens_the_file(self):
        # 이름만 스치는 검사(assertIn("row.ondblclick"))는 ondblclickXXX 같은
        # 오타에도 통과한다. 실제로 걸리는 형태까지 본다.
        self.assertRegex(HTML, r"row\.ondblclick\s*=\s*async\s*\(\)\s*=>")
        self.assertIn('"/api/open?id=" + encodeURIComponent(row.dataset.file)', HTML)

    def test_single_click_still_previews(self):
        self.assertIn("row.onclick = () => openPanel(id, row.dataset.file)", HTML)

    def test_the_hint_tells_people_it_is_there(self):
        """알려 주지 않으면 아무도 두 번 눌러 보지 않는다."""
        self.assertIn("두 번 눌러 열기", HTML)


class TidyWarning(unittest.TestCase):
    """폴더 정리가 파일을 휴지통으로 보내게 됐다. 그렇게 말해야 한다."""

    def test_it_no_longer_claims_nothing_is_deleted(self):
        self.assertNotIn("파일을 지우지는 않습니다", HTML,
                         "이제 같은 파일은 휴지통으로 갑니다. 문구가 거짓이 됩니다")

    def test_the_count_is_shown_before_pressing(self):
        self.assertIn("휴지통으로 보냅니다", HTML)
        self.assertIn("휴지통에서 되돌릴 수 있습니다", HTML)

    def test_only_duplicates_stop_the_no_op_message(self):
        """옮길 것은 없고 지울 것만 있어도 '정리할 파일이 없습니다' 면 안 된다."""
        self.assertIn("if (!plan.moved && !plan.trashed)", HTML)

    def test_files_it_could_not_move_are_reported(self):
        """조용히 넘어가면 '눌러도 아무 일이 없다' 가 된다. 이번에 고친 증상이다."""
        self.assertIn("done.problems", HTML)
        self.assertIn("그대로 두었습니다", HTML)


if __name__ == "__main__":
    unittest.main(verbosity=2)
