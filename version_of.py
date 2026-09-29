"""app.py 에 적힌 VERSION 값을 한 줄로 출력한다.

빌드할 때 GitHub이 이 값을 읽어 릴리스 태그로 쓴다.

명령창에 정규식을 직접 적으면 PowerShell이 따옴표를 먼저 해석해 버려서
파이썬에 닿기도 전에 문자열이 깨진다. 그래서 파일로 빼 두었다.
"""

import pathlib
import re
import sys

source = pathlib.Path("app.py").read_text(encoding="utf-8")
found = re.search(r'^VERSION\s*=\s*"([^"]+)"', source, re.MULTILINE)
if not found:
    sys.exit("app.py 에서 VERSION 을 찾지 못했습니다")
print(found.group(1))
