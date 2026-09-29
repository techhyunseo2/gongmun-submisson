"""공문정리함제출 — 실행 진입점.

  python app.py                     설정 폴더를 훑고 브라우저를 연다
  python app.py --folder D:/공문     폴더를 지정하고 저장한다
  python app.py --rescan            이미 읽은 파일까지 전부 다시 분석한다
  python app.py --no-browser        서버만 띄운다
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from classify import CATEGORIES, CATEGORY_ORDER, days_left  # noqa: E402
from store import Store  # noqa: E402
import extract  # noqa: E402
import organize  # noqa: E402

def _base_dir() -> Path:
    """exe로 묶이면 파일들이 임시 폴더에 풀린다. 그때는 그쪽을 봐야 한다."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


BASE_DIR = _base_dir()
HOME_DIR = Path.home() / ".gongmun-submisson"
CONFIG_PATH = HOME_DIR / "config.json"
DB_PATH = HOME_DIR / "docs.db"
# 버전을 올리고 커밋하면 GitHub이 알아서 새 릴리스를 만든다.
# 이미 깔려 있는 프로그램들은 그 릴리스를 보고 스스로 갱신한다.
VERSION = "1.0.0"

# 업데이트를 받아 올 저장소. "사용자이름/저장소이름" 형태로 적는다.
# 공개 저장소여야 한다. 비공개면 받는 쪽에서 접근하지 못한다.
UPDATE_REPO = "techhyunseo2/gongmun-submisson"

PORT = 8877
PORT_TRIES = 12

# 함께 배포하는 글꼴과 그 라이선스. 예전에는 글꼴을 외부 CDN 에서 받아
# 썼는데, 실행할 때마다 이용자 IP 가 제3자에게 나가고 학교망이 CDN 을
# 막으면 글꼴이 조용히 바뀌었다. 이제 프로그램 안에 넣어 배포한다.
# Pretendard 는 SIL Open Font License 1.1 — 함께 배포하려면 라이선스
# 전문을 같이 두어야 하므로 Pretendard-OFL.txt 도 같이 넣는다.
ASSETS = {
    "/assets/PretendardVariable.woff2": "font/woff2",
    "/assets/Pretendard-OFL.txt": "text/plain; charset=utf-8",
}


# ------------------------------------------------------------------ 설정

def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def save_config(config: dict) -> None:
    HOME_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_inbox(chosen: Path) -> tuple[Path, Path]:
    """(업무 루트, 공문 인박스)를 정하고 인박스가 없으면 만든다.

    월별 폴더에는 공문 말고도 제출 자료나 개인정보가 든 파일이 섞여 있다.
    그래서 프로그램이 들여다보는 곳은 오직 공문 인박스 한 곳뿐이다.
    """
    base, inbox = organize.resolve_workspace(chosen)
    try:
        inbox.mkdir(parents=True, exist_ok=True)
    except OSError:
        return chosen.parent, chosen
    return base, inbox


def resolve_folder(cli_folder: str | None, ask: bool = False) -> Path:
    config = load_config()
    if cli_folder:
        folder = Path(cli_folder).expanduser().resolve()
        config["folder"] = str(folder)
        save_config(config)
        return folder
    if config.get("folder") and Path(config["folder"]).is_dir():
        return Path(config["folder"])

    folder = ask_folder() if ask else None
    if folder is None:
        folder = Path.home() / "Documents" / "공문"
        if not folder.exists():
            folder = Path.home() / "Downloads" / "공문"
    folder.mkdir(parents=True, exist_ok=True)
    config["folder"] = str(folder.resolve())
    save_config(config)
    return folder.resolve()


