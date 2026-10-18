"""유스케이스 계층 (AGENT.md 5장). 검증 조합, id 발급, 집계, 재배정. 저장소만 호출한다.

P1에서는 시그니처와 데코레이터 적용만 두고, 본문은 "아직 구현되지 않은 명령입니다" 오류로 끝난다.
argparse·print·input 은 여기서 쓰지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .decorators import log_call, timed
from .errors import not_implemented
from .models import Budget, Transaction
from .repository import (
    BUDGETS_FILE,
    CATEGORIES_FILE,
    TRANSACTIONS_FILE,
    BudgetStore,
    CategoryStore,
    JsonlStore,
    TransactionRepository,
)


@dataclass(slots=True)
class ImportResult:
    """import 결과: 저장 건수와 (행번호, 사유) 목록 (D19)."""

    imported: int = 0
    skipped: list[tuple[int, str]] = field(default_factory=list)


@dataclass(slots=True)
class MonthlySummary:
    """summary 결과 (D16, D17)."""

    month: str
    income: int
    expense: int
    budget: Budget | None
    top_expenses: list[tuple[str, int]]
    count: int

    @property
    def balance(self) -> int:
        return self.income - self.expense


class CategoryService:
    def __init__(self, categories: CategoryStore, transactions: TransactionRepository) -> None:
        self.categories = categories
        self.transactions = transactions

    @log_call
    def list_names(self) -> list[str]:
        """이름 오름차순."""
        raise not_implemented(3)

    @log_call
    def add(self, name: str) -> str:
        raise not_implemented(3)

    @log_call
    def remove(self, name: str, replace: str | None = None) -> int:
        """삭제하고 재배정한 거래 건수를 돌려준다 (D18)."""
        raise not_implemented(5)


class TransactionService:
    def __init__(self, transactions: TransactionRepository, categories: CategoryStore) -> None:
        self.transactions = transactions
        self.categories = categories

    @log_call
    def add(
        self,
        *,
        date: str,
        type_: str,
        category: str,
        amount: str | int,
        memo: str = "",
        tags: str | list[str] | None = None,
    ) -> Transaction:
        raise not_implemented(3)

    @log_call
    @timed
    def list_recent(self, limit: int) -> list[Transaction]:
        """heapq.nlargest(limit, ...) 로 최신순 (D06, D07)."""
        raise not_implemented(3)

    @log_call
    @timed
    def search(
        self,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        category: str | None = None,
        type_: str | None = None,
        query: str | None = None,
        tag: str | None = None,
        limit: int | None = None,
    ) -> list[Transaction]:
        raise not_implemented(4)

    @log_call
    def update(
        self,
        tx_id: str,
        *,
        date: str | None = None,
        type_: str | None = None,
        category: str | None = None,
        amount: str | None = None,
        memo: str | None = None,
        tags: str | None = None,
    ) -> Transaction:
        raise not_implemented(5)

    @log_call
    def delete(self, tx_id: str) -> Transaction:
        raise not_implemented(5)

    @log_call
    @timed
    def import_csv(self, source: Path) -> ImportResult:
        raise not_implemented(6)

    @log_call
    @timed
    def export_csv(
        self,
        out: Path,
        *,
        month: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> int:
        """내보낸 건수를 돌려준다 (D20)."""
        raise not_implemented(6)


class BudgetService:
    def __init__(self, budgets: BudgetStore, transactions: TransactionRepository) -> None:
        self.budgets = budgets
        self.transactions = transactions

    @log_call
    def set_budget(self, month: str, amount: str | int) -> Budget:
        raise not_implemented(4)

    @log_call
    def list_all(self) -> list[Budget]:
        """월 오름차순 (D25)."""
        raise not_implemented(4)

    @log_call
    @timed
    def summary(self, month: str, top: int) -> MonthlySummary:
        raise not_implemented(4)


@dataclass(slots=True)
class Services:
    """cli 가 쓰는 서비스 묶음. 저장 폴더 1개에 대응한다."""

    data_dir: Path
    transactions: TransactionService
    categories: CategoryService
    budgets: BudgetService

    @log_call
    def backup(self) -> Path:
        """`data/backups/{YYYYMMDD-HHMMSS}/` 에 3개 파일을 복사하고 그 경로를 돌려준다 (B1)."""
        raise not_implemented(7)


def build_services(data_dir: Path) -> Services:
    """저장 폴더 경로로 저장소와 서비스를 조립한다. P2에서 ensure_initialized 를 연결한다."""
    tx_repo = TransactionRepository(JsonlStore(data_dir / TRANSACTIONS_FILE))
    category_store = CategoryStore(JsonlStore(data_dir / CATEGORIES_FILE))
    budget_store = BudgetStore(JsonlStore(data_dir / BUDGETS_FILE))
    return Services(
        data_dir=data_dir,
        transactions=TransactionService(tx_repo, category_store),
        categories=CategoryService(category_store, tx_repo),
        budgets=BudgetService(budget_store, tx_repo),
    )
