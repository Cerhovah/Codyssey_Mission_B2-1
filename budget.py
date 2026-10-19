from __future__ import annotations

"""`python budget.py`로 간편 가계부를 시작하는 짧은 실행 파일.

명령 해석과 대화형 질문은 budget_app.easy에 맡기고, 여기서는 실행 환경만 확인한다.
"""

import sys


if __name__ == "__main__":
    # 지원하지 않는 버전에서는 다른 모듈을 읽기 전에 실행 방법부터 안내한다.
    if sys.version_info < (3, 10):
        print("[오류] Python 3.10 이상이 필요합니다.", file=sys.stderr)
        print("[힌트] python3.12 budget.py 또는 Python 3.10 이상의 실행 명령을 사용하세요.", file=sys.stderr)
        sys.exit(1)

    from budget_app.easy import main

    # 간편 모드가 반환한 처리 결과를 운영체제의 종료 코드로 전달한다.
    sys.exit(main())