def ask_folder() -> Path | None:
    """첫 실행 때 공문을 모아 둘 폴더를 창으로 고르게 한다."""
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox
    except ImportError:
        return None

    root = tk.Tk()
    root.withdraw()
    try:
        suggested = Path.home() / "Documents" / "공문"
        messagebox.showinfo(
            "공문정리함제출",
            "공문을 모아 둘 폴더를 하나 정해 주세요.\n\n"
            "앞으로 에듀파인에서 공문을 내려받아 이 폴더에 넣으면\n"
            "프로그램이 알아서 읽고 기한 순으로 정리해 줍니다.\n\n"
            f"따로 만들어 두신 폴더가 없으면\n{suggested}\n폴더를 새로 만들어 쓰셔도 됩니다.",
        )
        suggested.mkdir(parents=True, exist_ok=True)
        chosen = filedialog.askdirectory(title="공문을 모아 둘 폴더 고르기",
                                         initialdir=str(suggested))
        return Path(chosen) if chosen else suggested
    finally:
        root.destroy()


# -------------------------------------------------------------- 파일 열기

def open_in_os(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def _allow_foreground_steal() -> None:
    """다른 프로세스가 창을 앞으로 세워도 된다고 윈도우에 알린다.

    윈도우는 포그라운드가 아닌 프로세스가 남의 창을 앞으로 끌어올리는 것을
    막는다. 우리가 탐색기를 열 때 화면 앞에 있는 것은 브라우저이므로,
    탐색기 창이 다른 창 뒤에서 열려 "아무 일도 안 일어났다" 처럼 보인다.
    우리가 포그라운드가 아니면 이 호출은 그냥 실패하며, 실패해도 해가 없다.
    """
    try:
        ctypes.windll.user32.AllowSetForegroundWindow(-1)   # ASFW_ANY
    except Exception:  # noqa: BLE001
        pass


WIDGET_TITLE = "공문정리함제출"


def raise_running_widget(title: str = WIDGET_TITLE) -> bool:
    """이미 떠 있는 위젯 창을 밖에서 찾아 앞으로 세운다. 세웠으면 True.

    **떠 있는 판의 협조에 기대지 않는다.** `/api/show` 로 부탁하는 길은 그
    판이 그 길을 아는 판일 때만 듣는다. 옛 버전이 돌고 있으면 404 가 나고,
    그러면 안내창으로 물러나는데 **그 안내창마저 다른 창 뒤에 숨는다.**
    쓰는 분에게는 "아무 반응이 없다" 로 보인다.

    다시 설치해도 낫지 않는다 — 파일만 새것으로 바뀌고 **이미 돌던 옛
    프로세스는 그대로 살아 있기** 때문이다. 실제로 몇 분이 지웠다 설치하기를
    되풀이하셨다.

    여기는 창을 직접 세우므로 상대가 어느 판이든 듣는다. 실패해도 해가
    없다 — 부르는 쪽이 뒤이어 안내창을 띄운다.
    """
    if sys.platform != "win32":
        return False
    try:
        from ctypes import wintypes
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        ours = kernel32.GetCurrentProcessId()
        found: list[int] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def visit(hwnd, _param):
            if not user32.IsWindowVisible(hwnd):
                return True
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == ours:        # 방금 뜬 우리 자신은 건너뛴다
                return True
            name = ctypes.create_unicode_buffer(160)
            user32.GetWindowTextW(hwnd, name, 160)
            if name.value == title:
                found.append(hwnd)
            return True

        user32.EnumWindows(visit, 0)
        if not found:
            return False

        mine = kernel32.GetCurrentThreadId()
        front = user32.GetForegroundWindow()
        theirs = user32.GetWindowThreadProcessId(front, None)
        joined = bool(theirs and theirs != mine
                      and user32.AttachThreadInput(theirs, mine, True))
        try:
            for hwnd in found:
                user32.ShowWindow(hwnd, 9)                      # SW_RESTORE
                # 맨 위 칸으로 올렸다가 곧바로 내린다. 올리기만 하면 '항상
                # 위' 를 꺼 두신 분의 설정을 어기게 된다.
                user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, _KEEP)   # TOPMOST
                user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, _KEEP)   # NOTOPMOST
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
        finally:
            if joined:
                user32.AttachThreadInput(theirs, mine, False)
        return True
    except Exception:  # noqa: BLE001 — 못 세워도 진행은 된다
        return False


# SetWindowPos: 크기·자리를 건드리지 말고 초점도 뺏지 말 것
_KEEP = 0x0001 | 0x0002 | 0x0010


