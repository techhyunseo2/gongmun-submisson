"""일정 내보내기(.ics) 생성 회귀 테스트.

구글 캘린더가 파일을 가져와도 일정이 안 뜨던 일이 있었다. 원인은
종일 일정에 DTEND 가 없던 것. 그 형태를 여기서 지킨다.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import build_ics  # noqa: E402

DOC = {
    "id": "abc123",
    "filename": "붙임.hwpx",
    "title": "신규 강사 채용 계획",
    "deadline": "2026-09-10",
    "summary": "요약입니다",
}


class BuildIcs(unittest.TestCase):
    def test_all_day_event_has_a_matching_dtend(self):
        text = build_ics([DOC])
        self.assertIn("DTSTART;VALUE=DATE:20260910", text)
        # DTEND 가 없으면 구글 캘린더가 조용히 무시한다.
        self.assertIn("DTEND;VALUE=DATE:20260911", text)

    def test_title_has_no_status_prefix(self):
        text = build_ics([DOC])
        self.assertIn("SUMMARY:신규 강사 채용 계획", text)
        self.assertNotIn("[마감]", text)
        self.assertNotIn("[일정]", text)

    def test_uid_is_stable_and_from_the_file_id(self):
        self.assertIn("UID:abc123@gongmun-submisson", build_ics([DOC]))

    def test_file_ends_with_crlf(self):
        self.assertTrue(build_ics([DOC]).endswith("\r\n"))

    def test_doc_without_a_date_is_skipped(self):
        text = build_ics([{"id": "x", "filename": "f.hwpx", "title": "날짜 없음"}])
        self.assertNotIn("BEGIN:VEVENT", text)


if __name__ == "__main__":
    unittest.main()
