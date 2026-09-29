# PyInstaller 설정 — 파이썬이 없는 컴퓨터에서도 도는 실행 파일 하나를 만든다.
#   pyinstaller build.spec
# 결과: dist/gongmun-submisson.exe
#
# exe 이름은 반드시 영문이어야 한다. GitHub 릴리스는 한글이 든 첨부
# 파일명을 제멋대로 바꿔 버려서(공문정리함.exe → default.exe), 자동
# 업데이트가 그 파일을 찾지 못하고 "내려받다가 끊겼습니다" 로 실패한다.
# 사용자에게 보이는 이름은 설치 후 바로가기(installer.iss의 AppName,
# "공문정리함제출")가 담당하므로 exe 파일명이 영문이어도 상관없다.

a = Analysis(
    ["widget.py"],
    pathex=["."],
    binaries=[],
    # 변경내역.md 는 갱신 뒤 "이렇게 바뀌었습니다" 창이 읽는다. 빠뜨리면
    # 창이 그냥 뜨지 않는다(오류는 안 난다) — 그래서 빠진 걸 알아채기 어렵다.
    datas=[("ui.html", "."), ("변경내역.md", "."), ("icon.ico", "."),
           # 글꼴은 함께 넣어 배포한다. 외부 CDN 을 쓰면 실행할 때마다
           # 이용자 IP 가 제3자에게 나가고, 학교망이 막으면 글꼴이 바뀐다.
           # OFL 1.1 은 함께 배포할 때 라이선스 전문을 같이 두도록 요구한다.
           ("assets/PretendardVariable.woff2", "assets"),
           ("assets/Pretendard-OFL.txt", "assets"),
           ("LICENSE", "."), ("THIRD-PARTY-NOTICES.txt", "."),
           # MIT·BSD 는 배포물에 라이선스 전문을 함께 두라고 요구한다
           ("licenses", "licenses")],
    hiddenimports=["olefile", "pypdf", "openpyxl", "xlrd", "app", "store",
                   "classify", "extract", "hwpx_view", "updater", "organize",
                   "changelog", "compare", "screen_compare",
                   "compare_window"],
    hookspath=[],
    runtime_hooks=[],
    # 쓰지 않는 큰 덩어리를 빼서 파일 크기를 줄인다
    # fontTools 는 pypdf 가 글꼴을 "써 넣을" 때만 쓰는 선택 꾸러미다. 우리는
    # 읽기만 하므로 필요 없는데, 빌드하는 PC 에 깔려 있으면 딸려 들어가
    # 고지 목록에 없는 저작물이 exe 에 섞인다.
    excludes=["numpy", "pandas", "matplotlib", "scipy", "PIL", "pytest", "playwright",
              "fontTools"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="gongmun-submisson",
    icon="icon.ico",
    console=False,          # 검은 명령 창을 띄우지 않는다
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
