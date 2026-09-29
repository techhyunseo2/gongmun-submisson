"""변경내역.md 에서 한 버전의 내용을 꺼낸다.

두 곳에서 쓴다.

  · 위젯이 갱신을 마치고 다시 뜬 뒤 "이렇게 바뀌었습니다" 창을 띄울 때
  · 빌드가 GitHub 릴리스 설명글을 만들 때 (`python changelog.py 1.4.0`)

명령창에 정규식을 직접 적으면 PowerShell 이 따옴표를 먼저 해석해 버리므로
`version_of.py` 와 같은 이유로 파일로 빼 두었다.

app.py 를 불러오지 않는다. 빌드 스크립트가 무거운 의존성 없이 쓰기 위해서다.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

FILENAME = "변경내역.md"


def _base_dir() -> Path:
    """exe 로 묶이면 파일들이 임시 폴더에 풀린다. 그때는 그쪽을 봐야 한다."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def _read(path: Path | None = None) -> str:
    target = path or (_base_dir() / FILENAME)
    try:
        return target.read_text(encoding="utf-8")
    except OSError:
        return ""


def notes_for(version: str, path: Path | None = None) -> str:
    """그 버전 아래에 적힌 줄들을 돌려준다. 없으면 빈 문자열.

    없다고 해서 문제가 되면 안 된다 — 적어 두는 것을 잊었을 뿐이므로
    안내창을 띄우지 않고 넘어간다.
    """
    wanted = (version or "").strip().lstrip("vV")
    if not wanted:
        return ""

    body = _read(path)
    if not body:
        return ""

    collecting = False
    picked: list[str] = []
    for line in body.splitlines():
        heading = re.match(r"^##\s+v?([\w.]+)\s*$", line)
        if heading:
            if collecting:
                break                       # 다음 버전을 만났다
            collecting = heading.group(1) == wanted
            continue
        if collecting:
            picked.append(line)

    return "\n".join(picked).strip()


def as_lines(version: str, path: Path | None = None) -> list[str]:
    """안내창에 뿌리기 좋게 '- ' 목록을 한 항목씩 이어 붙여 돌려준다."""
    notes = notes_for(version, path)
    if not notes:
        return []
    items: list[str] = []
    for line in notes.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("-", "*", "·")):
            items.append(stripped.lstrip("-*· ").strip())
        elif items:
            items[-1] += " " + stripped      # 다음 줄로 접힌 항목을 잇는다
        else:
            items.append(stripped)
    return items


# 릴리스 페이지 아래에 늘 붙는 안내. 바뀐 점 뒤에 온다 — 위젯이 갱신 전에
# 보여 주는 미리보기는 앞쪽 400자만 쓰므로 바뀐 점이 먼저여야 한다.
_FOOTER = """---

처음 쓰시는 분은 `gongmun-submisson-setup.exe` 를 받아 실행하세요.

이미 쓰고 계신 분은 아무것도 하지 않으셔도 됩니다. 프로그램이 알아서
갱신하고, 끝나면 무엇이 바뀌었는지 알려 드립니다.
"""


def release_body(version: str, path: Path | None = None) -> str:
    notes = notes_for(version, path)
    head = f"## 바뀐 점\n\n{notes}\n\n" if notes else ""
    return head + _FOOTER


if __name__ == "__main__":
    # 빌드 러너에서는 stdout 이 콘솔이 아니라 파이프다. 그때 파이썬은 윈도우의
    # 기본 코드페이지(cp1252 등)로 내보내려 하고, 한글이 하나라도 있으면
    # UnicodeEncodeError 로 죽는다. 파일은 이미 UTF-8 로 잘 썼는데 확인용
    # 출력 한 줄 때문에 빌드가 통째로 멈추던 자리다.
    # (version_of.py 가 멀쩡했던 건 숫자만 찍기 때문이고, 회귀 테스트가
    #  멀쩡했던 건 unittest 가 stderr 로 쓰는데 stderr 는 기본 오류 처리가
    #  backslashreplace 라 죽지 않기 때문이다.)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    args = sys.argv[1:]
    if args and args[0] == "--release":
        if len(args) < 3:
            sys.exit("쓰는 법: python changelog.py --release 1.4.0 release-notes.md")
        Path(args[2]).write_text(release_body(args[1]), encoding="utf-8")
        print(f"{args[2]} 를 만들었습니다 ({args[1]})")
    elif args:
        print(notes_for(args[0]))
    else:
        sys.exit("쓰는 법: python changelog.py 1.4.0")
