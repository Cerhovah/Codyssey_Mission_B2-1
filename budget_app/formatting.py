"""출력 포맷 (P1: 단순 ' | ' join. P7에서 열 너비 정렬·천 단위 구분 추가, 보너스 B3)."""
from __future__ import annotations

from .models import Budget, Transaction

TYPE_COLUMN_WIDTH = 7


def format_amount(amount: int) -> str:
    """금액 문자열. P7 전에는 숫자 그대로."""
    return str(amount)


def format_won(amount: int) -> str:
    return f"{format_amount(amount)}원"


def format_transaction_row(tx: Transaction) -> str:
    """`id | date | type(7자리 좌정렬) | category | amount | memo` (AGENT.md 7장)."""
    return " | ".join(
        [
            tx.id,
            tx.date,
            f"{tx.type:<{TYPE_COLUMN_WIDTH}}",
            tx.category,
            format_amount(tx.amount),
            tx.memo,
        ]
    )


def format_budget_row(budget: Budget) -> str:
    return f"{budget.month} | {format_won(budget.amount)}"


def format_category_row(name: str) -> str:
    return f"- {name}"