def _raise_explorer_window(folder_name: str) -> None:
    """방금 연 탐색기 창을 찾아 앞으로 끌어올린다.

    창이 뜨는 데 시간이 걸리므로 잠깐 지켜본다. HTTP 응답을 붙잡아 두지
    않도록 딴 스레드에서 돈다. 실패해도 조용히 넘어간다 — 창은 어차피
    열려 있고, 앞으로 못 세운 것뿐이다.
    """
    if not folder_name:
        return

    def work() -> None:
        try:
            from ctypes import wintypes
            user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
            found: list[int] = []

            @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            def visit(hwnd, _param):
                if not user32.IsWindowVisible(hwnd):
                    return True
                name = ctypes.create_unicode_buffer(128)
                user32.GetClassNameW(hwnd, name, 128)
                if name.value not in ("CabinetWClass", "ExploreWClass"):
                    return True
                title = ctypes.create_unicode_buffer(320)
                user32.GetWindowTextW(hwnd, title, 320)
                # 제목은 대개 폴더 이름이다. 엉뚱한 창을 끌어올리지 않도록
                # 이름이 맞는 것만 고른다.
                if title.value.startswith(folder_name):
                    found.append(hwnd)
                    return False
                return True

            for _ in range(15):                 # 3초까지 기다린다
                found.clear()
                user32.EnumWindows(visit, 0)
                if found:
                    break
                time.sleep(0.2)
            if not found:
                return

            hwnd = found[0]
            user32.ShowWindow(hwnd, 9)          # SW_RESTORE — 최소화돼 있으면 편다
            # 앞에 있는 창의 입력 큐에 잠시 붙어야 포그라운드를 넘겨받을 수 있다
            ahead = user32.GetForegroundWindow()
            ours = kernel32.GetCurrentThreadId()
            theirs = user32.GetWindowThreadProcessId(ahead, None)
            attached = user32.AttachThreadInput(ours, theirs, True) if theirs else False
            try:
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
            finally:
                if attached:
                    user32.AttachThreadInput(ours, theirs, False)
        except Exception:  # noqa: BLE001
            pass                                # 창은 열렸다. 그걸로 충분하다

    threading.Thread(target=work, daemon=True).start()


def reveal_in_os(path: Path) -> None:
    """파일이 든 폴더를 열되, 그 파일을 골라 놓은 채로 연다.

    첨부가 여럿인 공문에서 "이 파일이 어디 있지" 를 바로 알 수 있게 한다.
    파일을 고르는 기능이 없는 환경에서는 폴더만 연다.
    """
    if sys.platform.startswith("win"):
        # 반드시 문자열 한 줄로 넘긴다. 리스트로 주면 파이썬이 공백이 든
        # "/select,경로" 를 통째로 따옴표로 감싸 버리는데, 그러면 explorer
        # 가 /select 를 스위치로 알아보지 못하고 엉뚱하게 문서 폴더를 연다.
        # 따옴표는 경로에만 씌워야 한다.
        #   맞음  : explorer /select,"C:\업무 폴더\공문\문서.hwp"
        #   틀림  : explorer "/select,C:\업무 폴더\공문\문서.hwp"
        # 윈도우 파일명에는 큰따옴표를 쓸 수 없으므로 이 조립은 안전하다.
        # explorer 는 성공해도 종료 코드 1 을 내므로 결과는 보지 않는다.
        _allow_foreground_steal()
        subprocess.Popen(f'explorer /select,"{path}"')
        # 창이 다른 창 뒤에서 열리면 아무 일도 안 일어난 것처럼 보인다.
        _raise_explorer_window(path.parent.name)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        open_in_os(path.parent)


# ------------------------------------------------------------------ ICS

def _ics_escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;")
                .replace(",", "\\,").replace("\n", "\\n"))


