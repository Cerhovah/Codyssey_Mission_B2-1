"""저장 계층: JSONL 스트리밍 읽기, append, 원자적 재작성 (AGENT.md 5장, C5, C6, D21).

P1에서는 시그니처만 둔다. 모든 메서드는 P2 전까지 "아직 구현되지 않은 명령입니다" 오류로 끝난다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Iterator

from .errors import not_implemented
from .models import Budget, Transaction

TRANSACTIONS_FILE = "transactions.jsonl"
CATEGORIES_FILE = "categories.jsonl"
BUDGETS_FILE = "budgets.jsonl"
DEFAULT_CATEGORIES: tuple[str, ...] = ("food", "transport", "rent", "salary", "etc")  # D04


class JsonlStore:
    """JSONL 파일 1개를 다룬다. 읽기는 제너레이터, 재작성은 임시 파일 + os.replace."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def iter_records(self) -> Iterator[dict[str, Any]]:
        """한 줄씩 JSON 객체를 yield 한다. 빈 줄은 건너뛰고 손상된 줄은 StorageError."""
        raise not_implemented(2)

    def append(self, record: dict[str, Any]) -> None:
        raise not_implemented(2)

    def rewrite(self, records: Iterable[dict[str, Any]]) -> None:
        """임시 파일에 전부 쓴 뒤 os.replace 로 교체한다 (D21)."""
        raise not_implemented(2)


class TransactionRepository:
    def __init__(self, store: JsonlStore) -> None:
        self.store = store

    def iter_all(self) -> Iterator[Transaction]:
        raise not_implemented(2)

    def next_id(self) -> str:
        """스트리밍으로 구한 최대 번호 + 1 (D05)."""
        raise not_implemented(2)

    def append(self, tx: Transaction) -> None:
        raise not_implemented(2)

    def rewrite(self, transactions: Iterable[Transaction]) -> None:
        raise not_implemented(2)


class CategoryStore:
    def __init__(self, store: JsonlStore) -> None:
        self.store = store

    def names(self) -> list[str]:
        raise not_implemented(2)

    def exists(self, name: str) -> bool:
        raise not_implemented(2)

    def add(self, name: str) -> None:
        raise not_implemented(2)

    def remove(self, name: str) -> None:
        raise not_implemented(2)


class BudgetStore:
    def __init__(self, store: JsonlStore) -> None:
        self.store = store

    def get(self, month: str) -> Budget | None:
        raise not_implemented(2)

    def set(self, budget: Budget) -> None:
        """같은 달이 있으면 덮어쓴다 (D25)."""
        raise not_implemented(2)

    def iter_all(self) -> Iterator[Budget]:
        raise not_implemented(2)


def ensure_initialized(data_dir: Path) -> bool:
    """폴더와 파일 3개를 만들고 기본 카테고리를 채운다. 새로 만들었으면 True (D04, D23)."""
    raise not_implemented(2)
