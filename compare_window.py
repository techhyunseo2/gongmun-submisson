"""화면 비교의 창 부분 — 드래그로 자리 고르기, 결과 보여 주기.

판단은 `screen_compare.py` 가 한다. 여기는 tkinter 만 다룬다.

쓰는 흐름은 이렇다. 한글 창 두 개를 나란히 띄워 둔 채로,

1. 위젯 우클릭 → "결재 전후 비교"
2. 화면이 살짝 어두워진다. 원본 쪽을 드래그
3. 다시 어두워진다. 수정본 쪽을 드래그
4. 수정본 그림에 달라진 자리가 빨간 상자로 뜬다

**DPI 를 건드리지 않는다.** `SetProcessDPIAware` 를 중간에 켜면 이미 떠
있는 tkinter 가 보는 좌표와 화면 좌표가 어긋나 엉뚱한 곳을 찍는다.
화면 배율이 걸려 있으면 두 장 모두 똑같이 흐려지므로 비교에는 지장이 없다.

**찍은 그림은 메모리에만 둔다.** 파일로 쓰지 않는다 — 화면에 무엇이
있을지 프로그램은 알 수 없기 때문이다. 자세한 것은 `screen_compare` 의
머리말 참고.
"""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import struct
import time
import tkinter as tk
import zlib

import screen_compare

# 고를 때 화면을 덮는 막의 짙기. 너무 짙으면 무엇을 고르는지 안 보인다.
VEIL = 0.28

# 막을 걷고 화면이 다시 그려지기를 기다리는 시간(초).
SETTLE = 0.15

# 표시 상자를 글자에서 이만큼 띄운다.
MARGIN = 3

# 결과 창이 화면을 다 잡아먹지 않도록 하는 한도.
MAX_VIEW = (1200, 760)


def _virtual_screen() -> tuple[int, int, int, int]:
    """모니터 여러 대를 합친 전체 화면 범위. 두 창이 다른 모니터에 있어도 되게."""
    metric = ctypes.windll.user32.GetSystemMetrics
    return metric(76), metric(77), metric(78), metric(79)


class _Box(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("whole", _Box), ("work", _Box),
                ("flags", wintypes.DWORD)]


def _monitor_at(x: int, y: int) -> tuple[int, int, int, int]:
    """그 자리가 속한 모니터 한 대의 범위. 작업 표시줄은 뺀 값.

    창을 화면 **전체** 한가운데 두면 안 된다. 모니터 두 대를 쓰면 그
    한가운데가 바로 두 화면이 갈리는 자리라, 안내가 반씩 잘려 읽기
    어렵다. 선생님들 대부분이 두 대를 쓰신다.
    """
    user32 = ctypes.windll.user32
    point = wintypes.POINT(x, y)
    handle = user32.MonitorFromPoint(point, 2)      # 가장 가까운 모니터
    info = _MonitorInfo()
    info.cbSize = ctypes.sizeof(_MonitorInfo)
    if not user32.GetMonitorInfoW(handle, ctypes.byref(info)):
        return _virtual_screen()
    work = info.work
    return work.left, work.top, work.right - work.left, work.bottom - work.top


def _grab_focus(window: tk.Misc) -> None:
    """이 창에 키보드 초점을 확실히 가져온다. 안 되면 조용히 넘어간다.

    Esc 가 안 듣는다는 말씀이 있었다. 테두리 없는 창은 윈도우가 키보드
    초점을 순순히 주지 않는데, 특히 **위젯을 감춘 직후** 가 그렇다 —
    창이 사라지면 초점이 다른 프로그램으로 넘어가고, 포그라운드가 아닌
    프로세스는 제 창을 앞으로 세우지 못하게 윈도우가 막는다.

    지금 앞에 선 창의 입력 대기줄에 잠깐 붙었다가(`AttachThreadInput`)
    초점을 넘겨받는다. `app.py` 가 탐색기 창을 앞으로 끌어올릴 때 쓰는
    것과 같은 방법이다. 실패해도 오른쪽 버튼으로 그만둘 수 있으므로
    막다른 길이 되지는 않는다.
    """
    try:
        user32 = ctypes.windll.user32
        # `winfo_id()` 는 **진짜 최상위 창이 아닐 수 있다.** 테두리 없는
        # 창에서 실측해 보니 자식 창 손잡이가 나왔다(13241590 ≠ 7802858).
        # 그 손잡이에 초점을 걸면 아무 일도 일어나지 않는다.
        handle = window.winfo_id()
        while True:
            parent = user32.GetAncestor(handle, 2)      # GA_ROOT
            if not parent or parent == handle:
                break
            handle = parent
        mine = ctypes.windll.kernel32.GetCurrentThreadId()
        front = user32.GetForegroundWindow()
        theirs = user32.GetWindowThreadProcessId(front, None)
        joined = bool(theirs and theirs != mine
                      and user32.AttachThreadInput(theirs, mine, True))
        try:
            user32.SetForegroundWindow(handle)
            user32.SetFocus(handle)
        finally:
            if joined:
                user32.AttachThreadInput(theirs, mine, False)
    except Exception:  # noqa: BLE001 — 못 가져와도 진행은 된다
        pass


