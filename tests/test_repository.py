"""repository 계층 테스트: 스트리밍·원자성·초기화·id 발급·손상 줄을 시나리오 단위로 확인한다 (AGENT.md 9장 P2, 10장)."""
from __future__ import annotations

import json
import tempfile
import types
import unittest
from itertools import islice
from pathlib import Path
from typing import Any, Iterator

from budget_app.errors import ConflictError, NotFoundError, StorageError
from budget_app.models import Budget, Transaction
from budget_app.repository import (
    BUDGETS_FILE,
    CATEGORIES_FILE,
    DATA_FILES,
    DEFAULT_CATEGORIES,
    RECURRING_FILE,
    TRANSACTIONS_FILE,
    BudgetStore,
    CategoryStore,
    JsonlStore,
    TransactionRepository,
    ensure_initialized,
)

BIG_LINE_COUNT = 100_000


def make_tx(number: int, date: str = "2024-01-15", category: str = "food") -> Transaction:
    """번호마다 다른 금액과 메모를 가진 거래를 만들어 보존 여부를 구분한다."""
    return Transaction(
        id=f"TX-{number:06d}", type="expense", date=date, amount=1000 + number, category=category, memo=f"메모 {number}"
    )


def write_lines(path: Path, lines: list[str]) -> None:
    """빈 줄과 손상 줄을 포함한 JSONL 시험 자료를 UTF-8로 쓴다."""
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


class RepositoryTestCase(unittest.TestCase):
    """각 테스트는 자기만의 임시 폴더를 쓴다."""

    def setUp(self) -> None:
        """실제 사용자 데이터와 분리된 임시 저장 폴더를 준비한다."""
        self._tmp = tempfile.TemporaryDirectory(prefix="budget_app_repo_")
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def store(self, name: str = TRANSACTIONS_FILE) -> JsonlStore:
        """현재 테스트의 임시 폴더를 사용하는 JSONL 저장소를 만든다."""
        return JsonlStore(self.dir / name)

    def leftover_temp_files(self) -> list[str]:
        """재작성 성공·실패 뒤 임시 파일이 남았는지 확인할 목록을 구한다."""
        return sorted(p.name for p in self.dir.iterdir() if p.suffix == ".tmp")


class StreamingScenario(RepositoryTestCase):
    """(1) 10만 줄 파일을 islice 로 앞 3개만 소비해도 전체를 리스트로 만들지 않는다 (C5)."""

    def test_islice_consumes_only_the_head_of_a_huge_file(self) -> None:
        # 4행을 고의로 손상시킨다. 제너레이터가 아니라 전체를 먼저 읽는 구현이라면 여기서 StorageError 가 난다.
        """대용량 파일의 앞부분만 읽을 때 뒤의 손상 줄을 미리 읽지 않는지 확인한다."""
        lines = [json.dumps(make_tx(n).to_dict(), ensure_ascii=False) for n in range(1, BIG_LINE_COUNT + 1)]
        lines[3] = "{이 줄은 JSON 이 아니다"
        path = self.dir / TRANSACTIONS_FILE
        write_lines(path, lines)
        self.assertGreater(path.stat().st_size, 10_000_000)

        store = JsonlStore(path)
        generator = store.iter_records()
        self.assertIsInstance(generator, types.GeneratorType)
        head = list(islice(generator, 3))
        generator.close()
        self.assertEqual([r["id"] for r in head], ["TX-000001", "TX-000002", "TX-000003"])

        repo = TransactionRepository(store)
        tx_iter = repo.iter_all()
        self.assertIsInstance(tx_iter, Iterator)
        first_three = list(islice(tx_iter, 3))
        tx_iter.close()
        self.assertEqual([tx.amount for tx in first_three], [1001, 1002, 1003])

        # 4번째까지 소비하면 손상 줄에 닿아 파일명과 행 번호가 있는 StorageError 가 난다.
        with self.assertRaises(StorageError) as ctx:
            list(islice(store.iter_records(), 4))
        self.assertIn(TRANSACTIONS_FILE, ctx.exception.message)
        self.assertIn("4행", ctx.exception.message)
        self.assertTrue(ctx.exception.hint)


