"""공통 관심사 데코레이터: handle_errors / log_call / timed (D22, C8).

- handle_errors: CLI 진입 함수에 적용. AppError → 두 줄 메시지 + 종료 코드,
  KeyboardInterrupt/EOFError → 130, 그 외 예외 → "예기치 않은 오류" + 1. 스택트레이스는 출력하지 않는다.
- log_call: 서비스 공개 메서드에 적용. 호출명과 인자 요약을 DEBUG 로그로 남긴다.
- timed: list/search/summary/import/export에 적용. 경과 ms를 DEBUG 로그로 남긴다.
"""
from __future__ import annotations

import functools
import logging
import sys
import time
from typing import Callable, ParamSpec, TypeVar

from .errors import EXIT_ERROR, EXIT_INTERRUPT, AppError

P = ParamSpec("P")
R = TypeVar("R")

logger = logging.getLogger("budget_app")

_ARG_REPR_LIMIT = 60


def _print_error_lines(lines: list[str]) -> None:
    """오류 줄을 stderr에 쓴다. stdout과 순서가 섞이지 않도록 먼저 flush 한다."""
    sys.stdout.flush()
    for line in lines:
        print(line, file=sys.stderr)
    sys.stderr.flush()


def handle_errors(func: Callable[P, int]) -> Callable[P, int]:
    """진입 함수의 예외를 사용자 메시지와 종료 코드로 바꾼다 (D15, D22). SystemExit는 그대로 통과한다."""

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> int:
        try:
            return func(*args, **kwargs)
        except AppError as err:
            _print_error_lines(err.format_lines())
            return err.exit_code
        except (KeyboardInterrupt, EOFError):
            _print_error_lines(["", "[안내] 중단했습니다"])
            return EXIT_INTERRUPT
        except Exception as exc:  # noqa: BLE001 - 마지막 방어선. 스택트레이스 대신 요약만 출력한다.
            logger.debug("예기치 않은 오류 상세", exc_info=True)
            _print_error_lines(
                [
                    f"[오류] 예기치 않은 오류: {type(exc).__name__}",
                    "[힌트] --verbose 로 다시 실행하면 상세 로그를 볼 수 있습니다",
                ]
            )
            return EXIT_ERROR

    return wrapper


def _short_repr(value: object) -> str:
    text = repr(value)
    if len(text) > _ARG_REPR_LIMIT:
        text = text[: _ARG_REPR_LIMIT - 3] + "..."
    return text


def _summarize_call(func: Callable[..., object], args: tuple[object, ...], kwargs: dict[str, object]) -> str:
    """메서드라면 self를 제외하고 인자를 짧게 요약한다."""
    positional = list(args)
    if "." in func.__qualname__ and positional:
        positional = positional[1:]
    parts = [_short_repr(a) for a in positional]
    parts.extend(f"{k}={_short_repr(v)}" for k, v in kwargs.items())
    return f"{func.__qualname__}({', '.join(parts)})"


def log_call(func: Callable[P, R]) -> Callable[P, R]:
    """호출명·인자 요약을 DEBUG 로그로 남긴다 (--verbose 에서만 보인다)."""

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        logger.debug("호출 %s", _summarize_call(func, args, kwargs))
        return func(*args, **kwargs)

    return wrapper


def timed(func: Callable[P, R]) -> Callable[P, R]:
    """경과 시간을 ms 단위 DEBUG 로그로 남긴다."""

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        started = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.debug("%s 완료 (%.1f ms)", func.__qualname__, elapsed_ms)

    return wrapper
