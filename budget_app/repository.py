"""저장 계층: JSONL 스트리밍 읽기, append, 원자적 재작성 (AGENT.md 5장, C5, C6, D21, D33~D35).

- 읽기는 전부 제너레이터다. 파일을 한 줄씩 읽어 JSON 객체를 yield 하고, 리스트로 모으지 않는다.
- 추가는 파일 끝에 1줄 append 한다.
- 재작성은 같은 폴더의 임시 파일에 전부 쓰고 flush + fsync 한 뒤 os.replace 로 교체한다. 실패하면
  임시 파일을 지우고 원본은 건드리지 않는다.
- 비즈니스 규칙(사용 중 카테고리, 집계)과 출력은 여기서 하지 않는다. 저장 파일의 불변 조건(카테고리 유일성,
  월별 예산 1건)만 지킨다.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, TypeVar

from .errors import AppError, ConflictError, NotFoundError, StorageError, ValidationError
from .models import (
    Budget,
    Category,
    RecurringRule,
    Transaction,
    format_recurring_id,
    parse_category_name,
    recurring_number,
    transaction_number,
)

# 초기화와 전체 백업은 현재 사용 중인 네 파일만 대상으로 삼는다.
TRANSACTIONS_FILE = "transactions.jsonl"
CATEGORIES_FILE = "categories.jsonl"
BUDGETS_FILE = "budgets.jsonl"
RECURRING_FILE = "recurring.jsonl"  # D44
# 삭제 이력은 활성 데이터가 아니라 복구용 보관 기록이므로 DATA_FILES에 넣지 않는다 (D47).
DELETED_FILE = "deleted.jsonl"
DATA_FILES: tuple[str, ...] = (TRANSACTIONS_FILE, CATEGORIES_FILE, BUDGETS_FILE, RECURRING_FILE)
DEFAULT_CATEGORIES: tuple[str, ...] = ("food", "transport", "rent", "salary", "etc")  # D04

ENCODING = "utf-8"
CORRUPTED_HINT = "해당 줄을 수정하거나 backup에서 복구하세요"

T = TypeVar("T")


def _storage_error(path: Path, exc: OSError) -> StorageError:
    """OSError 를 사용자 메시지로 감싼다 (D34). 스택트레이스 대신 원인과 경로만 남긴다."""
    reason = exc.strerror or type(exc).__name__
    return StorageError(
        f"저장 파일을 처리할 수 없습니다: {path.name} ({reason})",
        hint=f"폴더와 권한을 확인하세요: {path.parent}",
    )


def _corrupted(path: Path, line_no: int) -> StorageError:
    """손상 줄 오류 (D33). 파일명과 물리적 줄 번호를 함께 알린다."""
    return StorageError(f"저장 파일 {path.name} {line_no}행이 손상되었습니다", hint=CORRUPTED_HINT)


class JsonlStore:
    """JSONL 파일 1개를 다룬다. 읽기는 제너레이터, 재작성은 임시 파일 + os.replace."""

    def __init__(self, path: Path) -> None:
        """경로만 보관한다. 도움말이나 객체 생성만으로 파일을 만들지 않는다."""
        self.path = path

    # -- 읽기 ---------------------------------------------------------------

    def _iter_numbered(self) -> Iterator[tuple[int, dict[str, Any]]]:
        """(줄 번호, JSON 객체) 를 한 줄씩 yield 한다. 빈 줄은 건너뛰되 줄 번호에는 포함한다 (D33)."""
        try:
            handle = open(self.path, "r", encoding=ENCODING)
        except FileNotFoundError:
            return  # 파일이 없으면 0건 (D34)
        except OSError as exc:
            raise _storage_error(self.path, exc) from None
        with handle:
            try:
                for line_no, line in enumerate(handle, start=1):
                    text = line.strip()
                    if not text:
                        continue
                    try:
                        record = json.loads(text)
                    except ValueError:
                        raise _corrupted(self.path, line_no) from None
                    if not isinstance(record, dict):
                        # JSON 문법이 맞아도 배열·숫자는 레코드 계약에 맞지 않는다.
                        raise _corrupted(self.path, line_no)
                    yield line_no, record
            except (OSError, UnicodeDecodeError) as exc:
                if isinstance(exc, OSError):
                    raise _storage_error(self.path, exc) from None
                raise StorageError(
                    f"저장 파일 {self.path.name} 을(를) UTF-8 로 읽을 수 없습니다", hint=CORRUPTED_HINT
                ) from None

    def iter_records(self) -> Iterator[dict[str, Any]]:
        """한 줄씩 JSON 객체를 yield 한다. 빈 줄은 건너뛰고 손상된 줄은 StorageError (C5, D33)."""
        for _line_no, record in self._iter_numbered():
            yield record

    def iter_parsed(self, from_dict: Callable[[dict[str, Any]], T]) -> Iterator[T]:
        """레코드를 모델로 바꾸며 yield 한다. 변환 중 ValidationError 는 줄 번호를 붙여 StorageError 로 바꾼다 (D33)."""
        for line_no, record in self._iter_numbered():
            try:
                yield from_dict(record)
            except ValidationError:
                raise _corrupted(self.path, line_no) from None

    # -- 쓰기 ---------------------------------------------------------------

    @staticmethod
    def _dump(record: dict[str, Any]) -> str:
        """한글을 읽을 수 있는 JSON 한 건에 줄바꿈을 붙여 JSONL 경계를 유지한다."""
        return json.dumps(record, ensure_ascii=False) + "\n"

    def append(self, record: dict[str, Any]) -> None:
        """파일 끝에 한 줄을 더한다. 파일이 없으면 새로 만든다 (D01, D34)."""
        try:
            with open(self.path, "a", encoding=ENCODING, newline="\n") as handle:
                handle.write(self._dump(record))
        except OSError as exc:
            raise _storage_error(self.path, exc) from None

    def rewrite(self, records: Iterable[dict[str, Any]]) -> None:
        """임시 파일에 전부 쓴 뒤 os.replace 로 교체한다 (D21, D34).

        레코드 제너레이터가 도중에 예외를 던져도 원본은 그대로 남고 임시 파일은 지워진다.
        """
        directory = self.path.parent
        try:
            # 같은 파일 시스템에 임시 파일을 두어 마지막 교체를 원자적으로 수행한다.
            tmp = tempfile.NamedTemporaryFile(
                mode="w",
                encoding=ENCODING,
                newline="\n",
                dir=directory,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            )
        except OSError as exc:
            raise _storage_error(self.path, exc) from None
        tmp_path = Path(tmp.name)
        try:
            with tmp:
                for record in records:
                    tmp.write(self._dump(record))
                # 교체 전에 Python 버퍼와 운영체제 버퍼의 쓰기를 완료한다.
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_path, self.path)
        except BaseException as exc:
            # 입력 제너레이터의 실패와 사용자 중단에서도 임시 파일만 제거한다.
            self._discard(tmp_path)
            if isinstance(exc, AppError):
                raise
            if isinstance(exc, OSError):
                raise _storage_error(self.path, exc) from None
            raise

    @staticmethod
    def _discard(tmp_path: Path) -> None:
        """실패한 재작성의 임시 파일을 지운다. 지우지 못해도 원본 보존이 우선이므로 조용히 넘어간다."""
        try:
            os.remove(tmp_path)
        except OSError:
            pass


class TransactionRepository:
    """거래 저장소. id 형식까지 검증한 Transaction 만 흘려 보낸다 (D05, D33)."""

    def __init__(self, store: JsonlStore) -> None:
        """파일 I/O 구현을 주입받아 거래 모델의 직렬화만 담당한다."""
        self.store = store
        self.deleted_store = JsonlStore(store.path.parent / "backups" / DELETED_FILE)

    @staticmethod
    def _from_record(record: dict[str, Any]) -> Transaction:
        """필드와 번호를 함께 검사해 잘못된 저장 줄이 서비스로 넘어가지 않게 한다."""
        tx = Transaction.from_dict(record)
        transaction_number(tx.id)  # `TX-000012` 형식이 아니면 ValidationError → 손상 줄 (D33)
        return tx

    def iter_all(self) -> Iterator[Transaction]:
        """파일 순서대로 한 건씩 yield 한다. 정렬은 서비스가 heapq 로 한다 (C5, D07)."""
        yield from self.store.iter_parsed(self._from_record)

    def next_id(self) -> str:
        """스트리밍으로 구한 최대 번호 + 1 (D05). 빈 파일이면 TX-000001."""
        highest = 0
        for tx in self.iter_all():
            number = transaction_number(tx.id)
            if number > highest:
                highest = number
        return f"TX-{highest + 1:06d}"

    def append(self, tx: Transaction) -> None:
        """검증된 거래를 JSON 객체로 바꾸어 기존 파일 끝에 추가한다."""
        self.store.append(tx.to_dict())

    def archive(self, tx: Transaction) -> None:
        """기존 이력을 보존하며 원본 한 건을 원자적으로 더한다. 보관 실패 시 삭제하지 않는다 (D47)."""
        try:
            # 삭제 기능을 처음 사용할 때만 복구 이력을 둘 폴더를 준비한다.
            self.deleted_store.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise _storage_error(self.deleted_store.path, exc) from None

        def archived() -> Iterator[dict[str, Any]]:
            """기존 기록을 검증하며 순서대로 넘긴 뒤 삭제 직전 원본을 마지막에 더한다."""
            for deleted in self.iter_deleted():
                yield deleted.to_dict()
            yield tx.to_dict()

        # 직접 append하면 쓰기 실패로 이력 끝이 잘릴 수 있다. 재작성은 기존 이력을
        # 모두 검증하고 각 줄의 LF 경계와 flush·fsync를 완료한 뒤 한 번에 교체한다.
        self.deleted_store.rewrite(archived())

    def iter_deleted(self) -> Iterator[Transaction]:
        """보관된 원본을 삭제 순서대로 전달한다. 이력이 없으면 아무것도 생성하지 않는다 (D47)."""
        yield from self.deleted_store.iter_parsed(self._from_record)

    def rewrite(self, transactions: Iterable[Transaction]) -> None:
        """전체를 다시 쓴다 (update/delete/재배정용, D21). 입력도 제너레이터 그대로 흘려 보낸다."""
        self.store.rewrite(tx.to_dict() for tx in transactions)


class CategoryStore:
    """카테고리 저장소. 이름의 유일성을 지킨다 (D12, D35)."""

    def __init__(self, store: JsonlStore) -> None:
        """카테고리를 읽고 쓸 JSONL 저장소를 연결한다."""
        self.store = store

    def _iter_names(self) -> Iterator[str]:
        """모델 검증을 거친 이름을 한 건씩 전달해 존재 검사의 조기 종료를 허용한다."""
        for category in self.store.iter_parsed(Category.from_dict):
            yield category.name

    def names(self) -> list[str]:
        """파일 순서 그대로. 정렬은 서비스가 한다."""
        return list(self._iter_names())

    def exists(self, name: str) -> bool:
        """일치하는 이름을 찾는 즉시 멈추며 전체 목록을 메모리에 올리지 않는다."""
        return any(existing == name for existing in self._iter_names())

    def add(self, name: str) -> None:
        """이름을 정규화해 1줄 추가한다. 이미 있으면 ConflictError (D35)."""
        clean = parse_category_name(name)
        if self.exists(clean):
            raise ConflictError(
                f"이미 등록된 카테고리입니다: {clean}",
                hint="python -m budget_app category list 로 목록을 확인하세요",
            )
        self.store.append(Category(clean).to_dict())

    def remove(self, name: str) -> None:
        """해당 이름을 제외하고 재작성한다. 없는 이름이면 NotFoundError (D35). 사용 중 여부는 서비스가 검사한다 (D18)."""
        if not self.exists(name):
            raise NotFoundError(
                f"카테고리를 찾을 수 없습니다: {name}",
                hint="python -m budget_app category list 로 목록을 확인하세요",
            )
        self.store.rewrite(
            category.to_dict() for category in self.store.iter_parsed(Category.from_dict) if category.name != name
        )


class BudgetStore:
    """월 예산 저장소. 한 달에 레코드 1건을 유지한다 (D25, D35)."""

    def __init__(self, store: JsonlStore) -> None:
        """월별 예산을 저장할 JSONL 저장소를 연결한다."""
        self.store = store

    def get(self, month: str) -> Budget | None:
        """지정한 월의 예산을 찾아 돌려주고 설정되지 않았으면 None을 돌려준다."""
        for budget in self.iter_all():
            if budget.month == month:
                return budget
        return None

    def set(self, budget: Budget) -> None:
        """같은 달이 있으면 그 자리에서 덮어쓰고, 없으면 끝에 더한다 (D25). 재작성은 원자적이다 (D21)."""
        if self.get(budget.month) is None:
            self.store.append(budget.to_dict())
            return

        def replaced() -> Iterator[dict[str, Any]]:
            """다른 월의 위치와 값을 유지하며 대상 월만 새 예산으로 바꾼다."""
            for existing in self.iter_all():
                yield (budget if existing.month == budget.month else existing).to_dict()

        self.store.rewrite(replaced())

    def iter_all(self) -> Iterator[Budget]:
        """파일 순서대로 yield 한다. 월 오름차순 정렬은 서비스가 한다."""
        yield from self.store.iter_parsed(Budget.from_dict)


class RecurringStore:
    """반복 내역 규칙 저장소 (D44). TransactionRepository 와 같은 패턴이며 id 는 `RC-` 접두사."""

    def __init__(self, store: JsonlStore) -> None:
        """반복 규칙 파일의 읽기·쓰기를 맡을 저장소를 연결한다."""
        self.store = store

    @staticmethod
    def _from_record(record: dict[str, Any]) -> RecurringRule:
        """반복 규칙의 필드와 RC 번호를 검증해 손상 줄을 일관되게 처리한다."""
        rule = RecurringRule.from_dict(record)
        recurring_number(rule.id)  # `RC-000001` 형식이 아니면 ValidationError → 손상 줄 (D33)
        return rule

    def iter_all(self) -> Iterator[RecurringRule]:
        """파일에 저장된 순서대로 검증된 규칙을 한 건씩 전달한다."""
        yield from self.store.iter_parsed(self._from_record)

    def next_id(self) -> str:
        """스트리밍으로 구한 최대 번호 + 1. 빈 파일이면 RC-000001."""
        highest = 0
        for rule in self.iter_all():
            number = recurring_number(rule.id)
            if number > highest:
                highest = number
        return format_recurring_id(highest + 1)

    def append(self, rule: RecurringRule) -> None:
        """완성된 규칙을 한 줄로 저장하며 기존 규칙은 다시 쓰지 않는다."""
        self.store.append(rule.to_dict())

    def remove(self, rule_id: str) -> RecurringRule:
        """해당 id 를 빼고 재작성한다. 없으면 NotFoundError. 삭제된 규칙을 돌려준다."""
        target: RecurringRule | None = None
        for rule in self.iter_all():
            if rule.id == rule_id:
                target = rule
                break
        if target is None:
            raise NotFoundError(
                f"반복 내역을 찾을 수 없습니다: {rule_id}", hint="python -m budget_app recurring list 로 id를 확인하세요."
            )
        # 대상이 없을 때는 재작성하지 않으므로 실패한 삭제가 파일을 바꾸지 않는다.
        self.store.rewrite(rule.to_dict() for rule in self.iter_all() if rule.id != rule_id)
        return target


def backup_files(data_dir: Path, target_dir: Path) -> list[Path]:
    """저장 파일(DATA_FILES, 4개)을 target_dir 로 복사(shutil.copy2)하고 복사된 경로를 돌려준다 (D43, D44). 실패는 StorageError."""
    try:
        # 기존 백업 폴더는 덮어쓰지 않는다. 이름 충돌 해소는 서비스가 맡는다.
        target_dir.mkdir(parents=True, exist_ok=False)
        copied: list[Path] = []
        for name in DATA_FILES:
            copied.append(Path(shutil.copy2(data_dir / name, target_dir / name)))
        return copied
    except OSError as exc:
        raise StorageError(
            f"백업을 만들 수 없습니다: {target_dir} ({exc.strerror or type(exc).__name__})",
            hint="저장 폴더에 파일 3개가 있는지와 쓰기 권한을 확인하세요",
        ) from None


def ensure_initialized(data_dir: Path) -> bool:
    """폴더와 저장 파일(DATA_FILES, 4개)을 만들고, 카테고리가 0건이면 기본 카테고리를 채운다 (D04, D23, D35, D44).

    폴더·파일 중 하나라도 새로 만들었으면 True. 안내 출력은 호출한 cli 계층이 맡는다.
    """
    created = False
    try:
        if not data_dir.is_dir():
            data_dir.mkdir(parents=True, exist_ok=True)
            created = True
        for name in DATA_FILES:
            path = data_dir / name
            if not path.exists():
                path.touch()
                created = True
    except OSError as exc:
        raise StorageError(
            f"저장 폴더를 만들 수 없습니다: {data_dir} ({exc.strerror or type(exc).__name__})",
            hint="--data-dir 로 쓸 수 있는 폴더를 지정하세요",
        ) from None

    category_store = JsonlStore(data_dir / CATEGORIES_FILE)
    if not any(True for _ in category_store.iter_records()):
        # 기존 분류가 하나라도 있으면 사용자 목록을 그대로 사용한다.
        for name in DEFAULT_CATEGORIES:
            category_store.append(Category(name).to_dict())
    return created
