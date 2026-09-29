"""HTTP 라우트 회귀 테스트.

실제 서버를 띄워 브라우저가 부르는 것과 같은 방식으로 두드린다.
파일을 여는 것은 운영체제 일이므로 그 부분만 가로채 기록한다.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402
import extract  # noqa: E402
from store import Store  # noqa: E402

BODY = ("제목\n      파견교사 선발 계획 알림\n\n"
        "신청서를 2026. 9. 25.까지 제출바랍니다.\n")


class RevealCommand(unittest.TestCase):
    """탐색기에 넘기는 명령줄이 옳은지.

    리스트로 넘기면 파이썬이 공백이 든 "/select,경로" 를 통째로 따옴표로
    감싸고, 그러면 explorer 가 /select 를 스위치로 못 알아보고 엉뚱하게
    문서 폴더를 연다. 실제 업무 폴더는 "OneDrive - 예시중학교" 처럼
    공백이 섞여 있어서 늘 실패했다.
    """

    SPACED = Path(r"C:\Users\나\OneDrive - 예시중학교\1. 교무기획\공문"
                  r"\[예시중학교-4971] (본문) 계획.txt")

    def _sent(self, path: Path, platform: str = "win32"):
        sent = []
        saved_popen, saved_platform = app.subprocess.Popen, app.sys.platform
        app.subprocess.Popen = lambda args, **kw: sent.append(args)
        app.sys.platform = platform
        try:
            app.reveal_in_os(path)
        finally:
            app.subprocess.Popen = saved_popen
            app.sys.platform = saved_platform
        return sent[0]

    def test_switch_is_outside_the_quotes(self):
        line = self._sent(self.SPACED)
        self.assertIsInstance(line, str,
                              "리스트로 넘기면 파이썬이 따옴표를 다시 씌운다")
        self.assertTrue(line.startswith('explorer /select,"'),
                        f"/select 가 따옴표 안에 들어갔습니다: {line}")
        self.assertTrue(line.endswith('"'))
        self.assertIn(str(self.SPACED), line)

    def test_matches_the_documented_form(self):
        simple = Path(r"C:\gongmun\a.txt")
        self.assertEqual(self._sent(simple), f'explorer /select,"{simple}"')

    def test_reveal_does_not_block_the_request(self):
        """창을 앞으로 끌어올리는 일은 딴 스레드에서 해야 한다.

        여기서 기다리면 브라우저의 요청이 몇 초씩 붙잡힌다.
        """
        import time as _time
        start = _time.monotonic()
        app._raise_explorer_window("이런이름의폴더는없다ZZZ")
        self.assertLess(_time.monotonic() - start, 0.5,
                        "요청 스레드에서 창을 기다리고 있습니다")

    def test_foreground_helpers_never_raise(self):
        """창을 못 세워도 파일 열기 자체는 성공해야 한다."""
        app._allow_foreground_steal()
        for junk in ("", "없는폴더ZZZ"):
            with self.subTest(name=junk):
                app._raise_explorer_window(junk)

    def test_macos_reveals_rather_than_opens(self):
        sent = self._sent(self.SPACED, platform="darwin")
        self.assertEqual(sent[:2], ["open", "-R"])


class Routes(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.base = cls.tmp / "1. 교무기획"
        cls.inbox = cls.base / "공문"
        cls.inbox.mkdir(parents=True)
        r = "[예시중학교-4971]"
        (cls.inbox / f"{r} (본문) 계획 알림.txt").write_text(BODY, encoding="utf-8")
        (cls.inbox / f"{r} (첨부) 서식.zip").write_bytes(b"PK\x03\x04" + b"\0" * 3000)
        cls.store = Store(cls.tmp / "t.db")
        cls.store.scan(cls.inbox)
        cls.server, cls.port = app.start_server(cls.store, cls.inbox,
                                                port=9931, base=cls.base)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.store.conn.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        # 운영체제 호출을 가로채 무엇을 열려 했는지만 적어 둔다
        self.opened: list[Path] = []
        self.revealed: list[Path] = []
        self._saved = (app.open_in_os, app.reveal_in_os)
        app.open_in_os = self.opened.append
        app.reveal_in_os = self.revealed.append

    def tearDown(self):
        app.open_in_os, app.reveal_in_os = self._saved

    def get(self, path: str):
        # 한글이 든 주소도 그대로 넘길 수 있게 감싼다
        url = f"http://127.0.0.1:{self.port}{urllib.parse.quote(path, safe='/?=&')}"
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def post(self, path: str, body: dict):
        url = f"http://127.0.0.1:{self.port}{path}"
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def a_doc(self, suffix: str) -> dict:
        for doc in self.store.all_docs():
            if doc["filename"].endswith(suffix):
                return doc
        self.fail(f"{suffix} 문서를 찾지 못했습니다")

    # ------------------------------------------------------------ reveal

    def test_reveal_targets_the_file_itself(self):
        """폴더만 여는 게 아니라 그 파일을 고른 채로 열어야 한다."""
        doc = self.a_doc(".zip")
        status, payload = self.get("/api/reveal?id=" + doc["id"])
        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"))
        self.assertEqual([str(p) for p in self.revealed], [doc["path"]])
        self.assertEqual(self.opened, [], "파일을 고르지 않고 폴더만 열었습니다")

    def test_reveal_works_for_attachments_too(self):
        """미리보기가 안 되는 첨부야말로 위치를 열어 볼 일이 많다."""
        for suffix in (".txt", ".zip"):
            with self.subTest(suffix=suffix):
                self.revealed.clear()
                doc = self.a_doc(suffix)
                self.get("/api/reveal?id=" + doc["id"])
                self.assertEqual([str(p) for p in self.revealed], [doc["path"]])

    def test_reveal_falls_back_to_the_folder_when_file_is_gone(self):
        doc = self.a_doc(".txt")
        moved = Path(doc["path"])
        stashed = moved.with_suffix(".hidden")
        moved.rename(stashed)
        try:
            status, payload = self.get("/api/reveal?id=" + doc["id"])
            self.assertEqual(status, 200)
            self.assertEqual([str(p) for p in self.opened], [str(moved.parent)])
        finally:
            stashed.rename(moved)

    def test_reveal_unknown_id(self):
        status, payload = self.get("/api/reveal?id=없는아이디")
        self.assertEqual(status, 404)
        self.assertIn("error", payload)

    # -------------------------------------------------------------- 기타

    def test_open_still_opens_the_file(self):
        doc = self.a_doc(".zip")
        self.get("/api/open?id=" + doc["id"])
        self.assertEqual([str(p) for p in self.opened], [doc["path"]])

    def test_open_folder_opens_the_inbox(self):
        self.get("/api/open-folder")
        self.assertEqual([str(p) for p in self.opened], [str(self.inbox)])

    def test_pin_marks_the_whole_group_and_sorts_it_first(self):
        """첨부 하나만 고정해도 공문 묶음이 통째로 맨 위로 올라와야 한다."""
        zip_doc = self.a_doc(".zip")
        try:
            status, state = self.post("/api/pin", {"id": zip_doc["id"], "pinned": True})
            self.assertEqual(status, 200)
            self.assertTrue(state["docs"][0]["pinned"])
        finally:
            self.post("/api/pin", {"id": zip_doc["id"], "pinned": False})
        _, state = self.get("/api/state")
        self.assertFalse(any(d["pinned"] for d in state["docs"]))

    def test_state_and_rev_agree(self):
        _, rev = self.get("/api/rev")
        _, state = self.get("/api/state")
        self.assertEqual(state["rev"], rev["rev"])


class PreviewImage(unittest.TestCase):
    """미리보기를 글자가 아니라 문서 그림으로 보여 준다.

    한글 문서는 저장할 때 첫 쪽 그림을 파일 안에 함께 넣어 둔다(탐색기가
    쓰는 그 그림이다). 그것을 꺼내 쓰면 표와 서식이 그대로 보인다.
    따로 깔 것도, 변환할 것도 없다.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.inbox = self.tmp / "공문"
        self.inbox.mkdir(parents=True)
        self.store = Store(self.tmp / "t.db")
        self.server, self.port = app.start_server(self.store, self.inbox,
                                                  port=9961, base=self.tmp)

    def tearDown(self):
        self.server.shutdown()
        self.store.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def raw(self, path: str):
        url = f"http://127.0.0.1:{self.port}{urllib.parse.quote(path, safe='/?=&')}"
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                return response.status, response.headers.get("Content-Type"), response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers.get("Content-Type"), exc.read()

    def _hwpx_with_preview(self, name: str, png: bytes) -> Path:
        """미리보기 그림이 든 최소한의 hwpx 를 만든다."""
        target = self.inbox / name
        with zipfile.ZipFile(target, "w") as archive:
            archive.writestr("Preview/PrvImage.png", png)
            archive.writestr("Preview/PrvText.txt", "미리보기 글")
            archive.writestr("Contents/section0.xml",
                             '<?xml version="1.0"?><hml><p>본문</p></hml>')
        return target

    def test_hwpx_preview_image_is_served_as_png(self):
        png = (b"\x89PNG\r\n\x1a\n" + b"\0" * 64)
        self._hwpx_with_preview("안내.hwpx", png)
        self.store.scan(self.inbox)
        doc_id = self.store.all_docs()[0]["id"]

        status, kind, body = self.raw("/api/preview-image?id=" + doc_id)

        self.assertEqual(status, 200)
        self.assertEqual(kind, "image/png")
        self.assertEqual(body, png)

    def test_document_without_a_preview_falls_back(self):
        """그림이 없으면 404 를 주고 화면이 글자 미리보기로 물러난다."""
        (self.inbox / "그냥.txt").write_text(BODY, encoding="utf-8")
        self.store.scan(self.inbox)
        doc_id = self.store.all_docs()[0]["id"]

        status, _, _ = self.raw("/api/preview-image?id=" + doc_id)

        self.assertEqual(status, 404)

    def test_unknown_id_is_not_a_crash(self):
        status, _, _ = self.raw("/api/preview-image?id=없는아이디")
        self.assertEqual(status, 404)

    def test_only_pdf_is_handed_over_whole(self):
        """/api/file 은 PDF 만 넘긴다. 아무 파일이나 읽어 가면 안 된다."""
        (self.inbox / "그냥.txt").write_text(BODY, encoding="utf-8")
        self.store.scan(self.inbox)
        doc_id = self.store.all_docs()[0]["id"]

        status, _, _ = self.raw("/api/file?id=" + doc_id)

        self.assertEqual(status, 404, "PDF 가 아닌 파일을 통째로 내주었습니다")

    def test_extractor_never_raises_on_junk(self):
        """깨진 파일에 걸려 미리보기가 프로그램을 멈추면 안 된다."""
        broken = self.inbox / "깨진.hwpx"
        broken.write_bytes(b"PK\x03\x04" + "이건 zip 이 아니다".encode("utf-8"))
        self.assertIsNone(extract.preview_image(broken))
        self.assertIsNone(extract.preview_image(self.inbox / "없는파일.hwp"))

    def test_only_real_images_go_out(self):
        """그림이 아닌 것을 image/png 라고 내보내면 안 된다."""
        self._hwpx_with_preview("가짜.hwpx", "이건 PNG 가 아닙니다".encode("utf-8"))
        self.store.scan(self.inbox)
        doc_id = self.store.all_docs()[0]["id"]
        status, _, _ = self.raw("/api/preview-image?id=" + doc_id)
        self.assertEqual(status, 404)


