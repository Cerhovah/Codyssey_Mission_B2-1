"""진입점: `python -m budget_app <command> [options]`.

handle_errors 가 모든 오류를 `[오류]`/`[힌트]` 두 줄과 종료 코드(0/1/2/130)로 바꾼다 (D14, D15, D22).
"""
from __future__ import annotations

import sys

from .cli import main
from .decorators import handle_errors


@handle_errors
def entry(argv: list[str] | None = None) -> int:
    """CLI 진입 함수. 반환값이 곧 종료 코드다."""
    return main(argv)


if __name__ == "__main__":
    sys.exit(entry())