class _Notice:
    """고르기 전에 무엇을 할지 알려 주는 창. 확인을 누르면 넘어간다.

    안내를 막 위에 얹지 않고 창으로 뺀 이유는 모니터가 두 대이기
    때문이다. 화면 한가운데는 곧 두 화면이 갈리는 자리라 글이 반씩
    잘렸다. 이 창은 **마우스가 있는 모니터 안** 에 뜨므로 걸치지 않는다.
    """

    def __init__(self, root: tk.Misc, step: str):
        self.ok = False
        self.window = tk.Toplevel(root)
        self.window.title("결재 전후 비교")
        self.window.resizable(False, False)

        frame = tk.Frame(self.window, padx=22, pady=18)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text=step, font=("맑은 고딕", 13, "bold"),
                 anchor="w", justify="left").pack(fill="x")
        tk.Label(frame, anchor="w", justify="left", wraplength=380,
                 font=("맑은 고딕", 10), pady=10,
                 text="종이의 좌우가 다 들어오게 넉넉히 끌어 주세요.\n"
                      "잘린 쪽은 비교할 수 없으므로 달라진 것으로 나옵니다."
                 ).pack(fill="x")
        tk.Label(frame, anchor="w", font=("맑은 고딕", 10), fg="#5C685F",
                 text="그만두려면  Esc  또는  마우스 오른쪽 버튼").pack(fill="x")

        buttons = tk.Frame(frame, pady=14)
        buttons.pack(fill="x")
        go = tk.Button(buttons, text="확인", width=10, command=self._go)
        go.pack(side="right")
        tk.Button(buttons, text="그만두기", width=10,
                  command=self.window.destroy).pack(side="right", padx=(0, 8))

        self.window.bind("<Escape>", lambda _event: self.window.destroy())
        self.window.bind("<Return>", lambda _event: self._go())
        self.window.protocol("WM_DELETE_WINDOW", self.window.destroy)

        # `transient` 는 쓰지 않는다. 부모가 숨겨져 있으면 딸린 창도 같이
        # 숨는데, 여기서는 고르는 동안 위젯을 감추므로 안내창이 아예 안
        # 뜬다. 자리를 잡은 뒤에 부르면 창을 부모 쪽으로 도로 옮기기도
        # 한다 — 왼쪽 모니터에 두려던 창이 오른쪽으로 끌려갔다.
        self.window.attributes("-topmost", True)
        self.window.update_idletasks()
        self._centre()
        # `grab_set` 은 쓰지 않는다. 고르는 동안 위젯은 어차피 감춰져 있어
        # 막을 것이 없는데, 모달 잠금이 남으면 다음 창이 열리지 못하고
        # 멈춘다(시험에서 실제로 걸렸다). 맨 위에 두는 것으로 충분하다.
        go.focus_set()
        _grab_focus(self.window)

    def _centre(self):
        """마우스가 있는 모니터 한가운데. 경계선에 걸치지 않게."""
        left, top, width, height = _monitor_at(*screen_compare.cursor_at())
        mine = self.window.winfo_reqwidth(), self.window.winfo_reqheight()
        x = left + (width - mine[0]) // 2
        y = top + (height - mine[1]) // 2
        # 왼쪽에 붙인 모니터는 x 가 음수다. 반드시 `+-1339` 꼴로 적는다 —
        # `-1339` 로 적으면 Tk 가 "오른쪽 끝에서 1339" 로 읽어 반대편으로
        # 보낸다. f-string 이 알아서 `+-1339` 를 만들어 준다.
        self.window.geometry(f"+{x}+{y}")

    def _go(self):
        self.ok = True
        self.window.destroy()

    def run(self) -> bool:
        try:
            self.window.wait_window()
        except tk.TclError:      # 이미 닫혔으면 기다릴 것이 없다
            pass
        return self.ok


