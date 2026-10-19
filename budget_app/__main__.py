"""진입점: `python -m budget_app <command> [options]`.

handle_errors 가 모든 오류를 `[오류]`/`[힌트]` 두 줄과 종료 코드(0/1/2/130)로 바꾼다 (D14, D15, D22).
"""
from __future__ import annotations

import sys

from .cli import main
from .decorators import handle_errors


@handle_errors
def entry(argv: list[str] | None = None) -> int:
    """CLI에 인자를 전달하고 처리 결과를 돌려준다. None이면 터미널 인자를 사용한다."""
    return main(argv)


if __name__ == "__main__":
    # import할 때는 실행하지 않고, -m으로 시작했을 때만 종료 코드를 전달한다.
    sys.exit(entry())
