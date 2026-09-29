"""읽지 못하는 첨부(zip, png…)도 같은 공문으로 묶어 정리하는지.

에듀파인에서 내려받으면 압축·이미지 첨부에도 같은 접수번호가 이름 앞에
붙어 온다. 내용을 못 읽는다고 빠뜨리면 폴더 정리에서 홀로 남고, 완료된
업무를 월별 폴더로 옮길 때도 뒤에 남겨진다.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402
import organize  # noqa: E402
from store import Store  # noqa: E402

BODY = ("제목\n      파견교사 선발 계획 알림\n\n"
        "신청서를 2026. 9. 25.까지 제출바랍니다.\n")


class MixedFolder(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.base = self.tmp / "1. 교무기획"
        self.inbox = self.base / "공문"
        self.inbox.mkdir(parents=True)
        self.store = Store(self.tmp / "t.db")

    def tearDown(self):
        self.store.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _fill(self):
        r = "[예시중학교-4971]"
        (self.inbox / f"{r} (본문) 파견교사 선발 계획 알림.txt").write_text(BODY, encoding="utf-8")
        (self.inbox / f"{r} (첨부) 제출서식.zip").write_bytes(b"PK\x03\x04" + b"\0" * 4000)
        (self.inbox / f"{r} 안내 포스터.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 900)
        # 접수번호가 없는 남의 파일. 건드리면 안 된다.
        (self.inbox / "내가 찍은 화면.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 80)


class Planning(MixedFolder):

    def test_plan_gathers_every_format(self):
        self._fill()
        groups, loose = organize.plan(self.inbox)
        self.assertEqual(len(groups), 1)
        names = sorted(i.path.suffix for i in groups[0].items)
        self.assertEqual(names, [".png", ".txt", ".zip"])

    def test_plan_leaves_unnumbered_files_alone(self):
        self._fill()
        _groups, loose = organize.plan(self.inbox)
        self.assertEqual([p.name for p in loose], ["내가 찍은 화면.png"])

    def test_organize_moves_every_format(self):
        self._fill()
        report = organize.organize(self.inbox)
        self.assertEqual(report["moved"], 3)
        folder = next(d for d in self.inbox.iterdir() if d.is_dir())
        self.assertEqual(sorted(p.suffix for p in folder.iterdir()),
                         [".png", ".txt", ".zip"])
        self.assertTrue((self.inbox / "내가 찍은 화면.png").exists(),
                        "접수번호 없는 파일까지 옮기면 안 됩니다")


class Recording(MixedFolder):

    def test_companions_are_recorded_but_not_read(self):
        self._fill()
        self.store.scan(self.inbox)
        by_name = {d["filename"]: d for d in self.store.all_docs()}
        self.assertIn("[예시중학교-4971] (첨부) 제출서식.zip", by_name)
        zipped = by_name["[예시중학교-4971] (첨부) 제출서식.zip"]
        self.assertFalse(zipped["readable"])
        self.assertEqual(zipped["error"], "",
                         "읽을 필요가 없는 것이지 못 읽은 것이 아닙니다")

    def test_unnumbered_loose_file_is_ignored(self):
        """공문 폴더 바로 아래의 접수번호 없는 그림은 남의 파일일 수 있다."""
        self._fill()
        self.store.scan(self.inbox)
        self.assertNotIn("내가 찍은 화면.png",
                         {d["filename"] for d in self.store.all_docs()})

    def test_everything_folds_into_one_group(self):
        self._fill()
        self.store.scan(self.inbox)
        groups = app.fold_groups(self.store.all_docs())
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["members"]), 3)
        self.assertEqual(groups[0]["attachments"], 2)

    def test_lead_is_never_an_unreadable_file(self):
        """대표가 zip 이면 목록에 제목도 기한도 없이 이름만 남는다."""
        self._fill()
        self.store.scan(self.inbox)
        lead = app.fold_groups(self.store.all_docs())[0]
        self.assertTrue(lead["filename"].endswith(".txt"))
        self.assertEqual(lead["deadline"], "2026-09-25")

    def test_sibling_in_organized_folder_joins_the_group(self):
        """정리된 폴더 안에 접수번호 없는 파일을 넣어도 갈라지면 안 된다."""
        self._fill()
        self.store.scan(self.inbox)
        organize.organize(self.inbox)
        folder = next(d for d in self.inbox.iterdir() if d.is_dir())
        (folder / "회의사진.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 300)
        self.store.scan(self.inbox)
        groups = app.fold_groups(self.store.all_docs())
        self.assertEqual(len(groups), 1, "같은 폴더인데 묶음이 갈라졌습니다")
        self.assertEqual(len(groups[0]["members"]), 4)

    def test_large_companion_is_not_read_whole(self):
        """큰 첨부까지 통째로 해시하면 훑을 때마다 디스크를 긁는다."""
        import store as store_module
        big = self.inbox / "[예시중학교-4971] (첨부) 큰파일.zip"
        big.write_bytes(b"A" * (store_module.COMPANION_HASH_BYTES + 2048))
        first = store_module._file_id(big, store_module.COMPANION_HASH_BYTES)
        # 뒷부분만 다른 파일은 크기가 같으면 같은 id 가 될 수 있지만,
        # 앞부분만 읽어도 크기를 섞으므로 크기가 다르면 갈린다.
        big.write_bytes(b"A" * (store_module.COMPANION_HASH_BYTES + 4096))
        self.assertNotEqual(first, store_module._file_id(
            big, store_module.COMPANION_HASH_BYTES))

    def test_readable_file_id_rule_unchanged(self):
        """읽는 형식의 id 규칙이 바뀌면 이미 쌓인 처리 상태와 메모가 날아간다."""
        import hashlib

        import store as store_module
        path = self.inbox / "[예시중학교-4971] (본문) 계획.txt"
        path.write_text(BODY, encoding="utf-8")
        expected = hashlib.sha1(path.read_bytes()).hexdigest()[:16]
        self.assertEqual(store_module._file_id(path), expected)


class Archiving(MixedFolder):

    def test_archive_carries_companions(self):
        self._fill()
        self.store.scan(self.inbox)
        organize.organize(self.inbox)
        self.store.scan(self.inbox)
        for doc in self.store.all_docs():
            self.store.set_done(doc["id"], True)

        entries = [{"title": g["title"], "month": 9,
                    "receipt": g.get("receipt_number", ""), "paths": g["paths"]}
                   for g in app.fold_groups(self.store.all_docs())]
        organize.archive(self.base, self.inbox, entries)

        landed = sorted(p.suffix for p in (self.base / "9월").rglob("*") if p.is_file())
        self.assertEqual(landed, [".png", ".txt", ".zip"],
                         "압축·이미지가 공문 폴더에 남겨졌습니다")


class DownloadedTwice(MixedFolder):
    """같은 공문을 또 내려받았을 때.

    폴더 정리를 이미 마친 공문을 에듀파인에서 다시 받으면, 인박스에 같은
    이름의 파일이 생긴다. 예전에는 갈 자리에 같은 이름이 있으면 그냥
    건너뛰어서 — 탐색기가 묻는 "덮어쓸까요" 같은 것도 없이 — 그 파일이
    정리를 아무리 눌러도 인박스에 그대로 남았다. 실사용에서 걸리셨다.
    """

    RECEIPT = "[예시중학교-4971]"

    def _first_round(self):
        body = self.inbox / f"{self.RECEIPT} (본문) 파견교사 선발 계획 알림.txt"
        att = self.inbox / f"{self.RECEIPT} (첨부) 제출서식.txt"
        body.write_text(BODY, encoding="utf-8")
        att.write_text("서식\n", encoding="utf-8")
        organize.organize(self.inbox)
        return body

    def test_same_file_again_goes_to_the_trash(self):
        body = self._first_round()
        body.write_text(BODY, encoding="utf-8")          # 똑같은 것을 또 받았다

        report = organize.organize(self.inbox)

        self.assertEqual(report["trashed"], 1)
        self.assertFalse(body.exists(), "정리를 눌렀는데 인박스에 그대로 남았습니다")
        self.assertEqual(report["renamed"], 0)

    def test_edited_version_is_kept_side_by_side(self):
        """이름은 같은데 내용이 다르면 고쳐 올라온 판이다. 지우면 안 된다."""
        body = self._first_round()
        body.write_text(BODY + "\n붙임 하나가 늘었습니다.\n", encoding="utf-8")

        report = organize.organize(self.inbox)

        self.assertEqual(report["renamed"], 1)
        self.assertEqual(report["trashed"], 0)
        self.assertFalse(body.exists())
        landed = sorted(p.name for p in (self.inbox / "파견교사 선발 계획 알림").iterdir())
        self.assertIn(f"{self.RECEIPT} (본문) 파견교사 선발 계획 알림 (2).txt", landed)
        self.assertIn(f"{self.RECEIPT} (본문) 파견교사 선발 계획 알림.txt", landed)

    def test_preview_says_what_will_happen(self):
        """누르기 전에 몇 건이 휴지통으로 가는지 알려야 한다."""
        body = self._first_round()
        body.write_text(BODY, encoding="utf-8")

        plan = organize.organize(self.inbox, dry_run=True)

        self.assertEqual(plan["trashed"], 1)
        self.assertTrue(body.exists(), "미리보기가 파일을 건드렸습니다")

    def test_nothing_is_skipped_into_limbo_anymore(self):
        """되풀이해 눌러도 남는 것이 없어야 한다."""
        body = self._first_round()
        for _ in range(3):
            body.write_text(BODY, encoding="utf-8")
            organize.organize(self.inbox)
        leftovers = [p.name for p in self.inbox.iterdir() if p.is_file()]
        self.assertEqual(leftovers, [], f"인박스에 남았습니다: {leftovers}")

    def test_unreadable_pair_is_compared_by_bytes(self):
        """내용을 못 읽는 형식(zip·png)도 바이트로 견줘 판단한다."""
        one = self.inbox / "가.zip"
        other = self.inbox / "나.zip"
        one.write_bytes(b"PK\x03\x04" + b"\0" * 500)
        other.write_bytes(b"PK\x03\x04" + b"\0" * 500)
        self.assertTrue(organize.same_file_content(one, other))
        other.write_bytes(b"PK\x03\x04" + b"\1" * 500)
        self.assertFalse(organize.same_file_content(one, other))

    def test_missing_file_is_never_called_identical(self):
        """읽지 못하면 같다고 우기지 않는다 — 우기면 지워 버린다."""
        one = self.inbox / "있다.txt"
        one.write_text("가", encoding="utf-8")
        self.assertFalse(organize.same_file_content(one, self.inbox / "없다.txt"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
