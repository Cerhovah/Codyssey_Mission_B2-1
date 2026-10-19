from __future__ import annotations

"""`python budget.py`로 간편 가계부를 실행한다."""

import sys


if __name__ == "__main__":
    if sys.version_info < (3, 10):
        print("[오류] Python 3.10 이상이 필요합니다.", file=sys.stderr)
        print("[힌트] python3.12 budget.py 또는 Python 3.10 이상의 실행 명령을 사용하세요.", file=sys.stderr)
        sys.exit(1)

    from budget_app.easy import main

    sys.exit(main())
