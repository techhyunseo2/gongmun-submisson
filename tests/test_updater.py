"""updater.py 회귀 테스트 (네트워크 없이 도는 것만).

핵심은 "새 버전이 나왔는데도 내려받지 못하는" 사고를 막는 것이다.
1.3.6~1.3.7 은 자동 업데이트가 찾는 첨부 이름(공문정리함.exe)과 GitHub 이
실제로 올린 이름(default.exe)이 어긋나 "내려받다가 끊겼습니다" 로
실패했다. 그 상황을 표본으로 고정한다.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import updater  # noqa: E402


class VersionCompare(unittest.TestCase):

    def test_newer(self):
        self.assertTrue(updater.is_newer("v1.3.8", "1.3.7"))
        self.assertTrue(updater.is_newer("1.4.0", "1.3.9"))

    def test_not_newer(self):
        self.assertFalse(updater.is_newer("v1.3.7", "1.3.7"))
        self.assertFalse(updater.is_newer("v1.3.6", "1.3.7"))

    def test_asset_name_is_ascii(self):
        """한글이 섞이면 GitHub 이 파일명을 바꿔 버려 다운로드가 깨진다."""
        self.assertTrue(updater.ASSET_NAME.isascii())


class RestartEnvironment(unittest.TestCase):
    """재시작할 때 PyInstaller 의 실행 환경 표시를 물려주면 안 된다.

    물려주면 새 exe 가 "나는 onefile 부모가 띄운 자식이다" 라고 착각하고
    부모가 같은 파일인지 검사하는데, 그때 부모(죽어가는 옛 프로세스)의
    파일은 이미 .old 로 이름이 바뀐 뒤라 이런 창이 뜬다.

        Security validation failure: parent process has different executable!

    PyInstaller 6.22.2 로 실제 onefile exe 를 만들어 재현하고 고친 자리다.
    """

    def setUp(self):
        self._saved = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved)

    def test_strips_pyinstaller_markers(self):
        os.environ["_PYI_ARCHIVE_FILE"] = r"C:\Programs\gongmun\gongmun.exe"
        os.environ["_PYI_PARENT_PROCESS_LEVEL"] = "1"
        os.environ["_PYI_APPLICATION_HOME_DIR"] = r"C:\Temp\_MEI123"
        os.environ["_MEIPASS2"] = r"C:\Temp\_MEI123"
        fresh = updater._fresh_env()
        left = sorted(k for k in fresh if k.startswith("_PYI_") or k == "_MEIPASS2")
        self.assertEqual(left, [], f"물려주면 안 되는 것이 남았습니다: {left}")

    def test_keeps_everything_else(self):
        os.environ["_PYI_ARCHIVE_FILE"] = "x"
        os.environ["GONGMUN_TEST_KEEP"] = "지켜야 함"
        fresh = updater._fresh_env()
        self.assertEqual(fresh.get("GONGMUN_TEST_KEEP"), "지켜야 함")
        self.assertIn("PATH", fresh, "PATH 까지 지우면 새 프로그램이 못 뜬다")

    def test_restart_passes_the_cleaned_environment(self):
        """restart() 가 정말 그 환경으로 띄우는지."""
        os.environ["_PYI_ARCHIVE_FILE"] = "x"
        captured = {}

        def fake_popen(args, **kwargs):
            captured.update(kwargs)
            return None

        def stop(code):
            raise SystemExit(code)

        original = (updater.subprocess.Popen, updater.os._exit)
        updater.subprocess.Popen, updater.os._exit = fake_popen, stop
        try:
            with self.assertRaises(SystemExit):
                updater.restart()
        finally:
            updater.subprocess.Popen, updater.os._exit = original

        self.assertIn("env", captured, "환경을 지정하지 않고 띄우고 있습니다")
        self.assertNotIn("_PYI_ARCHIVE_FILE", captured["env"])


class ReleaseParsing(unittest.TestCase):

    def test_picks_smaller_exe_as_app(self):
        """첨부가 설치파일 + 실행파일이면 더 작은 쪽이 PyInstaller exe."""
        release = {
            "body": "설명",
            "assets": [
                {"name": "gongmun-submisson-setup.exe", "size": 17_000_000, "state": "uploaded",
                 "browser_download_url": "https://x/gongmun-submisson-setup.exe"},
                {"name": "gongmun-submisson.exe", "size": 15_000_000, "state": "uploaded",
                 "browser_download_url": "https://x/gongmun-submisson.exe"},
            ],
        }
        info = updater._parse_release(release)
        self.assertEqual(info["asset_url"], "https://x/gongmun-submisson.exe")
        self.assertEqual(info["notes"], "설명")

    def test_survives_mangled_korean_names(self):
        """GitHub 이 한글 이름을 default.exe / -.exe 로 바꿔 놓은 옛 릴리스."""
        release = {
            "assets": [
                {"name": "-.exe", "size": 16_511_735, "state": "uploaded",
                 "browser_download_url": "https://x/-.exe"},
                {"name": "default.exe", "size": 14_822_686, "state": "uploaded",
                 "browser_download_url": "https://x/default.exe"},
            ],
        }
        info = updater._parse_release(release)
        self.assertEqual(info["asset_url"], "https://x/default.exe")

    def test_no_exe_asset(self):
        info = updater._parse_release({"body": "x", "assets": [
            {"name": "notes.txt", "browser_download_url": "https://x/notes.txt"}]})
        self.assertNotIn("asset_url", info)

    def test_empty_release(self):
        self.assertEqual(updater._parse_release({}), {"notes": ""})


if __name__ == "__main__":
    unittest.main(verbosity=2)