class _Picker:
    """화면을 살짝 덮고 사각형 하나를 끌게 한다."""

    def __init__(self, root: tk.Misc, message: str):
        left, top, width, height = _virtual_screen()
        self.root = root
        self.start = None            # 막 위에 사각형을 그리는 자리 (tkinter)
        self.from_screen = None      # 실제로 찍을 자리 (윈도우 좌표)
        self.picked = None

        self.window = tk.Toplevel(root)
        self.window.overrideredirect(True)
        self.window.geometry(f"{width}x{height}+{left}+{top}")
        self.window.attributes("-topmost", True)
        self.window.attributes("-alpha", VEIL)
        self.window.configure(bg="black")

        self.canvas = tk.Canvas(self.window, bg="black", highlightthickness=0,
                                cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        # 막에는 글을 얹지 않는다. 화면 한가운데에 두면 모니터 두 대를
        # 쓰실 때 경계선에 걸려 반씩 잘린다. 안내는 앞서 뜨는 창이 맡는다.

        self.canvas.bind("<Button-1>", self._down)
        self.canvas.bind("<B1-Motion>", self._move)
        self.canvas.bind("<ButtonRelease-1>", self._up)

        # Esc 가 안 듣는다는 말씀이 있었는데 이 컴퓨터에서는 재현하지
        # 못했다. 짚이는 것은 키보드 초점이라 아래 `_grab_focus` 로
        # 확실히 가져오지만, 확인하지 못한 이상 길을 하나만 두지 않는다.
        #
        # 창에만 걸어도 캔버스에서 이벤트가 올라와 듣는 것은 확인했다.
        # 캔버스와 루트에 함께 거는 것은 그래도 모를 경우의 보험이다.
        # **오른쪽 버튼은 초점과 무관하게 듣는다** — 초점이 원인이라면
        # 이 길은 무슨 일이 있어도 열려 있다.
        for target in (self.window, self.canvas, root):
            target.bind("<Escape>", lambda _event: self._finish())
        self.canvas.bind("<Button-3>", lambda _event: self._finish())

        self.window.focus_force()
        self.canvas.focus_set()
        _grab_focus(self.window)

    def _down(self, event):
        # 그리는 자리는 tkinter 좌표, 찍을 자리는 윈도우 좌표. 둘을 따로
        # 둔다 — 화면 배율이 걸린 컴퓨터에서는 두 좌표계가 어긋나서, 섞어
        # 쓰면 끌어낸 데가 아니라 엉뚱한 곳이 찍힌다.
        self.start = (event.x, event.y)
        self.from_screen = screen_compare.cursor_at()
        self.canvas.delete("box")

    def _move(self, event):
        if not self.start:
            return
        self.canvas.delete("box")
        self.canvas.create_rectangle(*self.start, event.x, event.y,
                                     outline="white", width=2, tags="box")

    def _up(self, _event):
        if not self.start:
            return
        x0, y0 = self.from_screen
        x1, y1 = screen_compare.cursor_at()
        self.picked = (min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
        self._finish()

    def _finish(self):
        self.window.destroy()

    def run(self) -> screen_compare.Shot | None:
        """고르게 하고, 고른 자리만 찍어서 돌려준다."""
        self.window.wait_window()
        if not self.picked:
            return None

        # 막이 화면에서 실제로 걷힐 때까지 기다린다. `destroy()` 는 요청일
        # 뿐이라, 바로 찍으면 그 아래가 아니라 막이 덮인 화면이 찍힌다.
        # 윈도우가 가려졌던 자리를 다시 그릴 틈을 줘야 한다.
        self.root.update_idletasks()
        self.root.update()
        time.sleep(SETTLE)
        self.root.update()

        # 이미 윈도우 좌표다. 여기에 무엇을 더하면 안 된다.
        return screen_compare.capture(*self.picked)


def _as_png(shot: screen_compare.Shot) -> str:
    """tkinter 가 바로 읽는 그림 자료로. 회색 그대로 둬야 빨강이 눈에 띈다.

    PPM 은 안 된다 — Tk 는 base64 로 넘긴 PPM 을 못 알아본다(PNG 는
    읽는다). 회색 한 겹짜리로 만들면 자료도 3분의 1 로 준다. 만드는 데
    쓰는 zlib 은 표준 라이브러리다.
    """
    rows = bytearray()
    for y in range(shot.height):
        rows.append(0)               # 줄마다 '거르기 없음' 표시
        rows += shot.grey[y * shot.width:(y + 1) * shot.width]

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xffffffff))

    png = (bytes([137, 80, 78, 71, 13, 10, 26, 10])
           + chunk(b"IHDR", struct.pack(">IIBBBBB", shot.width, shot.height,
                                        8, 0, 0, 0, 0))      # 8비트 회색 한 겹
           + chunk(b"IDAT", zlib.compress(bytes(rows), 1))   # 한 번 보고 마니 빠르게
           + chunk(b"IEND", b""))
    return base64.b64encode(png).decode("ascii")


