"""changelog.py 회귀 테스트 + 배포 때 빠뜨리기 쉬운 것들의 그물.

변경내역.md 한 곳을 두 군데가 읽는다. 갱신을 마친 위젯이 띄우는
"이렇게 바뀌었습니다" 창과, 빌드가 만드는 GitHub 릴리스 설명글이다.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import changelog  # noqa: E402


def app_version() -> str:
    """app.py 의 VERSION. 테스트가 버전을 손으로 적으면 올릴 때마다 깨진다."""
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    found = re.search(r'^VERSION\s*=\s*"([^"]+)"', source, re.MULTILINE)
    assert found, "app.py 에서 VERSION 을 찾지 못했습니다"
    return found.group(1)

SAMPLE = """# 변경 내역

머리말은 무시한다.

## 1.4.0

- 첫째 줄입니다.
  접힌 둘째 줄입니다.
- 둘째 항목입니다.

## 1.3.8

- 옛 버전 항목.
"""


class Parsing(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "변경내역.md"
        self.tmp.write_text(SAMPLE, encoding="utf-8")

    def test_picks_only_that_version(self):
        notes = changelog.notes_for("1.4.0", self.tmp)
        self.assertIn("첫째 줄입니다.", notes)
        self.assertNotIn("옛 버전 항목", notes)      # 다음 ## 에서 멈춰야 한다

    def test_accepts_v_prefix(self):
        self.assertEqual(changelog.notes_for("v1.4.0", self.tmp),
                         changelog.notes_for("1.4.0", self.tmp))

    def test_unknown_version_is_quiet(self):
        """적어 두는 것을 잊었을 뿐이다. 오류를 내면 안 된다."""
        self.assertEqual(changelog.notes_for("9.9.9", self.tmp), "")
        self.assertEqual(changelog.as_lines("9.9.9", self.tmp), [])

    def test_missing_file_is_quiet(self):
        self.assertEqual(changelog.notes_for("1.4.0", self.tmp.parent / "없다.md"), "")

    def test_as_lines_joins_wrapped_items(self):
        lines = changelog.as_lines("1.4.0", self.tmp)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], "첫째 줄입니다. 접힌 둘째 줄입니다.")

    def test_release_body_leads_with_changes(self):
        """갱신 전 미리보기는 앞 400자만 쓴다. 바뀐 점이 먼저 와야 한다."""
        body = changelog.release_body("1.4.0", self.tmp)
        self.assertTrue(body.startswith("## 바뀐 점"))
        self.assertLess(body.index("첫째 줄입니다"), body.index("gongmun-submisson-setup.exe"))

    def test_release_body_without_notes_still_has_install_guide(self):
        body = changelog.release_body("9.9.9", self.tmp)
        self.assertNotIn("## 바뀐 점", body)
        self.assertIn("gongmun-submisson-setup.exe", body)


class CommandLine(unittest.TestCase):
    """빌드가 부르는 방식 그대로 돌려 본다.

    러너에서는 stdout 이 파이프여서 파이썬이 윈도우 기본 코드페이지로
    내보내려 한다. 한글을 찍으면 UnicodeEncodeError 로 죽고 빌드가 멈춘다.
    실제로 v1.4.0 빌드가 이것 때문에 "릴리스 설명글을 만들지 못했습니다" 로
    실패했다. 그 상황을 흉내 내려고 일부러 cp1252 를 물려서 돌린다.
    """

    def _run(self, *args, encoding: str = "cp1252"):
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = encoding      # 러너의 좁은 인코딩을 흉내
        env.pop("PYTHONUTF8", None)
        return subprocess.run([sys.executable, "changelog.py", *args],
                              cwd=ROOT, env=env, capture_output=True, timeout=60)

    def test_release_mode_survives_narrow_stdout(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "release-notes.md"
            done = self._run("--release", app_version(), str(out))
            self.assertEqual(done.returncode, 0,
                             f"stderr: {done.stderr.decode('utf-8', 'replace')}")
            self.assertIn("바뀐 점", out.read_text(encoding="utf-8"))

    def test_print_mode_survives_narrow_stdout(self):
        done = self._run(app_version())
        self.assertEqual(done.returncode, 0,
                         f"stderr: {done.stderr.decode('utf-8', 'replace')}")
        self.assertTrue(done.stdout.strip(), "바뀐 점이 출력되지 않았습니다")

    def test_no_arguments_explains_usage(self):
        self.assertNotEqual(self._run().returncode, 0)


class ShippingChecklist(unittest.TestCase):
    """올릴 때 빠뜨리기 쉬운 것들. 빠져도 오류가 안 나서 알아채기 어렵다."""

    def test_current_version_has_notes(self):
        """지금 VERSION 이 변경내역.md 에 있어야 갱신 뒤 안내창이 뜬다."""
        version = app_version()
        self.assertTrue(
            changelog.as_lines(version),
            f"변경내역.md 에 '## {version}' 을 적어 주세요. "
            f"없으면 갱신을 마쳐도 안내창이 뜨지 않습니다.")

    def test_changelog_file_is_bundled(self):
        """exe 안에 들어가지 않으면 안내창이 조용히 안 뜬다.

        주석에 이름이 적힌 것만으로는 안 되므로 datas 의 튜플을 찾는다.
        """
        spec = (ROOT / "build.spec").read_text(encoding="utf-8")
        self.assertRegex(
            spec, r'\(\s*"변경내역\.md"\s*,',
            'build.spec 의 datas 에 ("변경내역.md", ".") 를 넣어 주세요')

    def test_ui_html_is_bundled(self):
        """같은 이유. 이게 빠지면 전체 화면이 아예 안 열린다."""
        spec = (ROOT / "build.spec").read_text(encoding="utf-8")
        self.assertRegex(spec, r'\(\s*"ui\.html"\s*,',
                         'build.spec 의 datas 에 ("ui.html", ".") 를 넣어 주세요')

    def test_every_module_is_in_hiddenimports(self):
        """루트의 파이썬 모듈이 build.spec 의 hiddenimports 에 다 있는지.

        빠뜨리면 PyInstaller 가 조용히 뺀 채로 exe 를 만들고, 받는 분
        컴퓨터에서만 죽는다. CLAUDE.md 가 "잊기 쉬운 지점"이라 적어 둔 곳.
        """
        spec = (ROOT / "build.spec").read_text(encoding="utf-8")
        skip = {"version_of",   # 빌드할 때만 쓰는 도구
                "widget"}       # 진입점이라 PyInstaller 가 알아서 잡는다
        missing = [py.stem for py in sorted(ROOT.glob("*.py"))
                   if py.stem not in skip and f'"{py.stem}"' not in spec]
        self.assertEqual(missing, [],
                         f"build.spec 의 hiddenimports 에 넣어 주세요: {missing}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
