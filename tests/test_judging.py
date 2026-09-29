"""심사 환경에서 그냥 돌아가는가.

업무자동화 프로그램 개발대회 1차 심사는 심사위원이 제출된 자료로 직접
설치해 평가한다. **"구동이 되지 않거나, 평균점수 40점 이하는 선정에서
제외"** 라 여기서 걸리면 나머지 준비가 무의미해진다.

심사 환경으로 고지된 것: Windows 11 64bit, 한글 2024, MS Office 2024.
그 위에서 걱정되는 것을 하나씩 못박는다. 실제로 배포된 exe 를 깨끗한
사용자 폴더에서 돌려 확인한 뒤, 그때 본 것을 여기 옮겨 왔다.
"""

from __future__ import annotations

import json
import shutil
import socket
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402
import extract  # noqa: E402
import updater  # noqa: E402
from store import Store  # noqa: E402

BODY = (
    "제목  (중)2026학년도 방과후학교 운영 계획\n"
    "1. 관련: 예시중학교-2949(2026. 5. 14.)\n"
    "2. 제출 기한: 2026. 9. 30.(수)까지 제출 바랍니다.\n"
)


class _NoInternet:
    """바깥으로 나가는 길만 막는다. 로컬(127.0.0.1)은 살려 둔다.

    학교망이나 심사장에서 바깥이 막혀 있을 수 있다. 그때도 프로그램은
    제 일을 다 해야 하고, 갱신 확인만 조용히 건너뛰어야 한다.
    """

    LOCAL = {"127.0.0.1", "localhost", "::1"}

    def __enter__(self):
        self.real = socket.getaddrinfo
        socket.getaddrinfo = self._only_local
        return self

    def __exit__(self, *_):
        socket.getaddrinfo = self.real

    def _only_local(self, host, *args, **kwargs):
        if host not in self.LOCAL:
            raise socket.gaierror(11001, "이름을 못 찾음 (막힌 망)")
        return self.real(host, *args, **kwargs)


class Offline(unittest.TestCase):
    """바깥 인터넷이 막혀도 프로그램은 멀쩡해야 한다."""

    def test_the_update_check_fails_quietly_and_kindly(self):
        """콘솔 없는 exe 에서 예외가 새면 그냥 죽는다.

        `UpdateError` 로만 나와야 `widget._check_update_worker` 가 삼킨다.
        """
        with _NoInternet():
            with self.assertRaises(updater.UpdateError) as caught:
                updater.check()
        self.assertIn("인터넷", str(caught.exception))

    def test_release_notes_give_up_quietly(self):
        with _NoInternet():
            self.assertEqual(updater._release_info(), {})

    def test_downloading_fails_kindly(self):
        with _NoInternet():
            with self.assertRaises(updater.UpdateError):
                updater._download(
                    "https://github.com/x/y/releases/download/v1/gongmun.exe",
                    Path(tempfile.gettempdir()) / "안쓸파일.exe")

    def test_reading_and_sorting_work_without_any_network(self):
        with _NoInternet():
            tmp = Path(tempfile.mkdtemp())
            self.addCleanup(shutil.rmtree, tmp, True)
            inbox = tmp / "1. 교무기획" / "공문"
            inbox.mkdir(parents=True)
            (inbox / "[예시중학교-1234] (본문) 운영 계획 알림.txt").write_text(
                BODY, encoding="utf-8")
            store = Store(tmp / "t.db")
            self.addCleanup(store.conn.close)
            report = store.scan(inbox)
            self.assertEqual(report["added"], 1)
            self.assertEqual(report["failed"], 0)
            found = store.all_docs()[0]
            self.assertEqual(found["category"], "submit")
            self.assertEqual(found["deadline"], "2026-09-30")


class Loopback(unittest.TestCase):
    """화면을 여는 서버가 바깥에 열려 있으면 안 된다.

    `127.0.0.1` 에만 서면 윈도우 방화벽이 허용을 묻지 않는다. `0.0.0.0`
    으로 서면 심사위원 PC 에서 방화벽 창이 뜨고, 거절하면 화면이 안 열린다.
    요강 ➎ 도 "업무용 PC의 보안 프로그램과 충돌" 을 금한다.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.inbox = cls.tmp / "공문"
        cls.inbox.mkdir(parents=True)
        (cls.inbox / "[예시중학교-1234] (본문) 운영 계획 알림.txt").write_text(
            BODY, encoding="utf-8")
        cls.store = Store(cls.tmp / "t.db")
        cls.store.scan(cls.inbox)
        cls.server, cls.port = app.start_server(cls.store, cls.inbox,
                                                port=9971, base=cls.tmp)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.store.conn.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_it_only_listens_on_this_computer(self):
        host = self.server.server_address[0]
        self.assertIn(host, ("127.0.0.1", "::1"),
                      "바깥에 열면 방화벽이 허용을 묻습니다")

    def test_the_screen_and_the_font_come_from_inside(self):
        """글꼴을 함께 넣어 배포하므로 인터넷 없이도 글자가 제대로 나온다."""
        for route, least in (("/", 10_000),
                             ("/assets/PretendardVariable.woff2", 1_000_000)):
            with self.subTest(route=route):
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{self.port}{route}", timeout=5) as answer:
                    self.assertEqual(answer.status, 200)
                    self.assertGreater(len(answer.read()), least)

    def test_the_state_route_answers(self):
        with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/api/state", timeout=5) as answer:
            body = json.loads(answer.read().decode("utf-8"))
        self.assertTrue(body["docs"])


class WhatWindowsWrites(unittest.TestCase):
    """윈도우 프로그램이 만든 파일도 그대로 읽혀야 한다."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_a_file_saved_by_notepad_has_no_stray_mark(self):
        """메모장은 파일 앞에 보이지 않는 표식(BOM)을 붙인다.

        그냥 utf-8 로 읽으면 그 글자가 제목 앞에 딸려 들어가 목록에
        이상한 글자로 보인다. 실제로 배포된 exe 를 돌려 보다 찾았다.
        """
        path = self.tmp / "메모장으로 저장한 공문.txt"
        path.write_bytes(BODY.encode("utf-8-sig"))
        text = extract.extract_text(path)
        self.assertFalse(text.startswith("﻿"), "보이지 않는 표식이 남았습니다")
        self.assertTrue(text.startswith("제목"))

    def test_a_plain_file_still_reads_the_same(self):
        path = self.tmp / "그냥 저장한 공문.txt"
        path.write_bytes(BODY.encode("utf-8"))
        self.assertTrue(extract.extract_text(path).startswith("제목"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
