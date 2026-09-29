"""공문 묶음 정리.

에듀파인에서 내려받은 파일 이름은 대개 이런 모양이다.

    [예시중학교-4971] (본문) 부산광역시서부교육지원청 ... 파견교사 선발 계획 알림.pdf
    [예시중학교-4971] (첨부) 부산광역시서부교육지원청 ... 파견교사 선발 계획.hwp

앞머리의 접수번호가 본문과 첨부를 잇는 열쇠다. 제목이 길어 잘리거나
괄호가 밑줄로 바뀌어도 번호는 남기 때문에 제목보다 훨씬 믿을 만하다.

  parse_name(파일명)   →  (접수번호, 역할, 제목)
  plan(폴더)           →  어떻게 옮길지 계획만 세운다
  organize(폴더)       →  실제로 폴더를 만들고 옮긴다
"""

from __future__ import annotations

import ctypes
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

# 접수번호: 기관 이름 뒤에 붙임표와 숫자. 괄호가 밑줄로 바뀐 경우도 받는다.
_RECEIPT = re.compile(
    r"^[\[\(\{_\s]*"
    r"(?P<org>[가-힣A-Za-z][가-힣A-Za-z0-9]{1,19})"
    r"\s*-\s*(?P<no>\d{2,7})"
    r"[\]\)\}_\s]+"
)

# 역할: 본문인지 첨부인지
_ROLE = re.compile(r"^[\[\(\{_\s]*(?P<role>본\s*문|첨\s*부|붙\s*임)[\]\)\}_\s]+")

ROLE_BODY = "본문"
ROLE_ATTACH = "첨부"
ROLE_ALONE = "단독"

# 윈도우에서 폴더 이름에 쓸 수 없는 글자
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

MAX_FOLDER_NAME = 60

# 선생님들이 쓰는 업무 폴더 구조를 알아보기 위한 이름들
#   1. 교무기획/            ← 업무 루트
#      공문/                ← 받은 공문이 쌓이는 곳
#         파견교사 선발 계획 알림/
#      8월/                 ← 끝난 일을 옮겨 두는 곳
_INBOX_NAMES = ("공문", "공문서", "접수공문", "공문함", "수신공문")
_MONTH_DIR = re.compile(r"^\s*0?(?P<n>1[0-2]|[1-9])\s*월\s*$")

# 파일 이름 앞에 붙는 발신 기관과 부서. 폴더 이름에서는 군더더기다.
_ORG_PREFIX = re.compile(
    r"^\s*[가-힣]{2,12}(?:교육청|교육지원청|교육부|교육원|연수원|재단|연구원|진흥원|"
    r"협회|공단|공사|시청|구청|군청|위원회|본부|센터|학교)\s+")
_DEPT_PREFIX = re.compile(r"^\s*[가-힣]{2,12}(?:지원과|교육과|담당관|과|부|팀|실)\s+")


@dataclass
class Item:
    path: Path
    receipt: str
    role: str
    title: str


@dataclass
class Group:
    receipt: str
    items: list[Item] = field(default_factory=list)

    @property
    def body(self) -> Item | None:
        for item in self.items:
            if item.role == ROLE_BODY:
                return item
        return None

    @property
    def title(self) -> str:
        source = self.body or (self.items[0] if self.items else None)
        return source.title if source else self.receipt

    def folder_name(self) -> str:
        return safe_folder_name(self.title) or self.receipt


# ------------------------------------------------------------------ 해석

def parse_name(filename: str) -> tuple[str, str, str]:
    """파일 이름에서 (접수번호, 역할, 제목)을 뽑는다.

    접수번호가 없으면 빈 문자열을 돌려준다. 그런 파일은 묶지 않고 그냥 둔다.
    """
    stem = Path(filename).stem
    stem = unicodedata.normalize("NFC", stem)

    receipt = ""
    match = _RECEIPT.match(stem)
    if match:
        receipt = f"{match.group('org')}-{match.group('no')}"
        stem = stem[match.end():]

    role = ROLE_ALONE
    match = _ROLE.match(stem)
    if match:
        role = ROLE_BODY if "본" in match.group("role") else ROLE_ATTACH
        stem = stem[match.end():]

    return receipt, role, _clean(stem)