class AtomicRewriteScenario(RepositoryTestCase):
    """(2) rewrite 도중 예외가 나면 원본이 보존되고 임시 파일이 남지 않는다 (C6, D21)."""

    def test_failure_keeps_original_and_success_replaces_it(self) -> None:
        """중간 실패는 원본을 보존하고 성공한 재작성만 원본을 교체하는지 확인한다."""
        store = self.store()
        for n in range(1, 4):
            store.append(make_tx(n).to_dict())
        original = store.path.read_bytes()
        self.assertTrue(original.endswith(b"\n"))
        self.assertNotIn(b"\r\n", original)  # LF 고정 (D01)

        class Injected(RuntimeError):
            """저장 도중 발생하는 예상 밖 오류를 재현하는 시험용 예외다."""
            pass

        def exploding() -> Iterator[dict[str, Any]]:
            """한 줄을 쓴 직후 실패해 부분 저장 상황을 만든다."""
            yield make_tx(99).to_dict()
            raise Injected("재작성 도중 주입된 예외")

        with self.assertRaises(Injected):
            store.rewrite(exploding())
        self.assertEqual(store.path.read_bytes(), original)
        self.assertEqual(self.leftover_temp_files(), [])

        # 저장 계층 오류(AppError)도 감싸지지 않고 그대로 올라오며 원본은 그대로다 (D34).
        def failing_storage() -> Iterator[dict[str, Any]]:
            """이미 사용자용 오류로 변환된 저장 오류가 보존되는지 확인한다."""
            yield make_tx(98).to_dict()
            raise StorageError("주입된 저장 오류")

        with self.assertRaises(StorageError) as ctx:
            store.rewrite(failing_storage())
        self.assertEqual(ctx.exception.message, "주입된 저장 오류")
        self.assertEqual(store.path.read_bytes(), original)
        self.assertEqual(self.leftover_temp_files(), [])

        # 정상 재작성: 내용이 통째로 바뀌고 임시 파일은 남지 않는다. 입력은 제너레이터 그대로 받는다.
        repo = TransactionRepository(store)
        repo.rewrite(tx for tx in repo.iter_all() if tx.id != "TX-000002")
        self.assertEqual([tx.id for tx in repo.iter_all()], ["TX-000001", "TX-000003"])
        self.assertEqual(self.leftover_temp_files(), [])

        # 빈 결과로 재작성하면 0바이트 파일이 된다 (전부 삭제한 경우).
        repo.rewrite(iter(()))
        self.assertEqual(store.path.read_bytes(), b"")
        self.assertEqual(list(repo.iter_all()), [])


class InitializationScenario(RepositoryTestCase):
    """(3) 초기화: 폴더·파일 4개 생성, 기본 카테고리 5개, 두 번째 호출은 False (D04, D23, D35, D44)."""

    def test_fresh_dir_then_idempotent(self) -> None:
        """첫 초기화·재초기화·일부 파일 누락 복구에서 사용자 설정을 보존한다."""
        data_dir = self.dir / "nested" / "data"
        self.assertTrue(ensure_initialized(data_dir))
        self.assertEqual(DATA_FILES, (TRANSACTIONS_FILE, CATEGORIES_FILE, BUDGETS_FILE, RECURRING_FILE))
        for name in DATA_FILES:
            self.assertTrue((data_dir / name).is_file(), name)
        self.assertEqual(sorted(p.name for p in data_dir.iterdir()), sorted(DATA_FILES))
        categories = CategoryStore(JsonlStore(data_dir / CATEGORIES_FILE))
        self.assertEqual(categories.names(), list(DEFAULT_CATEGORIES))
        self.assertEqual(len(categories.names()), 5)
        self.assertEqual((data_dir / TRANSACTIONS_FILE).stat().st_size, 0)

        # 다시 호출해도 새로 만든 것이 없으므로 False, 카테고리는 중복 등록되지 않는다.
        self.assertFalse(ensure_initialized(data_dir))
        self.assertEqual(categories.names(), list(DEFAULT_CATEGORIES))

        # 사용자가 카테고리를 바꿔 둔 폴더는 건드리지 않고, 파일 하나가 사라졌으면 그 파일만 다시 만든다.
        categories.remove("etc")
        (data_dir / BUDGETS_FILE).unlink()
        self.assertTrue(ensure_initialized(data_dir))
        self.assertEqual(categories.names(), ["food", "transport", "rent", "salary"])

    def test_existing_dir_with_empty_category_file_gets_defaults_without_notice(self) -> None:
        """기존 빈 카테고리 파일에 기본값을 넣되 새 폴더 안내는 반복하지 않는다."""
        for name in DATA_FILES:
            (self.dir / name).touch()
        self.assertFalse(ensure_initialized(self.dir))  # 새로 만든 것은 없다
        self.assertEqual(CategoryStore(self.store(CATEGORIES_FILE)).names(), list(DEFAULT_CATEGORIES))