def _ics_fold(line: str) -> str:
    """한 줄이 75옥텟을 넘으면 규격대로 접는다."""
    raw = line.encode("utf-8")
    if len(raw) <= 73:
        return line
    out, chunk = [], b""
    for char in line:
        encoded = char.encode("utf-8")
        limit = 73 if not out else 72
        if len(chunk) + len(encoded) > limit:
            out.append(chunk.decode("utf-8"))
            chunk = b""
        chunk += encoded
    out.append(chunk.decode("utf-8"))
    return "\r\n ".join(out)


def build_ics(docs: list[dict]) -> str:
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//gongmun-submisson//KR",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:공문 일정",
    ]
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    for doc in docs:
        when = doc.get("deadline") or doc.get("event_date")
        if not when:
            continue
        try:
            start = date.fromisoformat(when[:10])
        except ValueError:
            continue
        # 종일 일정은 DTEND(다음 날)가 없으면 구글 캘린더가 조용히 무시한다.
        end = start + timedelta(days=1)
        # "[마감]" 같은 앞말은 붙이지 않는다 — 캘린더에 한번 넣으면 상태가
        # 바뀌어도 따라 갱신되지 않아 오히려 헷갈린다.
        summary = _ics_escape(doc.get("title") or doc["filename"])[:180]
        detail = _ics_escape((doc.get("summary") or "")[:300])
        # UID 는 파일 내용 해시라 다시 내보내도 같은 값이다. 같은 달력에
        # 다시 가져오면 새 일정이 아니라 기존 일정을 갱신하게 하려는 것.
        lines += [
            "BEGIN:VEVENT",
            f"UID:{doc['id']}@gongmun-submisson",
            f"DTSTAMP:{stamp}",
            f"LAST-MODIFIED:{stamp}",
            "SEQUENCE:0",
            f"DTSTART;VALUE=DATE:{start.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{end.strftime('%Y%m%d')}",
            _ics_fold(f"SUMMARY:{summary}"),
            _ics_fold(f"DESCRIPTION:{detail}"),
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    # RFC 5545: 마지막 줄도 CRLF 로 끝나야 한다.
    return "\r\n".join(lines) + "\r\n"


# ---------------------------------------------------------------- 서버

class Handler(BaseHTTPRequestHandler):
    store: Store
    folder: Path          # 공문 인박스 — 여기만 읽는다
    base: Path            # 업무 루트 — 월별 폴더를 만드는 곳

    # 위젯을 다시 앞으로 불러 달라는 요청이 올 때마다 오른다. 위젯이
    # 메인 스레드에서 이 값만 지켜본다 — tkinter 를 요청 스레드에서
    # 만지면 안 되기 때문이다.
    show_calls: int = 0

    def log_message(self, *args):  # 콘솔을 조용하게
        pass

    # ---------------------------------------------------------- helpers

    def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None):
        # extra 로 같은 헤더를 덮어쓸 수 있게 사전으로 모았다가 한 번씩만 보낸다.
        # (글꼴처럼 캐시해도 되는 것은 no-store 를 갈아끼운다)
        headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
        }
        headers.update(extra or {})
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload, status: int = 200):
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    # -------------------------------------------------------------- GET

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        query = parse_qs(parsed.query)

        if route in ("/", "/index.html"):
            html = (BASE_DIR / "ui.html").read_bytes()
            return self._send(200, html, "text/html; charset=utf-8")

        # 함께 넣어 배포하는 파일들. 이름을 목록으로 못박아 두어 엉뚱한
        # 경로를 읽어 가지 못하게 한다.
        if route in ASSETS:
            target = BASE_DIR / "assets" / route.rsplit("/", 1)[-1]
            try:
                body = target.read_bytes()
            except OSError:
                return self._send(404, b"not found", "text/plain; charset=utf-8")
            return self._send(200, body, ASSETS[route],
                              {"Cache-Control": "public, max-age=604800"})

        if route == "/api/state":
            return self._json(self._state())

        if route == "/api/show":
            # 프로그램을 또 실행했을 때 두 번째 판이 여기를 두드린다.
            # 위젯이 다른 창 뒤에 숨어 되살릴 길이 없던 것을 푸는 자리다.
            Handler.show_calls += 1
            return self._json({"ok": True})

        if route == "/api/rev":
            # 화면이 몇 초마다 물어보는 자리. 내용이 바뀌었는지만 알려 준다.
            return self._json({"rev": self.store.rev})

        if route == "/api/scan":
            force = query.get("force", ["0"])[0] == "1"
            report = self.store.scan(self.folder, force=force)
            state = self._state()
            state["report"] = report
            return self._json(state)

        if route == "/api/doc":
            doc = self.store.get(query.get("id", [""])[0])
            return self._json(doc or {"error": "찾을 수 없습니다."}, 200 if doc else 404)

        if route == "/api/open":
            doc = self.store.get(query.get("id", [""])[0])
            if not doc:
                return self._json({"error": "찾을 수 없습니다."}, 404)
            target = Path(doc["path"])
            if not target.exists():
                return self._json({"error": "파일이 폴더에 없습니다."}, 404)
            open_in_os(target)
            return self._json({"ok": True})

        if route == "/api/organize":
            preview = query.get("preview", ["0"])[0] == "1"
            report = organize.organize(self.folder, self._titles(), dry_run=preview)
            if not preview:
                self.store.scan(self.folder)
            state = self._state()
            state["organized"] = report
            return self._json(state)

        if route == "/api/archive":
            preview = query.get("preview", ["0"])[0] == "1"
            state = self._archive(preview)
            return self._json(state)

        if route == "/api/preview-image":
            # 한글 문서 안에 든 첫 쪽 그림. 글자만 뽑아 보여 주는 것보다
            # 표·서식이 그대로 보인다. 없으면 404 를 주고 화면이 글자
            # 미리보기로 물러난다.
            doc = self.store.get(query.get("id", [""])[0])
            if not doc:
                return self._json({"error": "찾을 수 없습니다."}, 404)
            image = extract.preview_image(Path(doc["path"]))
            if not image:
                return self._json({"error": "미리보기 그림이 없습니다."}, 404)
            return self._send(200, image, "image/png",
                              {"Cache-Control": "private, max-age=604800"})

        if route == "/api/file":
            # PDF 를 브라우저 내장 뷰어로 보여 주기 위해 원본을 그대로 넘긴다.
            # 우리 기록에 있는 문서만 — 아무 경로나 읽어 가지 못하게 한다.
            doc = self.store.get(query.get("id", [""])[0])
            if not doc:
                return self._json({"error": "찾을 수 없습니다."}, 404)
            target = Path(doc["path"])
            if target.suffix.lower() != ".pdf" or not target.is_file():
                return self._json({"error": "보여 줄 수 없는 형식입니다."}, 404)
            try:
                data = target.read_bytes()
            except OSError:
                return self._json({"error": "읽지 못했습니다."}, 404)
            return self._send(200, data, "application/pdf",
                              {"Cache-Control": "private, max-age=604800"})

        if route == "/api/reveal":
            doc = self.store.get(query.get("id", [""])[0])
            if not doc:
                return self._json({"error": "찾을 수 없습니다."}, 404)
            target = Path(doc["path"])
            if target.exists():
                reveal_in_os(target)
            elif target.parent.is_dir():
                # 파일은 없어졌어도 있던 자리를 열어 주는 편이 낫다
                open_in_os(target.parent)
            else:
                return self._json({"error": "폴더를 찾지 못했습니다."}, 404)
            return self._json({"ok": True})

        if route == "/api/open-folder":
            open_in_os(self.folder)
            return self._json({"ok": True})

        if route == "/api/calendar.ics":
            # 목록과 같은 묶음 단위로 내보낸다 (첨부에만 기한이 있어도 잡힌다).
            docs = [d for d in fold_groups(self.store.all_docs()) if not d["done"]]
            # 브라우저에서 고른 공문만 담는다. ids 가 없으면 안 담는다 —
            # 이제 내보내기는 반드시 골라서 하도록 바뀌었다.
            keep = {x for x in query.get("ids", [""])[0].split(",") if x}
            docs = [d for d in docs if d["id"] in keep]
            body = build_ics(docs).encode("utf-8")
            name = "gongmun-submisson-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".ics"
            return self._send(200, body, "text/calendar; charset=utf-8",
                              {"Content-Disposition": f'attachment; filename="{name}"'})

        return self._send(404, b"not found", "text/plain; charset=utf-8")

    # ------------------------------------------------------------- POST

    def do_POST(self):  # noqa: N802
        route = urlparse(self.path).path
        payload = self._read_json()
        doc_id = payload.get("id", "")

        if route == "/api/done":
            done = bool(payload.get("done"))
            for member in payload.get("members") or [doc_id]:
                self.store.set_done(member, done)
        elif route == "/api/pin":
            pinned = bool(payload.get("pinned"))
            for member in payload.get("members") or [doc_id]:
                self.store.set_pinned(member, pinned)
        elif route == "/api/category":
            category = payload.get("category")
            if category not in CATEGORIES:
                return self._json({"error": "알 수 없는 유형입니다."}, 400)
            self.store.set_category(doc_id, category)
        elif route == "/api/memo":
            self.store.set_memo(doc_id, payload.get("memo", ""))
        elif route == "/api/deadline":
            self.store.set_deadline(doc_id, payload.get("deadline") or None)
        elif route == "/api/folder":
            folder = Path(unquote(payload.get("folder", ""))).expanduser()
            if not folder.is_dir():
                return self._json({"error": "그런 폴더가 없습니다."}, 400)
            base, inbox = resolve_inbox(folder.resolve())
            config = load_config()
            config["folder"] = str(inbox)
            save_config(config)
            Handler.base, Handler.folder = base, inbox
            self.store.scan(inbox)
            # 훑어서 달라진 게 없더라도 위젯은 폴더줄을 다시 칠해야 한다.
            self.store.touch()
        else:
            return self._json({"error": "알 수 없는 요청입니다."}, 404)

        return self._json(self._state())

    def _titles(self) -> dict[str, str]:
        """접수번호별 대표 제목. 본문에서 읽은 것을 우선한다."""
        titles: dict[str, str] = {}
        for group in fold_groups(self.store.all_docs()):
            key = group.get("receipt_number") or group.get("group_key") or ""
            if key and group.get("title"):
                titles[key] = group["title"]
        return titles

    def _archive(self, preview: bool) -> dict:
        """끝난 공문을 마감 월 폴더로 옮긴다.

        기한도 행사일도 없는 문서는 오늘 달로 보낸다 — 정리를 눌렀는데
        인박스에 그대로 남는 문서가 없게 한다.
        """
        base, inbox = self.base, self.folder
        today = date.today()
        entries = []
        for group in fold_groups(self.store.all_docs()):
            if not group["done"] or group.get("archived"):
                continue
            entries.append({
                "title": group.get("title") or group["filename"],
                "month": _month_of(group, today),
                "receipt": group.get("receipt_number") or "",
                "paths": group["paths"],
                "ids": [m["id"] for m in group["members"]],
            })

        report = organize.archive(base, inbox, entries, dry_run=preview)
        if not preview:
            moved = report.get("relocated", {})
            for entry in entries:
                for member_id, old in zip(entry["ids"], entry["paths"]):
                    if old in moved:
                        self.store.relocate(member_id, moved[old], f"{entry['month']}월")
        report["no_date"] = 0
        report["base"] = str(base)
        state = self._state()
        state["archived_report"] = report
        return state

    # -------------------------------------------------------------- 상태

    def _state(self) -> dict:
        today = date.today()
        docs = fold_groups(self.store.all_docs())
        for doc in docs:
            doc["days_left"] = days_left(doc.get("deadline"), today)
        docs.sort(key=_sort_key)
        counts = {key: 0 for key in CATEGORY_ORDER}
        for doc in docs:
            if not doc["done"]:
                counts[doc["category"]] = counts.get(doc["category"], 0) + 1
        urgent = [d for d in docs if not d["done"] and d["days_left"] is not None and d["days_left"] <= 3]
        return {
            "rev": self.store.rev,
            "folder": str(self.folder),
            "base": str(self.base),
            "inbox": str(self.folder),
            "months": sorted(organize.month_dirs(self.base)),
            "today": today.isoformat(),
            "categories": CATEGORIES,
            "order": CATEGORY_ORDER,
            "counts": counts,
            "urgent": len(urgent),
            "docs": docs,
        }


