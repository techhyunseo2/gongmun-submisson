"""classify.py 회귀 테스트.

실제 공문에서 반복해서 틀렸던 지점(CLAUDE.md "날짜/기한 추출의 함정들")을
표본으로 고정해 둔다. 새 오탐을 고칠 때는 여기 케이스를 먼저 추가해
재현시킨 뒤 고치고, 나머지가 그대로인지 확인한다.

터미널 없이도 돌아가도록 표준 라이브러리만 쓴다.
    python -m unittest tests.test_classify      (저장소 루트에서)
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import classify  # noqa: E402

BASE = date(2026, 9, 2)


def deadline(body: str):
    return classify.analyze("파일명.pdf", body, BASE)["deadline"]


def result(body: str):
    return classify.analyze("파일명.pdf", body, BASE)


class ReferenceLines(unittest.TestCase):
    """다른 공문을 인용하는 줄의 날짜는 내 기한이 아니다."""

    def test_related_line_with_colon(self):
        body = (
            "제목\n      인사관리규정 일부개정 알림\n\n"
            "1. 관련: 교원인사과-14453(2026. 7. 31.)\n"
            "2. 인사관리규정을 붙임과 같이 개정하였음을 알려드립니다.\n"
        )
        self.assertIsNone(deadline(body))

    def test_related_block_subitems_leak(self):
        """1. 관련 아래 들여쓴 가./나. 인용 항목에 '제출'이 붙어 있어도
        그 문서 등록일자를 마감으로 잡으면 안 된다."""
        body = (
            "제목\n      학생 정서행동특성검사 시행 협조\n\n"
            "1. 관련\n"
            "  가. 학생건강증진과-9821(2026. 8. 5.) 정서행동특성검사 시행 계획\n"
            "  나. 학생건강증진과-10233(2026. 8. 20.) 검사 대상자 명단 제출 요청\n"
            "2. 위 검사 대상자 명단을 2026. 9. 30.까지 제출바랍니다.\n"
        )
        self.assertEqual(deadline(body), "2026-09-30")
        self.assertNotIn("2026-08-05", result(body)["all_dates"])
        self.assertNotIn("2026-08-20", result(body)["all_dates"])

    def test_inline_citation_next_to_real_deadline(self):
        """한 문장에 인용 날짜와 실제 마감이 같이 있으면 인용만 걸러낸다."""
        body = (
            "제목\n      방과후학교 운영계획 제출 안내\n\n"
            "1. 관련: 교육과정과-14453호(2026. 7. 31.) '자료 제출 요청'\n"
            "2. 운영계획을 2026. 9. 25.(금)까지 제출하여 주시기 바랍니다.\n"
        )
        self.assertEqual(deadline(body), "2026-09-25")

    def test_routing_line_receipt_date(self):
        """시행·접수 줄의 날짜(문서를 주고받은 날)는 마감이 아니다."""
        body = (
            "제목\n      2학기 자율동아리 계획 제출\n\n"
            "붙임 서식을 작성하여 2026. 9. 12.까지 제출바랍니다.\n"
            "시행 교육과정과-10755 (2026. 8. 24.)  접수 예시중학교-4971 (2026. 8. 25.)\n"
        )
        self.assertEqual(deadline(body), "2026-09-12")


class StaleAndEventDates(unittest.TestCase):

    def test_old_bylaw_date_not_deadline(self):
        """부칙의 오래된 시행일('2004. 3. 1.까지 인정한다')은 마감 후보에서 제외."""
        body = (
            "제목\n      인사관리규정 개정\n\n"
            "부칙 제2조(경과조치) 이 규정 시행 전 발령된 사항은 "
            "2004. 3. 1.까지 종전 규정에 따른다.\n"
        )
        self.assertIsNone(deadline(body))

    def test_duplicate_span_no_phantom_date(self):
        """'2004. 3. 1.'을 연도 없는 패턴이 '3. 1.'로 또 잡아 올해 날짜를
        만들어내면 안 된다."""
        body = "이 규정은 2004. 3. 1.부터 시행한다.\n"
        self.assertNotIn("2026-03-01", result(body)["all_dates"])
        self.assertNotIn("2027-03-01", result(body)["all_dates"])

    def test_range_takes_end_date(self):
        """'접수 기간: 9. 1. ~ 9. 5.' 는 끝 날짜가 마감."""
        body = (
            "제목\n      과학탐구대회 참가 접수\n\n"
            "접수 기간: 2026. 9. 1. ~ 2026. 9. 5.\n"
        )
        self.assertEqual(deadline(body), "2026-09-05")

    def test_deadline_and_event_same_sentence(self):
        """행사일과 마감일이 한 문장에 있으면 '까지' 앞의 날짜가 마감."""
        body = (
            "제목\n      학교폭력예방 연수 안내\n\n"
            "연수는 2026. 10. 5.(월) 실시하며, 참가 명단은 "
            "2026. 9. 20.까지 제출바랍니다.\n"
        )
        self.assertEqual(deadline(body), "2026-09-20")


class TitleExtraction(unittest.TestCase):

    def test_label_only_line_then_title(self):
        body = "수신 수신자 참조\n제목\n      진로체험 가정통신문 배부 안내\n\n1. 관련 ...\n"
        self.assertEqual(result(body)["title"], "진로체험 가정통신문 배부 안내")

    def test_org_name_not_title(self):
        body = "부산광역시서부교육지원청\n제목: 파견교사 선발 계획 알림\n"
        self.assertEqual(result(body)["title"], "파견교사 선발 계획 알림")


class Categories(unittest.TestCase):

    def test_submit(self):
        body = "제목\n      방과후학교 수요조사 결과 제출\n\n수요조사 결과를 2026. 9. 15.까지 회신 바랍니다.\n"
        self.assertEqual(result(body)["category"], "submit")

    def test_apply(self):
        body = "제목\n      과학탐구대회 공모 안내\n\n참가를 희망하는 학교는 공모에 응모하여 주시기 바랍니다.\n"
        self.assertEqual(result(body)["category"], "apply")

    def test_distribute(self):
        body = "제목\n      정서행동특성검사 가정통신문\n\n붙임 가정통신문을 학부모에게 배부하여 주시기 바랍니다.\n"
        self.assertEqual(result(body)["category"], "distribute")


if __name__ == "__main__":
    unittest.main(verbosity=2)