class NextIdScenario(RepositoryTestCase):
    """(4) next_id: 빈 파일은 TX-000001, 그 외에는 파일 순서와 무관하게 최대 번호 + 1 (D05)."""

    def test_next_id(self) -> None:
        """파일 순서와 자릿수 경계에 관계없이 활성 거래의 최대 번호 다음을 발급한다."""
        repo = TransactionRepository(self.store())
        self.assertEqual(repo.next_id(), "TX-000001")  # 파일 자체가 없어도 (D34)
        self.store().path.touch()
        self.assertEqual(repo.next_id(), "TX-000001")  # 빈 파일

        for n in (3, 10, 7):
            repo.append(make_tx(n))
        self.assertEqual(repo.next_id(), "TX-000011")
        repo.append(make_tx(1234567))
        self.assertEqual(repo.next_id(), "TX-1234568")  # 999999 초과 시 자연 확장

        # 저장된 줄은 유효한 JSONL 이고 한글 메모가 그대로 보존된다 (ensure_ascii=False, D01).
        raw = self.store().path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(raw), 4)
        self.assertIn('"memo": "메모 3"', raw[0])
        self.assertEqual(Transaction.from_dict(json.loads(raw[0])), make_tx(3))


class CorruptedLineScenario(RepositoryTestCase):
    """(5) 손상 줄은 파일명·행 번호가 담긴 StorageError, 빈 줄은 건너뛰되 번호에는 포함 (D33)."""

    def test_corrupted_lines_report_file_and_line_number(self) -> None:
        """손상 유형별로 파일과 행 번호가 있는 오류를 돌려주고 빈 줄은 건너뛴다."""
        path = self.dir / TRANSACTIONS_FILE
        good = json.dumps(make_tx(1).to_dict(), ensure_ascii=False)
        cases: list[tuple[str, int]] = [
            ("{잘못된 JSON", 3),                       # 파싱 실패
            ("[1, 2, 3]", 3),                          # 객체가 아님
            (json.dumps({"id": "TX-000002"}), 3),      # 필수 키 누락 → from_dict ValidationError
            (json.dumps({**make_tx(2).to_dict(), "amount": "100"}), 3),  # 타입 불일치
            (json.dumps({**make_tx(2).to_dict(), "id": "tx-2"}), 3),     # id 형식 불일치
        ]
        repo = TransactionRepository(JsonlStore(path))
        for bad_line, expected_line_no in cases:
            with self.subTest(bad_line=bad_line):
                write_lines(path, [good, "", bad_line, good])  # 2행은 빈 줄
                with self.assertRaises(StorageError) as ctx:
                    list(repo.iter_all())
                self.assertEqual(ctx.exception.exit_code, 1)
                self.assertIn(f"{TRANSACTIONS_FILE} {expected_line_no}행", ctx.exception.message)
                self.assertEqual(ctx.exception.format_lines()[1], "[힌트] 해당 줄을 수정하거나 backup에서 복구하세요")

        # 빈 줄과 공백만 있는 줄은 건너뛰고 나머지는 전부 읽는다.
        write_lines(path, [good, "", "   ", good])
        self.assertEqual(len(list(repo.iter_all())), 2)

        # iter_records 는 모델 검증을 하지 않으므로 필수 키 누락 줄도 dict 로 그대로 흘려 보낸다.
        write_lines(path, [json.dumps({"id": "TX-000002"})])
        self.assertEqual(list(JsonlStore(path).iter_records()), [{"id": "TX-000002"}])


