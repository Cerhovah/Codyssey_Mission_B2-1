"""유스케이스 계층 (AGENT.md 5장). 검증 조합, id 발급, 집계, 재배정. 저장소만 호출한다.

P3: CategoryService.list_names/add/require, TransactionService.add/list_recent, build_services 의 초기화 연결(D36).
P4: TransactionService.search(D28, D38), BudgetService.set_budget/list_all/summary(D16, D17, D25, D39).
P5: TransactionService.update/delete, CategoryService.remove(D03, D18, D40). 재작성은 명령당 최대 1회.
P6: TransactionService.import_csv/export_csv(D19, D20, D41). CSV 는 교환 포맷이며 저장 포맷은 JSONL 그대로다.
P7: Services.backup(D43). P9(예비): RecurringService(D44). argparse·print·input 은 여기서 쓰지 않는다.
D47: 삭제 전에 원본을 보관하고 restore로 원래 번호와 필드를 복구한다.
"""
from __future__ import annotations

import calendar
import csv
import heapq
from dataclasses import dataclass, field
from dataclasses import replace as replace_fields
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .decorators import log_call, timed
from .errors import AppError, ConflictError, NotFoundError, StorageError, ValidationError
from .models import (
    TYPE_EXPENSE,
    TYPE_INCOME,
    Budget,
    RecurringRule,
    Transaction,
    format_transaction_id,
    parse_amount,
    parse_category_name,
    parse_date,
    parse_day,
    parse_memo,
    parse_month,
    parse_tags,
    parse_type,
    recurring_number,
    transaction_number,
)
from .repository import (
    BUDGETS_FILE,
    CATEGORIES_FILE,
    DATA_FILES,
    RECURRING_FILE,
    TRANSACTIONS_FILE,
    BudgetStore,
    CategoryStore,
    JsonlStore,
    RecurringStore,
    TransactionRepository,
    backup_files,
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
        """별도 저장값 없이 집계된 수입과 지출에서 해당 월의 잔액을 계산한다."""
        return self.income - self.expense


BACKUP_DIR_NAME = "backups"  # D43
DATA_FILE_COUNT = len(DATA_FILES)  # backup 출력 `(N files)` 용. cli 는 repository 를 import 하지 않는다 (C10)


def _backup_stamp() -> str:
    """백업 폴더 이름 `YYYYMMDD-HHMMSS` (로컬 시간)."""
    return datetime.now().strftime("%Y%m%d-%H%M%S")


CSV_COLUMNS: tuple[str, ...] = ("date", "type", "category", "amount", "memo", "tags")  # README 6장, D20
CSV_HEADER_HINT = "필수 헤더: " + ",".join(CSV_COLUMNS) + " (UTF-8, 첫 줄 헤더)"


def _date_range(date_from: str | None, date_to: str | None) -> tuple[str | None, str | None]:
    """--from/--to 를 검증한다. 시작일이 종료일보다 늦으면 ValidationError (D38, D41)."""
    start = parse_date(date_from) if _given(date_from) else None
    end = parse_date(date_to) if _given(date_to) else None
    if start is not None and end is not None and start > end:
        raise ValidationError(
            f"시작일이 종료일보다 늦습니다 (--from {start}, --to {end})", hint="--from 은 --to 보다 같거나 빨라야 합니다"
        )
    return start, end


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
    """분류를 관리하고 사용 중인 분류를 없앨 때 거래의 참조를 보호한다."""

    def __init__(self, categories: CategoryStore, transactions: TransactionRepository) -> None:
        """분류 저장소와 사용 여부를 확인할 거래 저장소를 함께 연결한다."""
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
            # 거래의 분류 이동이 성공한 뒤에만 기존 분류를 제거한다.
            self.transactions.rewrite(
                replace_fields(tx, category=target) if tx.category == clean else tx
                for tx in self.transactions.iter_all()
            )
        self.categories.remove(clean)
        return in_use


class TransactionService:
    """거래의 검증·추가·조회·변경과 CSV 교환을 조합하는 업무 계층이다."""

    def __init__(self, transactions: TransactionRepository, categories: CategoryStore) -> None:
        """거래 저장소와 등록된 분류의 존재를 검사할 저장소를 연결한다."""
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
        start, end = _date_range(date_from, date_to)
        wanted_type = parse_type(type_) if _given(type_) else None
        wanted_category = category.strip() if _given(category) else None
        wanted_tag = tag.strip() if _given(tag) else None
        needle = query.strip().casefold() if _given(query) else None

        def matches(tx: Transaction) -> bool:
            """하나라도 어긋나면 제외해 지정된 검색 조건을 모두 만족하게 한다."""
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
            # 제한이 있으면 출력 후보만 유지하고, 없으면 일치한 결과만 정렬한다.
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

        # 입력값과 대상 존재를 먼저 확인한 뒤 파일을 한 번만 교체한다.
        current = find_transaction(self.transactions, tx_id)
        updated = replace_fields(current, **changes)  # type: ignore[arg-type]
        self.transactions.rewrite(updated if tx.id == updated.id else tx for tx in self.transactions.iter_all())
        return updated

    @log_call
    def delete(self, tx_id: str) -> Transaction:
        """대상 확인 → 원본 보관 → 그 거래만 빼고 원자적 재작성한다 (D21, D40, D47)."""
        target = find_transaction(self.transactions, tx_id)
        # 보관 완료 후 삭제해야 복구할 원본을 잃지 않는다. 재작성 실패 시 활성 원본도 남는다.
        self.transactions.archive(target)
        self.transactions.rewrite(tx for tx in self.transactions.iter_all() if tx.id != target.id)
        return target

    @log_call
    def restore(self, tx_id: str | None = None) -> Transaction:
        """마지막 삭제 기록 또는 지정한 번호의 마지막 원본을 그대로 복구한다 (D47)."""
        clean = tx_id.strip() if tx_id is not None else None
        if clean is not None:
            transaction_number(clean)

        target: Transaction | None = None
        # 뒤에서 다시 삭제된 같은 번호가 있으면 가장 나중의 원본을 사용한다.
        # 전체 이력을 리스트로 모으지 않고 후보 한 건만 갱신한다.
        for deleted in self.transactions.iter_deleted():
            if clean is None or deleted.id == clean:
                target = deleted
        if target is None:
            detail = f": {clean}" if clean is not None else ""
            raise NotFoundError(
                f"복구할 삭제 기록이 없습니다{detail}",
                hint="삭제 복구 기능을 추가한 뒤 삭제한 거래만 restore로 복구할 수 있습니다.",
            )

        if any(tx.id == target.id for tx in self.transactions.iter_all()):
            # 삭제 뒤 번호가 재사용되었어도 기존 거래를 덮어쓰거나 다른 번호로 추측하지 않는다.
            raise ConflictError(
                f"이미 사용 중인 거래 번호라 복구할 수 없습니다: {target.id}",
                hint="list로 현재 거래를 확인하세요. 이미 복구했거나 새 거래에 같은 번호가 발급되었습니다.",
            )
        require_category(self.categories, target.category)

        def restored() -> Iterator[Transaction]:
            """활성 거래를 모두 유지한 뒤 원래 번호와 필드를 가진 복구 원본을 더한다."""
            yield from self.transactions.iter_all()
            yield target

        # 저장 도중 실패해도 기존 활성 파일이 손상되지 않도록 임시 파일 교체를 재사용한다.
        self.transactions.rewrite(restored())
        # 삭제 이력을 지우지 않아 보관본을 유지한다. 중복 복구는 위의 번호 검사로 막는다.
        return target

    @log_call
    @timed
    def import_csv(self, source: Path) -> ImportResult:
        """CSV 를 행 단위로 검증해 유효 행만 새 id 로 저장한다. 실패 행은 (행번호, 사유) 로 보고 (D19, D41)."""
        if not source.is_file():
            raise StorageError(f"가져올 파일을 찾을 수 없습니다: {source}", hint="--from 경로를 확인하세요")
        result = ImportResult()
        try:
            with open(source, "r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                header = reader.fieldnames or []
                missing = [column for column in CSV_COLUMNS if column not in header]
                if missing:
                    # 헤더 오류는 어느 행도 저장하기 전에 끝내 부분 가져오기를 피한다.
                    raise ValidationError(
                        f"CSV 헤더가 올바르지 않습니다 (누락: {', '.join(missing)})", hint=CSV_HEADER_HINT
                    )
                number = transaction_number(self.transactions.next_id())  # 시작 번호 1회 (D41)
                for row in reader:
                    line_no = reader.line_num
                    try:
                        tx = self._from_csv_row(row, format_transaction_id(number))
                    except AppError as err:
                        # 행의 입력 오류만 건너뛴다. 실제 파일 저장 실패는 호출자에게 전파한다.
                        result.skipped.append((line_no, err.message))
                        continue
                    self.transactions.append(tx)
                    number += 1
                    result.imported += 1
        except UnicodeDecodeError:
            raise StorageError(f"CSV 파일을 UTF-8 로 읽을 수 없습니다: {source}", hint=CSV_HEADER_HINT) from None
        except csv.Error as exc:
            raise ValidationError(f"CSV 형식 오류: {exc}", hint=CSV_HEADER_HINT) from None
        except OSError as exc:
            raise StorageError(
                f"CSV 파일을 읽을 수 없습니다: {source} ({exc.strerror or type(exc).__name__})", hint="파일 권한을 확인하세요"
            ) from None
        return result

    def _from_csv_row(self, row: dict[str, str | None], tx_id: str) -> Transaction:
        """CSV 한 행 → Transaction. 비어 있거나 모자란 열은 빈 문자열로 본다 (D41)."""

        def cell(column: str) -> str:
            """누락되거나 비문자열인 셀을 빈 값으로 통일해 기존 필드 검증에 맡긴다."""
            value = row.get(column)
            return value if isinstance(value, str) else ""

        return Transaction(
            id=tx_id,
            type=parse_type(cell("type")),
            date=parse_date(cell("date")),
            amount=parse_amount(cell("amount")),
            category=require_category(self.categories, cell("category")),
            memo=parse_memo(cell("memo")),
            tags=parse_tags(cell("tags")),
        )

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
        """조건(AND)에 맞는 거래를 (date, id) 내림차순 CSV 로 쓰고 건수를 돌려준다. 0건도 헤더는 쓴다 (D20, D41)."""
        target_month = parse_month(month) if _given(month) else None
        start, end = _date_range(date_from, date_to)
        if target_month is None and start is None and end is None:
            raise ValidationError("기간 조건이 필요합니다", hint="--month YYYY-MM 또는 --from/--to YYYY-MM-DD")

        def matches(tx: Transaction) -> bool:
            """월과 날짜 범위가 함께 있으면 교집합에 속한 거래만 내보낸다."""
            if target_month is not None and tx.date[:7] != target_month:
                return False
            if start is not None and tx.date < start:
                return False
            if end is not None and tx.date > end:
                return False
            return True

        rows = sorted((tx for tx in self.transactions.iter_all() if matches(tx)), key=Transaction.sort_key, reverse=True)
        try:
            with open(out, "w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, lineterminator="\n")  # 기본값 CRLF 대신 LF (C11, D41)
                writer.writerow(CSV_COLUMNS)
                for tx in rows:
                    writer.writerow([tx.date, tx.type, tx.category, tx.amount, tx.memo, ",".join(tx.tags)])
        except OSError as exc:
            raise StorageError(
                f"CSV 파일을 쓸 수 없습니다: {out} ({exc.strerror or type(exc).__name__})",
                hint="--out 의 폴더가 있는지, 쓰기 권한이 있는지 확인하세요",
            ) from None
        return len(rows)


class BudgetService:
    """월 예산의 저장과 거래를 읽어 만드는 월별 요약을 담당한다."""

    def __init__(self, budgets: BudgetStore, transactions: TransactionRepository) -> None:
        """예산 비교 기준과 집계 대상 거래를 각각의 저장소에서 읽도록 연결한다."""
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
        # 지출이 같으면 이름순으로 정렬해 매번 같은 순위가 나오도록 한다.
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
class ApplyResult:
    """recurring apply 결과: 규칙 수, 생성 건수, (규칙 id, 사유) skip 목록 (D44)."""

    month: str
    rule_count: int
    created: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)


RECURRING_TAG_PREFIX = "rc:"  # 생성 거래에 붙여 중복 적용을 막는 태그 (D44)


class RecurringService:
    """반복 내역 규칙 등록·조회·삭제와 월별 적용 (보너스 B2, D44)."""

    def __init__(self, recurring: RecurringStore, transactions: TransactionRepository, categories: CategoryStore) -> None:
        """규칙 저장소와 실제 거래 저장소, 카테고리 검증 저장소를 연결한다."""
        self.recurring = recurring
        self.transactions = transactions
        self.categories = categories

    @log_call
    def add(
        self,
        *,
        day: str | int,
        type_: str,
        category: str,
        amount: str | int,
        memo: str = "",
        tags: str | list[str] | None = None,
    ) -> RecurringRule:
        """add 와 같은 검증을 거쳐 규칙을 1줄 추가한다."""
        rule = RecurringRule(
            id=self.recurring.next_id(),
            day=parse_day(day),
            type=parse_type(type_),
            amount=parse_amount(amount),
            category=require_category(self.categories, category),
            memo=parse_memo(memo),
            tags=parse_tags(tags),
        )
        self.recurring.append(rule)
        return rule

    @log_call
    def list_all(self) -> list[RecurringRule]:
        """파일 순서 = id 순서."""
        return list(self.recurring.iter_all())

    @log_call
    def remove(self, rule_id: str) -> RecurringRule:
        """규칙 번호의 형식을 확인한 뒤 등록 규칙을 지운다. 생성 거래는 보존한다."""
        clean = rule_id.strip()
        recurring_number(clean)
        return self.recurring.remove(clean)

    @log_call
    @timed
    def apply(self, month: str) -> ApplyResult:
        """규칙마다 해당 월의 거래를 1건 만든다. 이미 적용(rc: 태그)되었거나 카테고리가 없으면 건너뛴다 (D44)."""
        target = parse_month(month)
        rules = self.list_all()
        result = ApplyResult(month=target, rule_count=len(rules))
        if not rules:
            return result

        applied: dict[str, str] = {}  # 규칙 id → 이미 만들어진 거래 id (거래 파일 1회 스트리밍)
        for tx in self.transactions.iter_all():
            if tx.date[:7] != target:
                continue
            for tag in tx.tags:
                if tag.startswith(RECURRING_TAG_PREFIX):
                    applied.setdefault(tag[len(RECURRING_TAG_PREFIX):], tx.id)

        last_day = calendar.monthrange(int(target[:4]), int(target[5:7]))[1]
        number = transaction_number(self.transactions.next_id())  # 시작 번호 1회 (D41 과 같은 방식)
        for rule in rules:
            if rule.id in applied:
                result.skipped.append((rule.id, f"{target} 에 이미 적용됨 ({applied[rule.id]})"))
                continue
            try:
                category = require_category(self.categories, rule.category)
            except AppError as err:
                # 분류가 사라진 규칙도 보고에 남기고 나머지 유효 규칙을 계속 처리한다.
                result.skipped.append((rule.id, err.message))
                continue
            # 31일 규칙도 짧은 달에 적용할 수 있도록 그달의 마지막 날까지만 사용한다.
            tx = Transaction(
                id=format_transaction_id(number),
                type=rule.type,
                date=f"{target}-{min(rule.day, last_day):02d}",
                amount=rule.amount,
                category=category,
                memo=rule.memo,
                tags=parse_tags([*rule.tags, f"{RECURRING_TAG_PREFIX}{rule.id}"]),
            )
            self.transactions.append(tx)
            number += 1
            result.created += 1
        return result


@dataclass(slots=True)
class Services:
    """cli 가 쓰는 서비스 묶음. 저장 폴더 1개에 대응한다."""

    data_dir: Path
    transactions: TransactionService
    categories: CategoryService
    budgets: BudgetService
    recurring: RecurringService
    initialized: bool = False  # 이번 실행에서 저장 폴더·파일을 새로 만들었는지 (D36)

    @log_call
    def backup(self) -> Path:
        """`{data_dir}/backups/{YYYYMMDD-HHMMSS}/` 에 네 파일을 복사하고 그 경로를 돌려준다 (B1, D43).

        같은 초에 다시 실행해 폴더가 이미 있으면 `-1`, `-2`, … 를 붙여 덮어쓰지 않는다.
        """
        root = self.data_dir / BACKUP_DIR_NAME
        stamp = _backup_stamp()
        target = root / stamp
        suffix = 0
        while target.exists():
            suffix += 1
            target = root / f"{stamp}-{suffix}"
        backup_files(self.data_dir, target)
        return target


def build_services(data_dir: Path) -> Services:
    """저장 폴더를 초기화(D04, D23, D36)하고 저장소와 서비스를 조립한다. 안내 출력은 cli 가 맡는다."""
    initialized = ensure_initialized(data_dir)
    # 같은 저장소 객체를 공유해 모든 서비스가 동일한 가계부 파일을 사용하게 한다.
    tx_repo = TransactionRepository(JsonlStore(data_dir / TRANSACTIONS_FILE))
    category_store = CategoryStore(JsonlStore(data_dir / CATEGORIES_FILE))
    budget_store = BudgetStore(JsonlStore(data_dir / BUDGETS_FILE))
    recurring_store = RecurringStore(JsonlStore(data_dir / RECURRING_FILE))
    return Services(
        data_dir=data_dir,
        transactions=TransactionService(tx_repo, category_store),
        categories=CategoryService(category_store, tx_repo),
        budgets=BudgetService(budget_store, tx_repo),
        recurring=RecurringService(recurring_store, tx_repo, category_store),
        initialized=initialized,
    )