def fold_groups(docs: list[dict]) -> list[dict]:
    """같은 접수번호끼리 하나로 묶는다.

    본문이 대표가 되고 첨부는 딸린 문서로 붙는다. 기한과 날짜는 묶음 전체에서
    모으는데, 첨부의 제출 서식에만 기한이 적힌 경우가 흔하기 때문이다.
    """
    buckets: dict[str, list[dict]] = {}
    for doc in docs:
        buckets.setdefault(doc.get("group_key") or doc["id"], []).append(doc)

    folded: list[dict] = []
    for key, members in buckets.items():
        members.sort(key=lambda d: (d.get("role") != organize.ROLE_BODY, d["filename"]))
        lead = _pick_lead(members)
        entry = dict(lead)
        entry["group_key"] = key
        entry["members"] = [
            {"id": m["id"], "filename": m["filename"], "role": m.get("role") or "",
             "error": m.get("error") or "", "path": m.get("path") or "",
             "readable": bool(m.get("readable", True))}
            for m in members
        ]
        # 대표 문서를 뺀 나머지가 첨부다. 역할 표시가 없는 파일(zip, png 처럼
        # 이름에 "(첨부)" 가 안 붙어 오는 것)도 세야 개수가 맞는다.
        entry["attachments"] = max(len(members) - 1, 0)
        entry["paths"] = [m["path"] for m in members]
        entry["archived"] = next((m.get("archived") for m in members if m.get("archived")), "")

        # 손으로 정한 기한이 있으면 그것이 먼저다. 없을 때만 묶음에서 가장
        # 이른 것을 고른다. 제출 기한이 첨부 서식에만 적힌 경우가 흔해서다.
        edited = next((m for m in members if m.get("deadline_edited")), None)
        if edited:
            entry["deadline"] = edited.get("deadline")
            entry["deadline_context"] = edited.get("deadline_context") or ""
            entry["deadline_edited"] = 1
        else:
            deadlines = sorted({m["deadline"] for m in members if m.get("deadline")})
            if deadlines:
                entry["deadline"] = deadlines[0]
                if not entry.get("deadline_context"):
                    source = next(m for m in members if m["deadline"] == deadlines[0])
                    entry["deadline_context"] = source.get("deadline_context") or ""
        events = sorted({m["event_date"] for m in members if m.get("event_date")})
        entry["event_date"] = events[0] if events else None
        entry["all_dates"] = sorted({d for m in members for d in (m.get("all_dates") or [])})
        entry["done"] = all(m["done"] for m in members)
        # 묶음 안의 어느 문서든 고정돼 있으면 묶음 전체를 고정으로 본다.
        entry["pinned"] = any(m.get("pinned") for m in members)
        folded.append(entry)
    return folded


