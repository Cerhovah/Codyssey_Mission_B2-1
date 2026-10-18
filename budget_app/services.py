"""유스케이스 계층 (AGENT.md 5장). 검증 조합, id 발급, 집계, 재배정. 저장소만 호출한다.

P3: CategoryService.list_names/add/require, TransactionService.add/list_recent, build_services 의 초기화 연결(D36).
P4 이후 메서드는 "아직 구현되지 않은 명령입니다" 오류로 끝난다. argparse·print·input 은 여기서 쓰지 않는다.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from pathlib import Path

from .decorators import log_call, timed
from .errors import NotFoundError, not_implemented
from .models import (
    Budget,
    Transaction,
    parse_amount,
    parse_category_name,
    parse_date,
    parse_memo,
    parse_tags,
    parse_type,
)
from .repository import (
    BUDGETS_FILE,
    CATEGORIES_FILE,
    TRANSACTIONS_FILE,
    BudgetStore,
    CategoryStore,
    JsonlStore,
    TransactionRepository,
    ensure_initialized,
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


def require_category(categories: CategoryStore, name: str) -> str:
    """이름을 정규화하고 등록 여부를 확인한다. 없으면 등록 목록을 힌트로 담은 NotFoundError (D37)."""
    clean = parse_category_name(name)
    if not categories.exists(clean):
        registered = ", ".join(sorted(categories.names())) or "(없음)"
        raise NotFoundError(
            f"등록되지 않은 카테고리입니다: {clean}",
            hint=f"등록된 카테고리: {registered} (추가: python -m budget_app category add <이름>)",
        )
    return clean


class CategoryService:
    def __init__(self, categories: CategoryStore, transactions: TransactionRepository) -> None:
        self.categories = categories
        self.transactions = transactions

    @log_call
    def list_names(self) -> list[str]:
        """이름 오름차순."""
        return sorted(self.categories.names())

    @log_call
    def add(self, name: str) -> str:
        """정규화한 이름을 등록하고 돌려준다. 빈 이름은 ValidationError, 중복은 ConflictError (D12, D35)."""
        clean = parse_category_name(name)
        self.categories.add(clean)
        return clean

    @log_call
    def require(self, name: str) -> str:
        """대화형 프롬프트용 존재 검사 (D37)."""
        return require_category(self.categories, name)

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
        """모든 필드를 검증한 뒤 다음 id 를 발급해 1줄 추가한다 (D05, D08~D11)."""
        tx = Transaction(
            id=self.transactions.next_id(),
            type=parse_type(type_),
            date=parse_date(date),
            amount=parse_amount(amount),
            category=require_category(self.categories, category),
            memo=parse_memo(memo),
            tags=parse_tags(tags),
        )
        self.transactions.append(tx)
        return tx

    @log_call
    @timed
    def list_recent(self, limit: int) -> list[Transaction]:
        """heapq.nlargest(limit, ...) 로 최신순. 메모리는 limit 건만 유지한다 (D06, D07)."""
        return heapq.nlargest(limit, self.transactions.iter_all(), key=Transaction.sort_key)

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
    initialized: bool = False  # 이번 실행에서 저장 폴더·파일을 새로 만들었는지 (D36)

    @log_call
    def backup(self) -> Path:
        """`data/backups/{YYYYMMDD-HHMMSS}/` 에 3개 파일을 복사하고 그 경로를 돌려준다 (B1)."""
        raise not_implemented(7)


def build_services(data_dir: Path) -> Services:
    """저장 폴더를 초기화(D04, D23, D36)하고 저장소와 서비스를 조립한다. 안내 출력은 cli 가 맡는다."""
    initialized = ensure_initialized(data_dir)
    tx_repo = TransactionRepository(JsonlStore(data_dir / TRANSACTIONS_FILE))
    category_store = CategoryStore(JsonlStore(data_dir / CATEGORIES_FILE))
    budget_store = BudgetStore(JsonlStore(data_dir / BUDGETS_FILE))
    return Services(
        data_dir=data_dir,
        transactions=TransactionService(tx_repo, category_store),
        categories=CategoryService(category_store, tx_repo),
        budgets=BudgetService(budget_store, tx_repo),
        initialized=initialized,
    )