class ArchivingWithoutDates(unittest.TestCase):
    """기한도 행사일도 없는 문서를 정리해도 인박스에 남으면 안 된다.

    예전에는 파일이 마지막으로 고쳐진 날짜를 봤다. 옮기거나 다시 저장할
    때마다 이 날짜가 바뀌고, 받은 지 오래된 문서는 이미 지난 달을
    가리켜 정리를 눌러도 아무 데도 못 가고 그대로 남았다.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.base = self.tmp / "1. 교무기획"
        self.inbox = self.base / "공문"
        self.inbox.mkdir(parents=True)
        self.store = Store(self.tmp / "t.db")
        self.server, self.port = app.start_server(self.store, self.inbox,
                                                   port=9951, base=self.base)

    def tearDown(self):
        self.server.shutdown()
        self.store.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def get(self, path: str):
        url = f"http://127.0.0.1:{self.port}{urllib.parse.quote(path, safe='/?=&')}"
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_dateless_document_lands_in_this_months_folder(self):
        target = self.inbox / "그냥 안내.txt"
        target.write_text("제목\n      그냥 안내\n\n특별한 날짜는 없습니다.\n",
                          encoding="utf-8")
        self.store.scan(self.inbox)
        doc = self.store.all_docs()[0]
        self.assertIsNone(doc["deadline"])
        self.assertIsNone(doc["event_date"])
        self.store.set_done(doc["id"], True)

        status, state = self.get("/api/archive")
        self.assertEqual(status, 200)
        self.assertEqual(state["archived_report"]["no_date"], 0,
                         "기한이 없다고 정리를 건너뛰었습니다")

        this_month = self.base / f"{date.today().month}월"
        self.assertTrue(list(this_month.rglob("*.txt")),
                        "기한 없는 문서가 이번 달 폴더로 가지 않았습니다")
        self.assertFalse(target.exists(), "인박스에 그대로 남아 있습니다")

    def test_old_file_date_no_longer_sends_it_to_a_past_month(self):
        """파일 자체의 수정일이 지난 달이어도 오늘 달로 보낸다."""
        target = self.inbox / "오래된 안내.txt"
        target.write_text("제목\n      오래된 안내\n\n특별한 날짜는 없습니다.\n",
                          encoding="utf-8")
        old = date.today().replace(day=1) - timedelta(days=40)
        stamp = datetime.combine(old, datetime.min.time()).timestamp()
        os.utime(target, (stamp, stamp))
        self.store.scan(self.inbox)
        doc = self.store.all_docs()[0]
        self.assertNotEqual(doc["modified"][:7], date.today().isoformat()[:7],
                            "이 시험은 파일 날짜가 지난 달이어야 뜻이 있습니다")
        self.store.set_done(doc["id"], True)

        self.get("/api/archive")

        this_month = self.base / f"{date.today().month}월"
        self.assertTrue(list(this_month.rglob("*.txt")),
                        "지난 파일 날짜를 따라 지난 달로 보냈습니다")


class SurfaceCall(unittest.TestCase):
    """프로그램을 또 실행하면 떠 있는 위젯이 앞으로 나와야 한다.

    위젯은 테두리 없는 창이라 작업 표시줄에 뜨지 않는다. 바탕화면 보기로
    가려지면 되살릴 길이 없었다.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.inbox = cls.tmp / "공문"
        cls.inbox.mkdir(parents=True)
        cls.store = Store(cls.tmp / "t.db")
        cls.server, cls.port = app.start_server(cls.store, cls.inbox,
                                                port=9941, base=cls.tmp)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.store.conn.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_running_one_is_found_on_its_port(self):
        self.assertEqual(app.running_port(self.port), self.port)

    def test_nothing_running_is_nothing_found(self):
        self.assertIsNone(app.running_port(9800))

    def test_asking_raises_the_count(self):
        before = app.Handler.show_calls
        self.assertTrue(app.ask_to_surface(self.port))
        self.assertEqual(app.Handler.show_calls, before + 1,
                         "위젯이 지켜보는 숫자가 오르지 않았습니다")

    def test_asking_a_dead_port_just_says_no(self):
        """부탁이 안 닿으면 예전 안내창으로 물러나야 한다. 터지면 안 된다."""
        self.assertFalse(app.ask_to_surface(9801))

    def test_it_never_scans_the_disk(self):
        """되살리기는 사람이 기다리는 일이다. 폴더를 훑고 있으면 안 된다."""
        before = self.store.rev
        app.ask_to_surface(self.port)
        self.assertEqual(self.store.rev, before,
                         "읽기가 변경 번호를 올렸습니다")


if __name__ == "__main__":
    unittest.main(verbosity=2)