def _pick_lead(members: list[dict]) -> dict:
    """묶음을 대표할 문서. 본문이 있으면 본문, 없으면 판단이 가장 또렷한 것.

    읽지 못하는 파일(zip, png…)은 대표로 세우지 않는다. 제목도 기한도
    없어서 목록에 이름만 덩그러니 남기 때문이다. 묶음이 통째로 그런
    파일뿐일 때만 어쩔 수 없이 그중 하나를 쓴다.
    """
    readable = [m for m in members if m.get("readable", True)]
    for member in readable or members:
        if member.get("role") == organize.ROLE_BODY:
            return member
    ranking = {"높음": 0, "보통": 1, "낮음": 2}
    return min(readable or members,
               key=lambda m: (ranking.get(m.get("confidence"), 3),
                              not m.get("deadline")))


def _month_of(group: dict, today: date) -> int:
    """어느 달 폴더로 보낼지 정한다. 마감 → 행사일 순으로 보고,
    둘 다 없으면 오늘 달로 보낸다.

    예전에는 마지막으로 파일이 고쳐진 날짜(modified)를 봤는데, 옮기거나
    다시 저장할 때마다 이 날짜가 바뀌고, 받은 지 오래된 문서는 이미 지난
    달을 가리켜 정리를 눌러도 아무 데도 못 가고 인박스에 그대로 남았다.
    """
    for key in ("deadline", "event_date"):
        value = group.get(key)
        if value:
            try:
                return int(str(value).split("-")[1])
            except (IndexError, ValueError):
                continue
    return today.month


