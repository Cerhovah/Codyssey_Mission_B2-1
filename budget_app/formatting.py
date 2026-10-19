"""출력 포맷: 열 너비 정렬 테이블 (보너스 B3, D42). 외부 라이브러리 없이 문자열 정렬만 쓴다.

열 너비는 명령 결과 리스트(이미 limit·필터로 줄어든 소량)에서 계산한다. 한글 등 전각 문자는 2칸으로 센다.
"""
from __future__ import annotations

import unicodedata
from typing import Iterable

from .models import Budget, RecurringRule, Transaction

TYPE_COLUMN_WIDTH = 7
SEPARATOR = " | "


def display_width(text: str) -> int:
    """터미널 표시 폭. east_asian_width 가 W(Wide)/F(Fullwidth) 인 문자는 2칸 (D42)."""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def pad(text: str, width: int, align: str = "left") -> str:
    """표시 폭 기준으로 공백을 채운다. align 은 'left' 또는 'right'."""
    gap = max(width - display_width(text), 0)
    return (" " * gap + text) if align == "right" else (text + " " * gap)


def _render(rows: list[list[str]], aligns: tuple[str, ...], min_widths: tuple[int, ...]) -> list[str]:
    """마지막 열은 패딩하지 않고, 나머지 열은 데이터 최대 폭(최소 폭 이상)에 맞춘다."""
    if not rows:
        return []
    columns = len(aligns)
    # len()은 한글도 한 글자로 세므로 터미널에서 차지하는 칸 수를 따로 계산한다.
    widths = [
        max([min_widths[i], *(display_width(row[i]) for row in rows)]) for i in range(columns)
    ]
    lines: list[str] = []
    for row in rows:
        cells = [pad(row[i], widths[i], aligns[i]) for i in range(columns - 1)]
        # 마지막 열 뒤에는 공백을 붙이지 않아 줄 끝에 불필요한 여백을 남기지 않는다.
        cells.append(row[columns - 1])
        lines.append(SEPARATOR.join(cells))
    return lines


def format_amount(amount: int) -> str:
    """금액 문자열. 천 단위 구분 없이 숫자 그대로 (D42)."""
    return str(amount)


def format_won(amount: int) -> str:
    """숫자 표기에 원 단위를 덧붙인다."""
    return f"{format_amount(amount)}원"


def _transaction_cells(tx: Transaction) -> list[str]:
    """거래 모델을 화면의 열 순서에 맞는 문자열 목록으로 바꾼다."""
    return [tx.id, tx.date, tx.type, tx.category, format_amount(tx.amount), tx.memo]


def format_transaction_row(tx: Transaction) -> str:
    """단일 행 `id | date | type(7자리 좌정렬) | category | amount | memo` (호환용, 다른 행과 정렬하지 않음)."""
    cells = _transaction_cells(tx)
    cells[2] = pad(cells[2], TYPE_COLUMN_WIDTH)
    return SEPARATOR.join(cells)


def format_transaction_table(transactions: Iterable[Transaction]) -> list[str]:
    """list/search 출력. id·date·type·category 좌정렬, amount 우정렬, memo 는 패딩 없음 (D42)."""
    rows = [_transaction_cells(tx) for tx in transactions]
    return _render(rows, ("left", "left", "left", "left", "right", "left"), (0, 0, TYPE_COLUMN_WIDTH, 0, 0, 0))


def format_budget_row(budget: Budget) -> str:
    """월과 예산 금액을 한 줄로 표시한다. 여러 행 사이의 너비는 맞추지 않는다."""
    return f"{budget.month}{SEPARATOR}{format_won(budget.amount)}"


def format_budget_table(budgets: Iterable[Budget]) -> list[str]:
    """budget list 출력 `2024-01 | 500000원`. 금액 열은 우정렬 (D42)."""
    rows = [[budget.month, format_won(budget.amount)] for budget in budgets]
    if not rows:
        return []
    # 각 행의 금액을 가장 긴 금액에 맞춰 오른쪽 정렬한다.
    width = max(display_width(row[1]) for row in rows)
    return [f"{row[0]}{SEPARATOR}{pad(row[1], width, 'right')}" for row in rows]


def format_category_row(name: str) -> str:
    """카테고리 이름 앞에 목록 표시를 붙인다."""
    return f"- {name}"


def format_recurring_table(rules: Iterable[RecurringRule]) -> list[str]:
    """recurring list 출력 `id | 매월 N일 | type | category | amount | memo` (D44). 정렬 규칙은 거래 테이블과 같다."""
    rows = [[rule.id, f"매월 {rule.day}일", rule.type, rule.category, format_amount(rule.amount), rule.memo] for rule in rules]
    return _render(rows, ("left", "left", "left", "left", "right", "left"), (0, 0, TYPE_COLUMN_WIDTH, 0, 0, 0))
