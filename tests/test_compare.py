"""결재 전후 공문 비교.

공문을 기안하면 결재자가 말없이 고쳐서 결재하는 일이 흔하다. 무엇이
달라졌는지 눈으로 찾아야 했던 것을 프로그램이 짚어 준다.

여기 케이스들은 실제로 겪은 사례(따옴표와 '호' 한 글자가 붙은 것)에서
출발했다. 이런 변화는 두 문서를 나란히 놓고 봐도 잘 안 보인다.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import compare  # noqa: E402


def changed(rows):
    """바뀐 것으로 잡힌 줄만."""
    return [row for row in rows if row["state"] != compare.SAME]


def put(row):
    """그 줄에서 새로 들어온 글자들."""
    return "".join(s["text"] for s in (row["spans"] or [])
                   if s["kind"] == compare.PUT)


def cut(row):
    return "".join(s["text"] for s in (row["spans"] or [])
                   if s["kind"] == compare.CUT)


class RealCase(unittest.TestCase):
    """실제로 겪은 사례. 결재자가 따옴표를 씌우고 '호' 를 붙였다."""

    BEFORE = (
        "제목 (중)2026학년도 방과후학교(요리반) 물품 구매\n"
        "1. 관련: 예시중학교-2949(2026. 5. 14., 2026 학교교육계획)\n"
        "2. 2026학년도 방과후학교(요리반) 운영에 필요한 물품을 구매하고자 합니다.\n"
        "가. 일 시: 2026. 8. 24.(월) 7, 8교시\n"
        "마. 소요예산: 금75,000원(금칠만오천원). 끝."
    )
    AFTER = BEFORE.replace(
        "2026. 5. 14., 2026 학교교육계획)",
        "2026. 5. 14., “2026 학교교육계획”)호",
    )

    def test_only_the_edited_line_is_flagged(self):
        rows = changed(compare.compare_text(self.BEFORE, self.AFTER))
        self.assertEqual(len(rows), 1, "고친 줄 하나만 잡혀야 합니다")
        self.assertEqual(rows[0]["state"], compare.EDITED)

    def test_it_points_at_the_added_characters(self):
        row = changed(compare.compare_text(self.BEFORE, self.AFTER))[0]
        self.assertEqual(put(row), "“”호")
        self.assertEqual(cut(row), "", "지워진 글자는 없다")

    def test_untouched_lines_stay_quiet(self):
        rows = compare.compare_text(self.BEFORE, self.AFTER)
        self.assertEqual(sum(1 for r in rows if r["state"] == compare.SAME), 4)


class Edits(unittest.TestCase):

    def test_amount_change(self):
        rows = changed(compare.compare_text(
            "마. 소요예산: 금75,000원(금칠만오천원). 끝.",
            "마. 소요예산: 금80,000원(금팔만원). 끝."))
        self.assertEqual(len(rows), 1)
        self.assertIn("80", put(rows[0]))
        self.assertIn("75", cut(rows[0]))

    def test_inserted_line_does_not_flag_the_rest(self):
        before = "가. 일시\n나. 장소: 기술실\n다. 대상: 수강생 7명"
        after = "가. 일시\n나. 장소: 기술실\n다. 준비물: 앞치마\n라. 대상: 수강생 7명"
        rows = changed(compare.compare_text(before, after))
        states = [r["state"] for r in rows]
        self.assertIn(compare.ADDED, states)
        # 항목 번호가 밀린 것도 알려 준다. 그러나 앞의 두 줄은 건드리지 않는다.
        self.assertLessEqual(len(rows), 2, f"너무 많이 잡혔습니다: {rows}")

    def test_deleted_line(self):
        rows = changed(compare.compare_text("가. 일시\n나. 장소\n다. 대상",
                                            "가. 일시\n다. 대상"))
        self.assertEqual([r["state"] for r in rows], [compare.REMOVED])
        self.assertEqual(rows[0]["text"], "나. 장소")

    def test_rewritten_sentence_is_marked_whole(self):
        """통째로 다시 쓴 문장은 글자 단위로 쪼개지 않는다.

        쪼개면 '입'/'매' 같은 파편이 흩뿌려져 오히려 읽기 어려워진다.
        """
        before = "2. 위와 같이 구매하고자 합니다."
        after = "2. 아래와 같이 물품을 구입하고자 하오니 검토하여 주시기 바랍니다."
        row = changed(compare.compare_text(before, after))[0]
        self.assertEqual(put(row), after, "고친 줄 전체가 새 글로 표시돼야 합니다")
        self.assertEqual(len(row["spans"]), 2)

    def test_identical_text_has_nothing_to_say(self):
        rows = compare.compare_text(RealCase.BEFORE, RealCase.BEFORE)
        self.assertEqual(changed(rows), [])


class Guards(unittest.TestCase):
    """조용히 틀린 답을 주느니 못 하겠다고 말해야 하는 경우."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)

    def _write(self, name, text=""):
        path = self.tmp / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_different_formats_are_refused(self):
        """형식이 다르면 추출기가 줄을 다르게 끊어 전부 바뀐 것처럼 보인다."""
        a, b = self._write("기안.txt", "같은 글"), self._write("시행.md", "같은 글")
        with self.assertRaises(compare.CompareError) as caught:
            compare.compare_files(a, b)
        self.assertIn("같은 형식", str(caught.exception))

    def test_missing_file_is_refused(self):
        a = self._write("기안.txt", "글")
        with self.assertRaises(compare.CompareError):
            compare.compare_files(a, self.tmp / "없는파일.txt")

    def test_same_format_files_compare(self):
        a = self._write("기안.txt", "1. 관련: 계획\n2. 끝.")
        b = self._write("시행.txt", "1. 관련: “계획”호\n2. 끝.")
        result = compare.compare_files(a, b)
        self.assertEqual(result["changed"], 1)
        self.assertEqual(result["old"], "기안.txt")
        self.assertEqual(put(changed(result["rows"])[0]), "“”호")


if __name__ == "__main__":
    unittest.main(verbosity=2)