def _sort_key(doc: dict):
    """고정한 것이 맨 위, 그다음 마감 임박한 것부터, 마감 없는 것은 파일 날짜 최신순."""
    if doc.get("pinned") and not doc["done"]:
        return (-1, 0, doc["title"] or "")
    if doc["done"]:
        return (2, 0, "")
    if doc["days_left"] is not None:
        return (0, doc["days_left"], doc["title"] or "")
    return (1, 0, "-" + (doc.get("modified") or ""))


# ------------------------------------------------------------------ main

def running_port(port: int) -> int | None:
    """같은 프로그램이 이미 떠 있으면 그쪽이 쓰는 포트를 알려 준다.

    포트가 열려 있다는 것만으로는 부족하다. 다른 프로그램이 그 번호를
    쓰고 있을 수 있으므로, 우리 응답이 오는지까지 확인한다.
    """
    import json as _json
    import urllib.error
    import urllib.request
    for offset in range(PORT_TRIES):
        found = port + offset
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{found}/api/state",
                                        timeout=0.5) as response:
                data = _json.loads(response.read().decode("utf-8"))
                if "categories" in data and "docs" in data:
                    return found
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            continue
    return None


def already_running(port: int) -> bool:
    return running_port(port) is not None


def ask_to_surface(port: int) -> bool:
    """떠 있는 판에게 "앞으로 나와 달라" 고 부탁한다. 됐으면 True.

    위젯은 테두리 없는 창이라 작업 표시줄에 뜨지 않는다. 바탕화면 보기로
    가려지면 되살릴 방법이 없었다 — 다시 실행해 봐야 "이미 실행 중" 이라는
    말만 들었다. 이제 그 다시 실행이 곧 되살리기다.
    """
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/show",
                                    timeout=1.0) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def start_server(store: Store, folder: Path, port: int = PORT,
                 base: Path | None = None) -> tuple[ThreadingHTTPServer, int]:
    """API 서버를 띄우고 (서버, 실제로 쓴 포트)를 돌려준다.

    포트가 이미 쓰이고 있으면 옆 번호로 옮겨 간다.
    """
    Handler.store = store
    Handler.folder = folder
    Handler.base = base or getattr(Handler, "base", folder.parent)
    last: OSError | None = None
    for offset in range(PORT_TRIES):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port + offset), Handler)
        except OSError as exc:
            last = exc
            continue
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server, port + offset
    raise RuntimeError(f"쓸 수 있는 포트를 찾지 못했습니다: {last}")


def main() -> None:
    parser = argparse.ArgumentParser(description="공문정리함제출")
    parser.add_argument("--folder", help="공문을 모아 두는 폴더")
    parser.add_argument("--rescan", action="store_true", help="전부 다시 분석")
    parser.add_argument("--no-browser", action="store_true", help="브라우저를 열지 않음")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()

    folder = resolve_folder(args.folder)
    if not folder.is_dir():
        print(f"폴더를 찾을 수 없습니다: {folder}")
        sys.exit(1)

    base, folder = resolve_inbox(folder)
    store = Store(DB_PATH)
    print(f"업무 폴더: {base}")
    print(f"공문 폴더를 읽는 중: {folder}")
    report = store.scan(folder, force=args.rescan)
    print(f"새로 분석 {report['added']}건 · 그대로 {report['skipped']}건 · 실패 {report['failed']}건")

    server, port = start_server(store, folder, args.port, base=base)
    url = f"http://127.0.0.1:{port}/"
    print(f"주소: {url}   (종료는 Ctrl+C)")

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\n종료합니다.")
        server.shutdown()


if __name__ == "__main__":
    main()