class DeletedArchiveScenario(RepositoryTestCase):
    """삭제 이력은 활성 파일과 분리해 순서대로 기록하고 기존 거래 형식으로 읽는다."""

    def test_archive_is_lazy_persistent_and_preserves_active_files(self) -> None:
        """초기화 시 이력을 만들지 않고 첫 삭제 보관부터 원래 필드를 영구 저장한다."""
        ensure_initialized(self.dir)
        repo = TransactionRepository(self.store())
        first, second = make_tx(1), make_tx(2)
        repo.append(first)
        repo.append(second)
        active_before = self.store().path.read_bytes()
        archive = self.dir / "backups" / "deleted.jsonl"
        self.assertFalse(archive.exists())
        missing_history = repo.iter_deleted()
        self.assertIsInstance(missing_history, types.GeneratorType)
        self.assertEqual(list(missing_history), [])
        self.assertFalse(archive.exists())

        # 유효한 마지막 줄에 LF가 없어도 다음 보관과 레코드를 붙여 손상시키지 않는다.
        repo.archive(second)
        archive.write_bytes(archive.read_bytes().rstrip(b"\n"))
        # 보관은 활성 거래 삭제와 별개다. 같은 번호를 여러 번 보관해도 기록 순서를 유지한다.
        for tx in (first, second):
            repo.archive(tx)
        reopened = TransactionRepository(self.store())
        self.assertEqual(list(reopened.iter_deleted()), [second, first, second])
        self.assertEqual(self.store().path.read_bytes(), active_before)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir() if p.is_file()), sorted(DATA_FILES))
        self.assertEqual([Transaction.from_dict(json.loads(line)) for line in archive.read_text(encoding="utf-8").splitlines()],
                         [second, first, second])

    def test_corrupt_archive_reports_storage_error_without_changing_active_data(self) -> None:
        """잘못된 JSON과 필수 필드 누락을 저장 오류로 알리고 원본 거래는 보존한다."""
        repo = TransactionRepository(self.store())
        repo.append(make_tx(1))
        repo.archive(make_tx(2))
        archive = self.dir / "backups" / "deleted.jsonl"
        active_before = self.store().path.read_bytes()
        good = json.dumps(make_tx(2).to_dict(), ensure_ascii=False)
        for broken in ("{깨진 JSON", json.dumps({"id": "TX-000003"})):
            with self.subTest(broken=broken):
                write_lines(archive, [good, broken])
                with self.assertRaises(StorageError) as ctx:
                    list(repo.iter_deleted())
                self.assertIn("deleted.jsonl", ctx.exception.message)
                self.assertIn("2행", ctx.exception.message)
                self.assertEqual(self.store().path.read_bytes(), active_before)


class CategoryAndBudgetStoreScenario(RepositoryTestCase):
    """CategoryStore 유일성·삭제, BudgetStore 덮어쓰기 (D12, D25, D35)."""

    def test_category_store(self) -> None:
        """카테고리 정규화·대소문자 구분·중복 차단·대상 삭제를 함께 확인한다."""
        categories = CategoryStore(self.store(CATEGORIES_FILE))
        self.assertEqual(categories.names(), [])
        self.assertFalse(categories.exists("food"))

        categories.add(" food ")  # strip 정규화
        categories.add("Food")    # 대소문자 구분이므로 별개
        self.assertEqual(categories.names(), ["food", "Food"])
        self.assertTrue(categories.exists("food"))
        self.assertFalse(categories.exists(" food "))

        with self.assertRaises(ConflictError):
            categories.add("food")
        with self.assertRaises(NotFoundError):
            categories.remove("cafe")
        self.assertEqual(categories.names(), ["food", "Food"])

        categories.remove("food")
        self.assertEqual(categories.names(), ["Food"])
        self.assertEqual(self.leftover_temp_files(), [])

    def test_budget_store(self) -> None:
        """같은 월의 예산은 덮어쓰고 다른 월의 값과 저장 순서를 보존한다."""
        budgets = BudgetStore(self.store(BUDGETS_FILE))
        self.assertIsNone(budgets.get("2024-01"))
        self.assertEqual(list(budgets.iter_all()), [])

        budgets.set(Budget("2024-02", 300000))
        budgets.set(Budget("2024-01", 500000))
        budgets.set(Budget("2024-02", 350000))  # 같은 달 덮어쓰기, 자리 유지
        self.assertEqual(budgets.get("2024-02"), Budget("2024-02", 350000))
        self.assertEqual(
            list(budgets.iter_all()), [Budget("2024-02", 350000), Budget("2024-01", 500000)]
        )
        self.assertEqual(len(self.store(BUDGETS_FILE).path.read_text(encoding="utf-8").splitlines()), 2)
        self.assertEqual(self.leftover_temp_files(), [])


if __name__ == "__main__":
    unittest.main()