def _clean(text: str) -> str:
    text = text.replace("_", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .-")


def safe_folder_name(title: str) -> str:
    """공문 제목을 폴더 이름으로 쓸 수 있게 다듬는다."""
    body = _ILLEGAL.sub(" ", title or "")
    body = re.sub(r"\s+", " ", body).strip(" .")
    body = _strip_org(body)
    if len(body) > MAX_FOLDER_NAME:
        body = body[:MAX_FOLDER_NAME].rstrip(" .") + "…"
    return body.strip(" .")


def same_file_content(one: Path, other: Path) -> bool:
    """두 파일의 내용이 같은지. 크기가 다르면 읽지 않는다."""
    try:
        if one.stat().st_size != other.stat().st_size:
            return False
        with one.open("rb") as a, other.open("rb") as b:
            while True:
                chunk_a, chunk_b = a.read(262144), b.read(262144)
                if chunk_a != chunk_b:
                    return False
                if not chunk_a:
                    return True
    except OSError:
        return False        # 못 읽으면 같다고 우기지 않는다 (지우면 안 되므로)


def to_trash(path: Path) -> bool:
    """휴지통으로 보낸다. 지운 게 아니라 되돌릴 수 있어야 한다.

    같은 파일을 또 받은 것이라 해도 사람이 만든 파일을 프로그램이 영영
    지워서는 안 된다. 윈도우가 아니거나 실패하면 False 를 돌려주고 부르는
    쪽이 파일을 그대로 둔다.
    """
    if sys.platform != "win32":
        return False
    try:
        from ctypes import wintypes

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [("hwnd", wintypes.HWND),
                        ("wFunc", wintypes.UINT),
                        ("pFrom", wintypes.LPCWSTR),
                        ("pTo", wintypes.LPCWSTR),
                        ("fFlags", ctypes.c_uint16),
                        ("fAnyOperationsAborted", wintypes.BOOL),
                        ("hNameMappings", wintypes.LPVOID),
                        ("lpszProgressTitle", wintypes.LPCWSTR)]

        FO_DELETE = 3
        FOF_ALLOWUNDO = 0x0040          # 지우지 말고 휴지통으로
        FOF_NOCONFIRMATION = 0x0010     # 하나씩 물어보지 않는다
        FOF_SILENT = 0x0004
        FOF_NOERRORUI = 0x0400

        operation = SHFILEOPSTRUCTW(
            None, FO_DELETE,
            str(path.resolve()) + "\0\0", None,
            FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI,
            False, None, None)
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
        return result == 0 and not path.exists()
    except Exception:  # noqa: BLE001
        return False


def unique_file(parent: Path, name: str) -> Path:
    """같은 이름이 있으면 꼬리표를 붙인다. `계획.hwp` → `계획 (2).hwp`"""
    stem, suffix = Path(name).stem, Path(name).suffix
    for index in range(2, 100):
        candidate = parent / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
    return parent / f"{stem} ({os.getpid()}){suffix}"


def unique_dir(parent: Path, name: str, hint: str = "") -> Path:
    """같은 이름이 있으면 접수번호를 붙여 구분한다."""
    candidate = parent / (name or "공문")
    if not candidate.exists():
        return candidate
    if hint:
        marked = parent / f"{name} ({hint.split('-')[-1]})"
        if not marked.exists():
            return marked
    for index in range(2, 30):
        numbered = parent / f"{name} ({index})"
        if not numbered.exists():
            return numbered
    return candidate


def _strip_org(title: str) -> str:
    """앞머리의 기관명과 부서명을 걷어낸다. 다 걷어내면 원래대로 둔다."""
    trimmed = title
    for pattern in (_ORG_PREFIX, _DEPT_PREFIX, _DEPT_PREFIX):
        stripped = pattern.sub("", trimmed, count=1)
        if stripped.strip():
            trimmed = stripped
    return trimmed.strip() or title


# ------------------------------------------------------------------ 계획

def plan(folder: Path) -> tuple[list[Group], list[Path]]:
    """폴더 바로 아래 흩어져 있는 파일들을 묶음별로 나눈다.

    이미 하위 폴더에 들어가 있는 파일은 건드리지 않는다.

    형식은 가리지 않는다. zip 이나 png 처럼 내용을 읽지 못하는 첨부도
    이름 앞에 같은 접수번호가 붙어 내려오므로 같은 폴더로 들어가야 한다.
    접수번호가 없는 파일은 loose 로 빠져 제자리에 그대로 남는다.
    """
    groups: dict[str, Group] = {}
    loose: list[Path] = []

    for path in sorted(folder.glob("*")):
        if not path.is_file():
            continue
        if path.name.startswith(("~$", ".")):
            continue
        receipt, role, title = parse_name(path.name)
        if not receipt:
            loose.append(path)
            continue
        groups.setdefault(receipt, Group(receipt)).items.append(
            Item(path, receipt, role, title or path.stem))

    return list(groups.values()), loose


def organize(folder: Path, titles: dict[str, str] | None = None,
             dry_run: bool = False) -> dict:
    """묶음마다 폴더를 만들고 파일을 옮긴다.

    titles 에 접수번호별 제목을 넘기면 그것을 폴더 이름으로 쓴다.
    본문에서 읽어 낸 제목이 파일 이름보다 깔끔하기 때문이다.

    갈 자리에 같은 이름이 이미 있으면 — 같은 공문을 또 내려받은 것이다 —
    내용을 견줘 본다. 똑같으면 새로 받은 것을 휴지통으로 보내고, 다르면
    (고쳐 올라온 판) 꼬리표를 붙여 나란히 넣는다. 예전에는 둘 다 아니고
    그냥 건너뛰어서, 인박스에 남은 파일이 정리를 아무리 눌러도 꿈쩍하지
    않았다.
    """
    titles = titles or {}
    groups, loose = plan(folder)
    moved = skipped = trashed = renamed = 0
    made: list[str] = []
    problems: list[str] = []

    for group in groups:
        # 파일이 하나뿐이고 본문도 아니면 굳이 폴더로 감싸지 않는다
        if len(group.items) < 2 and not group.body:
            skipped += len(group.items)
            continue

        name = safe_folder_name(titles.get(group.receipt, "")) or group.folder_name()
        target = folder / name
        if dry_run:
            made.append(name)
            # 갈 자리에 같은 이름이 이미 있는지 미리 견줘 둔다. 무엇이
            # 휴지통으로 가고 무엇이 꼬리표를 달지 눌러 보기 전에 알려야 한다.
            for item in group.items:
                landing = target / item.path.name
                if target.is_dir() and landing.exists():
                    if same_file_content(item.path, landing):
                        trashed += 1
                    else:
                        renamed += 1
                        moved += 1
                else:
                    moved += 1
            continue
        if target.exists() and not target.is_dir():
            target = unique_dir(folder, name, group.receipt)

        try:
            target.mkdir(exist_ok=True)
        except OSError as exc:
            problems.append(f"{target.name}: 폴더를 만들지 못했습니다 ({exc})")
            continue
        made.append(target.name)

        for item in group.items:
            destination = target / item.path.name
            if destination.exists():
                if same_file_content(item.path, destination):
                    # 똑같은 것을 또 받았다. 남겨 둬 봐야 헷갈리기만 한다.
                    if to_trash(item.path):
                        trashed += 1
                    else:
                        skipped += 1
                        problems.append(f"{item.path.name}: 같은 파일인데 "
                                        "휴지통으로 보내지 못했습니다")
                    continue
                # 이름만 같고 내용이 다르다 — 고쳐 올라온 판이므로 함께 둔다
                destination = unique_file(target, item.path.name)
                try:
                    item.path.rename(destination)
                    renamed += 1
                    moved += 1
                except OSError as exc:
                    problems.append(f"{item.path.name}: 옮기지 못했습니다 ({exc})")
                continue
            try:
                item.path.rename(destination)
                moved += 1
            except OSError as exc:
                problems.append(f"{item.path.name}: 옮기지 못했습니다 ({exc})")

    return {
        "moved": moved,
        "skipped": skipped,
        "trashed": trashed,
        "renamed": renamed,
        "folders": made,
        "loose": len(loose),
        "problems": problems[:10],
    }


# ------------------------------------------------------------- 묶음 열쇠

def group_key(path: Path, folder: Path, receipt_in_body: str = "") -> tuple[str, str]:
    """저장할 때 쓸 (묶음 열쇠, 역할).

    순서대로 이름의 접수번호, 본문에서 읽은 접수번호, 들어 있는 폴더를 본다.
    """
    receipt, role, _ = parse_name(path.name)
    if not receipt and receipt_in_body:
        receipt = receipt_in_body
    if receipt:
        return receipt, role

    try:
        relative = path.relative_to(folder)
    except ValueError:
        relative = Path(path.name)
    if len(relative.parts) > 1:                 # 하위 폴더에 들어 있으면 그 폴더로 묶는다
        return f"폴더:{relative.parts[0]}", role
    return f"파일:{path.name}", role


# --------------------------------------------------------- 업무 폴더 구조

def resolve_workspace(folder: Path) -> tuple[Path, Path]:
    """(업무 루트, 공문 인박스)를 알아낸다.

    선생님들이 흔히 쓰는 구조를 그대로 따른다.

        1. 교무기획/        ← 업무 루트
           공문/            ← 받은 공문
           8월/  9월/       ← 끝난 일을 옮겨 두는 곳

    고르신 폴더가 공문 폴더면 그 위를 루트로 보고, 루트를 고르셨으면
    그 안의 공문 폴더를 찾는다. 없으면 만들 자리만 정해 둔다.
    """
    folder = folder.resolve()

    if _looks_like_inbox(folder.name):
        return folder.parent, folder

    for child in sorted(folder.iterdir()) if folder.is_dir() else []:
        if child.is_dir() and _looks_like_inbox(child.name):
            return folder, child

    if _has_month_dirs(folder):
        return folder, folder / _INBOX_NAMES[0]

    return folder.parent, folder


def _looks_like_inbox(name: str) -> bool:
    cleaned = re.sub(r"^[\d.\s]+", "", name).strip()
    return cleaned in _INBOX_NAMES


def _has_month_dirs(folder: Path) -> bool:
    if not folder.is_dir():
        return False
    return sum(1 for c in folder.iterdir()
               if c.is_dir() and _MONTH_DIR.match(c.name)) >= 2


def month_dirs(base: Path) -> dict[int, Path]:
    """이미 있는 월별 폴더를 찾는다. 2월이든 02월이든 같은 것으로 본다."""
    found: dict[int, Path] = {}
    if not base.is_dir():
        return found
    for child in sorted(base.iterdir()):
        match = _MONTH_DIR.match(child.name) if child.is_dir() else None
        if match:
            found.setdefault(int(match.group("n")), child)
    return found


def month_dir(base: Path, month: int, create: bool = True) -> Path:
    existing = month_dirs(base).get(month)
    if existing:
        return existing
    target = base / f"{month}월"
    if create:
        target.mkdir(parents=True, exist_ok=True)
    return target


# ------------------------------------------------------- 완료된 업무 정리

def archive(base: Path, inbox: Path, entries: list[dict], dry_run: bool = False) -> dict:
    """끝난 공문을 마감 월에 해당하는 폴더로 옮긴다.

    entries 는 {"title", "month", "paths"} 목록이다.
    공문 하나가 전용 폴더에 모여 있으면 폴더째 옮기고,
    흩어져 있으면 월 폴더 안에 새 폴더를 만들어 담는다.
    """
    moved = 0
    plans: list[tuple[str, str]] = []
    relocated: dict[str, str] = {}
    problems: list[str] = []

    for entry in entries:
        month = entry["month"]
        paths = [Path(p) for p in entry["paths"] if Path(p).exists()]
        if not paths:
            continue
        name = safe_folder_name(entry["title"]) or "공문"

        target_month = month_dir(base, month, create=not dry_run)
        parents = {p.parent for p in paths}
        whole = None
        if len(parents) == 1:
            only = parents.pop()
            if only != inbox and only.parent == inbox:
                whole = only

        if dry_run:
            plans.append((f"{month}월", name))
            moved += len(paths)
            continue

        destination = unique_dir(target_month, name, entry.get("receipt", ""))
        try:
            if whole is not None:
                whole.rename(destination)
                for path in paths:
                    relocated[str(path)] = str(destination / path.name)
                moved += len(paths)
            else:
                destination.mkdir(parents=True, exist_ok=True)
                for path in paths:
                    landing = destination / path.name
                    if landing.exists():
                        continue
                    path.rename(landing)
                    relocated[str(path)] = str(landing)
                    moved += 1
            plans.append((target_month.name, destination.name))
        except OSError as exc:
            problems.append(f"{name}: 옮기지 못했습니다 ({exc})")

    return {
        "moved": moved,
        "plans": plans,
        "relocated": relocated,
        "problems": problems[:10],
    }
