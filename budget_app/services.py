"""유스케이스 계층 (AGENT.md 5장). 검증 조합, id 발급, 집계, 재배정. 저장소만 호출한다.

P3: CategoryService.list_names/add/require, TransactionService.add/list_recent, build_services 의 초기화 연결(D36).
P4: TransactionService.search(D28, D38), BudgetService.set_budget/list_all/summary(D16, D17, D25, D39).
P5: TransactionService.update/delete, CategoryService.remove(D03, D18, D40). 재작성은 명령당 최대 1회.
P6 이후 메서드는 "아직 구현되지 않은 명령입니다" 오류로 끝난다. argparse·print·input 은 여기서 쓰지 않는다.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from dataclasses import replace as replace_fields
from pathlib import Path
from typing import Iterator

from .decorators import log_call, timed
from .errors import ConflictError, NotFoundError, ValidationError, not_implemented
from .models import (
    TYPE_EXPENSE,
    TYPE_INCOME,
    Budget,
    Transaction,
    parse_amount,
    parse_category_name,
    parse_date,
    parse_memo,
    parse_month,
    parse_tags,
    parse_type,
    transaction_number,
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


def _given(value: str | None) -> bool:
    """옵션이 주어졌고 strip 결과가 비어 있지 않으면 True. 빈 문자열은 "조건 없음" (D38)."""
    return value is not None and value.strip() != ""


def find_transaction(transactions: TransactionRepository, tx_id: str) -> Transaction:
    """id 형식을 검증하고 스트리밍으로 첫 일치를 찾는다. 없으면 NotFoundError (D40)."""
    clean = tx_id.strip()
    transaction_number(clean)
    for tx in transactions.iter_all():
        if tx.id == clean:
            return tx
    raise NotFoundError(f"거래를 찾을 수 없습니다: {clean}", hint="python -m budget_app list 로 id를 확인하세요.")


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
        """삭제하고 재배정한 거래 건수를 돌려준다 (D18, D40). 사용 중이면 --replace 없이는 차단한다."""
        clean = parse_category_name(name)
        if not self.categories.exists(clean):
            raise NotFoundError(
                f"카테고리를 찾을 수 없습니다: {clean}", hint="python -m budget_app category list 로 목록을 확인하세요"
            )
        target: str | None = None
        if replace is not None:
            target = require_category(self.categories, replace)
            if target == clean:
                raise ValidationError(
                    f"대체 카테고리가 삭제 대상과 같습니다: {clean}", hint="--replace 에는 다른 카테고리를 지정하세요"
                )
        in_use = sum(1 for tx in self.transactions.iter_all() if tx.category == clean)
        if in_use and target is None:
            raise ConflictError(
                f"'{clean}'를 사용하는 거래가 {in_use}건 있어 삭제할 수 없습니다.",
                hint="--replace <대체카테고리> 를 지정하면 해당 거래를 옮긴 뒤 삭제합니다.",
            )
        if in_use:
            self.transactions.rewrite(
                replace_fields(tx, category=target) if tx.category == clean else tx
                for tx in self.transactions.iter_all()
            )
        self.categories.remove(clean)
        return in_use


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
        """모든 조건 AND. 제너레이터로 걸러 통과분만 (date, id) 내림차순 정렬한다 (D07, D28, D38)."""
        start = parse_date(date_from) if _given(date_from) else None
        end = parse_date(date_to) if _given(date_to) else None
        if start is not None and end is not None and start > end:
            raise ValidationError(
                f"시작일이 종료일보다 늦습니다 (--from {start}, --to {end})", hint="--from 은 --to 보다 같거나 빨라야 합니다"
            )
        wanted_type = parse_type(type_) if _given(type_) else None
        wanted_category = category.strip() if _given(category) else None
        wanted_tag = tag.strip() if _given(tag) else None
        needle = query.strip().casefold() if _given(query) else None

        def matches(tx: Transaction) -> bool:
            if start is not None and tx.date < start:
                return False
            if end is not None and tx.date > end:
                return False
            if wanted_type is not None and tx.type != wanted_type:
                return False
            if wanted_category is not None and tx.category != wanted_category:
                return False
            if wanted_tag is not None and wanted_tag not in tx.tags:
                return False
            if needle is not None and needle not in tx.memo.casefold():
                return False
            return True

        passed: Iterator[Transaction] = (tx for tx in self.transactions.iter_all() if matches(tx))
        if limit is not None:
            return heapq.nlargest(limit, passed, key=Transaction.sort_key)
        return sorted(passed, key=Transaction.sort_key, reverse=True)

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
        """주어진 옵션만 바꾼다. 값 검증 → 대상 존재 확인 → 원자적 재작성 1회 (D03, D21, D40)."""
        changes: dict[str, object] = {}
        if date is not None:
            changes["date"] = parse_date(date)
        if type_ is not None:
            changes["type"] = parse_type(type_)
        if category is not None:
            changes["category"] = require_category(self.categories, category)
        if amount is not None:
            changes["amount"] = parse_amount(amount)
        if memo is not None:
            changes["memo"] = parse_memo(memo)
        if tags is not None:
            changes["tags"] = parse_tags(tags)
        if not changes:
            raise ValidationError("수정할 항목이 없습니다", hint="--date --type --category --amount --memo --tags 중 하나 이상")

        current = find_transaction(self.transactions, tx_id)
        updated = replace_fields(current, **changes)  # type: ignore[arg-type]
        self.transactions.rewrite(updated if tx.id == updated.id else tx for tx in self.transactions.iter_all())
        return updated

    @log_call
    def delete(self, tx_id: str) -> Transaction:
        """대상 존재 확인 → 그 거래만 빼고 원자적 재작성 1회 (D21, D40)."""
        target = find_transaction(self.transactions, tx_id)
        self.transactions.rewrite(tx for tx in self.transactions.iter_all() if tx.id != target.id)
        return target

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
        """월·금액을 검증하고 같은 달은 덮어쓴다 (D08, D25)."""
        budget = Budget(month=parse_month(month), amount=parse_amount(amount))
        self.budgets.set(budget)
        return budget

    @log_call
    def list_all(self) -> list[Budget]:
        """월 오름차순 (D25)."""
        return sorted(self.budgets.iter_all(), key=lambda budget: budget.month)

    @log_call
    @timed
    def summary(self, month: str, top: int) -> MonthlySummary:
        """한 번의 순회로 해당 월의 수입·지출·건수·카테고리별 지출을 집계한다 (D16, D17, D39)."""
        target = parse_month(month)
        income = expense = count = 0
        by_category: dict[str, int] = {}
        for tx in self.transactions.iter_all():
            if tx.date[:7] != target:
                continue
            count += 1
            if tx.type == TYPE_INCOME:
                income += tx.amount
            elif tx.type == TYPE_EXPENSE:
                expense += tx.amount
                by_category[tx.category] = by_category.get(tx.category, 0) + tx.amount
        ranked = sorted(by_category.items(), key=lambda item: (-item[1], item[0]))[:top]
        return MonthlySummary(
            month=target,
            income=income,
            expense=expense,
            budget=self.budgets.get(target),
            top_expenses=ranked,
            count=count,
        )


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
