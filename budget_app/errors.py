"""오류 계약: AppError 계층과 종료 코드 상수 (AGENT.md 8장, D14, D15).

서비스·모델은 AppError 하위 예외만 던지고, 출력은 decorators.handle_errors 한 곳에서만 한다.
"""
from __future__ import annotations

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_INTERRUPT = 130


class AppError(Exception):
    """사용자에게 보여 줄 오류. 원인(message)과 해결 힌트(hint), 종료 코드를 가진다."""

    def __init__(self, message: str, hint: str = "", exit_code: int = EXIT_ERROR) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.exit_code = exit_code

    def format_lines(self) -> list[str]:
        """`[오류] 원인` / `[힌트] 해결` 두 줄. 힌트가 없으면 한 줄 (D15)."""
        lines = [f"[오류] {self.message}"]
        if self.hint:
            lines.append(f"[힌트] {self.hint}")
        return lines

    def __str__(self) -> str:
        return self.message


class ValidationError(AppError):
    """날짜·금액·타입·태그 등 단일 값의 형식 검증 실패."""


class NotFoundError(AppError):
    """없는 거래 id, 없는 카테고리."""


class ConflictError(AppError):
    """중복 카테고리, 사용 중인 카테고리 삭제 시도."""


class StorageError(AppError):
    """손상된 저장 줄, 파일 권한, 재작성 실패."""


def not_implemented(phase: int) -> AppError:
    """아직 구현되지 않은 명령이 호출되었을 때 던질 오류를 만든다 (P1 스텁용)."""
    return AppError("아직 구현되지 않은 명령입니다", hint=f"Phase {phase}")