class _Result:
    """수정본 그림 위에 달라진 자리를 표시해 보여 준다."""

    def __init__(self, root: tk.Misc, shot: screen_compare.Shot, changes: list):
        marks = [c for c in changes if c.state != screen_compare.SAME]

        self.window = tk.Toplevel(root)
        self.window.title("결재 전후 비교")
        self.window.attributes("-topmost", True)

        tk.Label(self.window, anchor="w", font=("맑은 고딕", 11),
                 padx=12, pady=8,
                 text=self._headline(marks)).pack(fill="x")

        view = (min(shot.width, MAX_VIEW[0]), min(shot.height, MAX_VIEW[1]))
        holder = tk.Frame(self.window)
        holder.pack(fill="both", expand=True)
        canvas = tk.Canvas(holder, width=view[0], height=view[1],
                           highlightthickness=0, bg="white",
                           scrollregion=(0, 0, shot.width, shot.height))
        # 실제로 찍은 화면은 창보다 넓고 높다. 가로도 움직일 수 있어야 한다 —
        # 세로만 있으면 오른쪽에 있는 표시를 영영 못 본다.
        down = tk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        across = tk.Scrollbar(holder, orient="horizontal", command=canvas.xview)
        canvas.configure(yscrollcommand=down.set, xscrollcommand=across.set)
        down.grid(row=0, column=1, sticky="ns")
        across.grid(row=1, column=0, sticky="ew")
        canvas.grid(row=0, column=0, sticky="nsew")
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)

        # PhotoImage 는 참조가 끊기면 그림이 사라진다. 창에 붙들어 둔다.
        self.image = tk.PhotoImage(data=_as_png(shot))
        canvas.create_image(0, 0, image=self.image, anchor="nw")
        for change in marks:
            self._draw(canvas, change, shot.width)

        tk.Button(self.window, text="닫기",
                  command=self.window.destroy).pack(pady=8)
        self.window.bind("<Escape>", lambda _event: self.window.destroy())

    @staticmethod
    def _headline(marks: list) -> str:
        if not marks:
            return "달라진 곳을 찾지 못했습니다. 두 화면이 같습니다."
        added = sum(1 for c in marks if c.state == screen_compare.ADDED)
        removed = sum(1 for c in marks if c.state == screen_compare.REMOVED)
        edited = len(marks) - added - removed
        parts = []
        if edited:
            parts.append(f"고쳐진 곳 {edited}")
        if added:
            parts.append(f"새로 들어온 줄 {added}")
        if removed:
            parts.append(f"빠진 줄 {removed}")
        return "달라진 곳: " + ", ".join(parts) + "   (빨간 상자)"

    @staticmethod
    def _draw(canvas: tk.Canvas, change, width: int) -> None:
        top = max(0, change.top - MARGIN)
        bottom = change.bottom + MARGIN
        if change.state == screen_compare.REMOVED:
            # 빠진 줄은 수정본에 자리가 없다. 그 높이에 선만 그어 알린다.
            canvas.create_line(0, top, width, top, fill="#c81e1e",
                               width=2, dash=(6, 4))
            return
        for start, end in change.spans:
            canvas.create_rectangle(max(0, start - MARGIN), top,
                                    end + MARGIN, bottom,
                                    outline="#c81e1e", width=2)


def _pick(root: tk.Misc, step: str) -> screen_compare.Shot | None:
    """무엇을 고를지 알려 주고, 확인을 누르면 고르게 한다."""
    if not _Notice(root, step).run():
        return None
    return _Picker(root, step).run()


def run(root: tk.Misc, warn, hide=None, show=None) -> None:
    """원본 → 수정본 순서로 고르게 하고 결과를 띄운다.

    `warn(제목, 내용)` 은 알릴 때 부르는 함수. 창을 띄우는 방식을 위젯이
    정하도록 넘겨받는다.

    `hide` / `show` 는 고르는 동안 위젯을 감췄다 되돌리는 함수. 위젯은
    항상 위에 떠 있어서, 그대로 두면 화면을 찍을 때 **자기가 같이 찍힌다.**
    실사용에서 바로 그렇게 됐다. 감추는 방법은 위젯이 정하도록 넘겨받는다
    — 투명도·항상 위 설정을 되돌려 놓는 일은 위젯의 몫이다.
    """
    try:
        if hide:
            hide()
        try:
            before = _pick(root, "① 원본(기안한 것) 쪽을 끌어 주세요")
            if before is None:
                return
            after = _pick(root, "② 수정본(결재된 것) 쪽을 끌어 주세요")
            if after is None:
                return
        finally:
            if show:
                show()
        # 종이만 남기고 견준다. 창 부속(상태표시줄·스크롤바)이 빠지고,
        # 드래그 범위가 서로 달라도 같은 자리가 잘려 나온다.
        before, after = screen_compare.prepare(before, after)
        changes = screen_compare.compare(before, after)
    except screen_compare.ScreenError as exc:
        warn("결재 전후 비교", str(exc))
        return
    _Result(root, after, changes)
