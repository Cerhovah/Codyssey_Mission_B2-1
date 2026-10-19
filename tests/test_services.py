"""서비스의 거래 관리·검색·집계·백업·반복·삭제 복구를 독립된 임시 자료로 확인한다."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from budget_app.errors import ConflictError, NotFoundError, StorageError, ValidationError
from budget_app.models import Budget
from budget_app.repository import CATEGORIES_FILE, DATA_FILES, DEFAULT_CATEGORIES, JsonlStore
from budget_app.services import Services, build_services


class ServicesTestCase(unittest.TestCase):
    """서비스 계층 시나리오에서 사용할 독립 저장소와 공통 거래 자료를 준비한다."""
    def setUp(self) -> None:
        """실제 사용자 데이터와 분리된 임시 저장 폴더를 준비한다."""
        self._tmp = tempfile.TemporaryDirectory(prefix="budget_app_svc_")
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name) / "data"
        self.svc: Services = build_services(self.data_dir)

    def add(
        self, date: str, type_: str = "expense", category: str = "food", amount: int = 1000,
        memo: str = "", tags: str = "",
    ) -> str:
        """간단한 인자로 거래를 추가하고 후속 시나리오에서 쓸 번호만 돌려준다."""
        return self.svc.transactions.add(
            date=date, type_=type_, category=category, amount=amount, memo=memo, tags=tags
        ).id

    def seed_january(self) -> None:
        """2024-01 수입 1건·지출 3건(food 2, transport 1) + 2023-12 지출 1건."""
        self.add("2024-01-14", "income", "salary", 3000000, memo="월급")                 # TX-000001
        self.add("2024-01-15", "expense", "food", 15000, memo="점심", tags="meal")        # TX-000002
        self.add("2024-01-20", "expense", "food", 30000, memo="저녁 Dinner", tags="meal,family")  # TX-000003
        self.add("2024-01-12", "expense", "transport", 20000, memo="버스")               # TX-000004
        self.add("2023-12-31", "expense", "rent", 500000, memo="12월 월세")              # TX-000005


class BuildAndCategoryScenario(ServicesTestCase):
    """build_services 가 초기화하고(D36), CategoryService 는 정렬·정규화·중복 오류를 지킨다 (D12, D26, D35)."""

    def test_initialization_and_category_management(self) -> None:
        """조립 시 초기화와 카테고리 추가·조회·오류 힌트를 검증한다."""
        self.assertTrue(self.svc.initialized)
        self.assertFalse(build_services(self.data_dir).initialized)  # 두 번째 조립은 새로 만든 것이 없다
        self.assertEqual(self.svc.categories.list_names(), sorted(DEFAULT_CATEGORIES))

        self.assertEqual(self.svc.categories.add("  cafe "), "cafe")
        self.assertIn("cafe", self.svc.categories.list_names())
        self.assertEqual(self.svc.categories.list_names(), sorted(self.svc.categories.list_names()))
        with self.assertRaises(ConflictError):
            self.svc.categories.add("cafe")
        with self.assertRaises(ValidationError):
            self.svc.categories.add("   ")
        self.assertEqual(len(list(JsonlStore(self.data_dir / CATEGORIES_FILE).iter_records())), 6)

        self.assertEqual(self.svc.categories.require(" cafe "), "cafe")
        with self.assertRaises(NotFoundError) as ctx:
            self.svc.categories.require("coffee")
        self.assertIn("coffee", ctx.exception.message)
        self.assertIn("cafe", ctx.exception.hint)  # 힌트에 등록 목록
        self.assertIn("food", ctx.exception.hint)


class TransactionAddScenario(ServicesTestCase):
    """add: 검증 조합, 미등록 카테고리 실패, id 가 1부터 증가 (D05, D08~D11)."""

    def test_add_validates_and_assigns_increasing_ids(self) -> None:
        """정상 입력 정규화와 잘못된 입력 거부 후 번호·저장 건수 보존을 확인한다."""
        tx = self.svc.transactions.add(
            date=" 2024-01-15 ", type_="Expense", category="food", amount="15000", memo=" 점심 ", tags="meal, daily,meal"
        )
        self.assertEqual(tx.id, "TX-000001")
        self.assertEqual((tx.type, tx.date, tx.amount, tx.category, tx.memo, tx.tags),
                         ("expense", "2024-01-15", 15000, "food", "점심", ["meal", "daily"]))
        self.assertEqual(self.add("2024-01-14", "income", "salary", 3000000), "TX-000002")

        # 실패하는 추가는 id 를 소비하지 않고 아무것도 저장하지 않는다.
        failures = [
            dict(date="2024-13-40", type_="expense", category="food", amount=1),
            dict(date="2024-01-15", type_="transfer", category="food", amount=1),
            dict(date="2024-01-15", type_="expense", category="coffee", amount=1),
            dict(date="2024-01-15", type_="expense", category="food", amount="0"),
            dict(date="2024-01-15", type_="expense", category="food", amount="1,000"),
        ]
        for kwargs in failures:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises((ValidationError, NotFoundError)):
                    self.svc.transactions.add(**kwargs)  # type: ignore[arg-type]
        with self.assertRaises(NotFoundError) as ctx:
            self.svc.transactions.add(date="2024-01-15", type_="expense", category="coffee", amount=1)
        self.assertIn("등록된 카테고리", ctx.exception.hint)
        self.assertEqual(self.add("2024-01-16"), "TX-000003")
        self.assertEqual(len(self.svc.transactions.list_recent(100)), 3)


class ListRecentScenario(ServicesTestCase):
    """list_recent: 날짜 내림차순, 같은 날짜는 id 내림차순, limit 만큼만 (D06, D07, D27)."""

    def test_order_and_limit(self) -> None:
        """거래 날짜와 번호의 내림차순 및 조회 개수 제한을 확인한다."""
        self.assertEqual(self.svc.transactions.list_recent(20), [])
        ids = [
            self.add("2024-01-15"),            # TX-000001
            self.add("2024-01-14", "income", "salary"),  # TX-000002
            self.add("2024-01-15", category="transport"),  # TX-000003 (같은 날짜, 더 큰 id)
            self.add("2023-12-31"),            # TX-000004 (가장 오래됨)
        ]
        self.assertEqual(ids, ["TX-000001", "TX-000002", "TX-000003", "TX-000004"])

        recent = [tx.id for tx in self.svc.transactions.list_recent(20)]
        self.assertEqual(recent, ["TX-000003", "TX-000001", "TX-000002", "TX-000004"])
        self.assertEqual([tx.id for tx in self.svc.transactions.list_recent(2)], ["TX-000003", "TX-000001"])
        self.assertEqual([tx.id for tx in self.svc.transactions.list_recent(1)], ["TX-000003"])


class SearchScenario(ServicesTestCase):
    """search: 조건 AND, 최신순 정렬, limit, 날짜 검증 (D28, D38)."""

    def ids(self, **kwargs: object) -> list[str]:
        """검색 결과를 번호 목록으로 바꿔 필터별 결과를 비교한다."""
        return [tx.id for tx in self.svc.transactions.search(**kwargs)]  # type: ignore[arg-type]

    def test_conditions_sorting_and_limit(self) -> None:
        """검색 조건의 교집합·최신순·제한과 잘못된 기간 처리를 확인한다."""
        self.seed_january()
        self.assertEqual(self.ids(), ["TX-000003", "TX-000002", "TX-000001", "TX-000004", "TX-000005"])  # 조건 없음 = 전체 최신순
        self.assertEqual(self.ids(type_=" Income "), ["TX-000001"])
        self.assertEqual(self.ids(category="food"), ["TX-000003", "TX-000002"])
        self.assertEqual(self.ids(category="Food"), [])          # 정확 일치, 미등록이어도 오류 없이 0건
        self.assertEqual(self.ids(query="dinner"), ["TX-000003"])  # 메모 부분 일치, 대소문자 무시
        self.assertEqual(self.ids(query="월"), ["TX-000001", "TX-000005"])
        self.assertEqual(self.ids(tag="meal"), ["TX-000003", "TX-000002"])
        self.assertEqual(self.ids(tag="mea"), [])                 # 태그는 정확 일치
        self.assertEqual(self.ids(date_from="2024-01-13", date_to="2024-01-15"), ["TX-000002", "TX-000001"])  # 포함 범위
        self.assertEqual(self.ids(date_from="2024-01-15"), ["TX-000003", "TX-000002"])
        self.assertEqual(self.ids(date_to="2023-12-31"), ["TX-000005"])
        self.assertEqual(self.ids(category="food", tag="family", query="저녁"), ["TX-000003"])  # AND
        self.assertEqual(self.ids(category="food", type_="income"), [])
        self.assertEqual(self.ids(limit=2), ["TX-000003", "TX-000002"])
        self.assertEqual(self.ids(category="food", limit=1), ["TX-000003"])
        self.assertEqual(self.ids(query="   ", tag=""), self.ids())  # 빈 조건은 조건 없음

        for bad in (dict(date_from="2024-1-5"), dict(date_to="어제"), dict(type_="transfer"),
                    dict(date_from="2024-01-20", date_to="2024-01-10")):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    self.svc.transactions.search(**bad)  # type: ignore[arg-type]


class SummaryAndBudgetScenario(ServicesTestCase):
    """summary 집계·TOP·데이터 없음·예산, budget 덮어쓰기·정렬 (D16, D17, D25, D39)."""

    def test_summary_and_budget(self) -> None:
        """월별 합계·분류 순위·빈 달과 예산 변경을 한 흐름으로 확인한다."""
        empty = self.svc.budgets.summary("2024-01", 5)
        self.assertEqual((empty.count, empty.income, empty.expense, empty.budget, empty.top_expenses), (0, 0, 0, None, []))

        self.seed_january()
        result = self.svc.budgets.summary(" 2024-01 ", 2)
        self.assertEqual((result.month, result.count), ("2024-01", 4))
        self.assertEqual((result.income, result.expense, result.balance), (3000000, 65000, 2935000))
        self.assertEqual(result.top_expenses, [("food", 45000), ("transport", 20000)])
        self.assertIsNone(result.budget)
        self.assertEqual(self.svc.budgets.summary("2024-01", 1).top_expenses, [("food", 45000)])

        # 같은 금액은 이름 오름차순, 수입만 있는 달은 TOP 이 비어 있다
        self.add("2024-03-01", "expense", "transport", 7000)
        self.add("2024-03-02", "expense", "etc", 7000)
        self.assertEqual(self.svc.budgets.summary("2024-03", 5).top_expenses, [("etc", 7000), ("transport", 7000)])
        self.add("2024-04-01", "income", "salary", 10)
        april = self.svc.budgets.summary("2024-04", 5)
        self.assertEqual((april.count, april.income, april.top_expenses), (1, 10, []))

        # 예산: 검증, 덮어쓰기, 월 오름차순, summary 에 실림
        self.assertEqual(self.svc.budgets.list_all(), [])
        self.assertEqual(self.svc.budgets.set_budget("2024-02", "300000"), Budget("2024-02", 300000))
        self.assertEqual(self.svc.budgets.set_budget("2024-01", 100000), Budget("2024-01", 100000))
        self.assertEqual(self.svc.budgets.set_budget("2024-01", "50000"), Budget("2024-01", 50000))  # 덮어쓰기
        self.assertEqual(self.svc.budgets.list_all(), [Budget("2024-01", 50000), Budget("2024-02", 300000)])
        self.assertEqual(self.svc.budgets.summary("2024-01", 5).budget, Budget("2024-01", 50000))
        self.assertEqual(self.svc.budgets.summary("2024-02", 5).budget, Budget("2024-02", 300000))  # 데이터 없음 + 예산
        for month, amount in (("2024-13", 1), ("2024-1", 1), ("2024-01", "0"), ("2024-01", "1,000")):
            with self.subTest(month=month, amount=amount):
                with self.assertRaises(ValidationError):
                    self.svc.budgets.set_budget(month, amount)
        with self.assertRaises(ValidationError):
            self.svc.budgets.summary("2024/01", 5)


class UpdateDeleteScenario(ServicesTestCase):
    """update 부분 수정·검증 실패·없는 id, delete 성공·없는 id·건수 감소, 다른 거래 보존 (D03, D21, D40)."""

    def snapshot(self) -> list[tuple[str, str, str, int, str, str, list[str]]]:
        """거래의 모든 필드를 모아 수정·실패 전후의 보존 여부를 비교한다."""
        return [(t.id, t.type, t.date, t.amount, t.category, t.memo, t.tags) for t in self.svc.transactions.list_recent(100)]

    def test_update_then_delete(self) -> None:
        """부분 수정과 실패 시 보존을 검증한 뒤 지정한 거래만 삭제한다."""
        self.seed_january()
        before = self.snapshot()
        raw_before = (self.data_dir / "transactions.jsonl").read_bytes()

        updated = self.svc.transactions.update(" TX-000002 ", amount="18000", memo="점심+커피", tags="meal, coffee")
        self.assertEqual((updated.id, updated.amount, updated.memo, updated.tags), ("TX-000002", 18000, "점심+커피", ["meal", "coffee"]))
        self.assertEqual((updated.type, updated.date, updated.category), ("expense", "2024-01-15", "food"))  # 나머지 유지
        after = self.snapshot()
        self.assertEqual(len(after), 5)
        self.assertEqual([row for row in after if row[0] != "TX-000002"], [row for row in before if row[0] != "TX-000002"])

        # 비우기와 타입·날짜·카테고리 변경 (재정렬에도 반영)
        cleared = self.svc.transactions.update("TX-000002", memo="", tags="")
        self.assertEqual((cleared.memo, cleared.tags), ("", []))
        moved = self.svc.transactions.update("TX-000005", date="2024-01-31", type_="Income", category="salary")
        self.assertEqual((moved.date, moved.type, moved.category, moved.amount), ("2024-01-31", "income", "salary", 500000))
        self.assertEqual([t.id for t in self.svc.transactions.list_recent(2)], ["TX-000005", "TX-000003"])

        # 검증 실패·없는 id 는 파일을 바꾸지 않는다
        raw_mid = (self.data_dir / "transactions.jsonl").read_bytes()
        self.assertNotEqual(raw_mid, raw_before)
        failures: list[tuple[type[Exception], str, dict[str, str]]] = [
            (ValidationError, "TX-000001", {"amount": "0"}),
            (ValidationError, "TX-000001", {"date": "2024-1-5"}),
            (ValidationError, "TX-000001", {"type_": "transfer"}),
            (NotFoundError, "TX-000001", {"category": "coffee"}),
            (NotFoundError, "TX-999999", {"amount": "1"}),
            (ValidationError, "12", {"amount": "1"}),          # id 형식 오류
            (ValidationError, "TX-000001", {}),                 # 수정 항목 없음
        ]
        for exc_type, tx_id, kwargs in failures:
            with self.subTest(tx_id=tx_id, kwargs=kwargs):
                with self.assertRaises(exc_type):
                    self.svc.transactions.update(tx_id, **kwargs)  # type: ignore[arg-type]
        self.assertEqual((self.data_dir / "transactions.jsonl").read_bytes(), raw_mid)

        # delete: 대상만 사라지고 나머지 보존, 없는 id 는 NotFoundError, 번호는 재사용되지 않음(최대값 기준)
        deleted = self.svc.transactions.delete("TX-000003")
        self.assertEqual(deleted.id, "TX-000003")
        self.assertEqual([t.id for t in self.svc.transactions.list_recent(100)], ["TX-000005", "TX-000002", "TX-000001", "TX-000004"])
        with self.assertRaises(NotFoundError) as ctx:
            self.svc.transactions.delete("TX-000003")
        self.assertEqual(ctx.exception.message, "거래를 찾을 수 없습니다: TX-000003")
        self.assertIn("list", ctx.exception.hint)
        self.assertEqual(self.add("2024-02-01"), "TX-000006")
        self.assertEqual(sorted(p.name for p in self.data_dir.iterdir() if p.suffix == ".tmp"), [])


class RestoreScenario(ServicesTestCase):
    """삭제 이력의 지속성·대상 선택·충돌 차단과 저장 실패 시 원본 보존을 확인한다."""

    def test_restore_after_reopening_preserves_original_fields_and_other_transactions(self) -> None:
        """다시 조립한 서비스도 최근 삭제를 찾아 원래 번호·태그·나머지 거래를 보존한다."""
        self.seed_january()
        original = {tx.id: tx for tx in self.svc.transactions.list_recent(100)}
        deleted = self.svc.transactions.delete("TX-000002")
        self.assertEqual(deleted, original["TX-000002"])
        self.assertEqual(len(self.svc.transactions.list_recent(100)), 4)

        # 프로세스 메모리를 사용하지 않고 파일에 남은 이력으로 복구해야 한다.
        reopened = build_services(self.data_dir)
        self.assertEqual(reopened.transactions.restore(), original["TX-000002"])
        self.assertEqual({tx.id: tx for tx in reopened.transactions.list_recent(100)}, original)
        self.assertEqual(list(reopened.transactions.transactions.iter_deleted()), [deleted])
        with self.assertRaises(ConflictError):
            reopened.transactions.restore()
        self.assertEqual({tx.id: tx for tx in reopened.transactions.list_recent(100)}, original)

    def test_restore_selects_older_id_and_latest_revision_without_overwriting(self) -> None:
        """명시한 번호의 최근 삭제본을 선택하고 이미 활성화된 번호의 덮어쓰기를 막는다."""
        self.seed_january()
        first = self.svc.transactions.delete("TX-000002")
        latest = self.svc.transactions.delete("TX-000004")
        self.assertEqual(self.svc.transactions.restore("TX-000002"), first)
        self.assertEqual(self.svc.transactions.restore(), latest)

        # 복구한 거래를 수정하고 다시 지웠다면 같은 번호의 최신 필드가 복구된다.
        revised = self.svc.transactions.update(first.id, amount="19000", memo="변경된 점심", tags="meal,new")
        self.svc.transactions.delete(first.id)
        self.assertEqual(self.svc.transactions.restore(first.id), revised)
        raw_before = (self.data_dir / "transactions.jsonl").read_bytes()
        with self.assertRaises(ConflictError):
            self.svc.transactions.restore(first.id)
        self.assertEqual((self.data_dir / "transactions.jsonl").read_bytes(), raw_before)

        # 기존 번호 발급 정책상 최대 번호를 삭제하면 재사용될 수 있다. 새 거래를 덮어쓰면 안 된다.
        self.svc.transactions.delete("TX-000005")
        reused_id = self.add("2024-02-01", memo="새 거래")
        self.assertEqual(reused_id, "TX-000005")
        current = {tx.id: tx for tx in self.svc.transactions.list_recent(100)}
        with self.assertRaises(ConflictError):
            self.svc.transactions.restore(reused_id)
        self.assertEqual({tx.id: tx for tx in self.svc.transactions.list_recent(100)}, current)

    def test_missing_history_and_missing_category_do_not_consume_saved_history(self) -> None:
        """이력 없음과 카테고리 누락은 저장을 바꾸지 않으며 분류를 재등록하면 복구할 수 있다."""
        with self.assertRaises(NotFoundError):
            self.svc.transactions.restore()
        with self.assertRaises(NotFoundError):
            self.svc.transactions.restore("TX-999999")
        with self.assertRaises(ValidationError):
            self.svc.transactions.restore("TX-2")

        self.svc.categories.add("cafe")
        tx_id = self.add("2024-01-15", category="cafe", amount=4500, memo="커피", tags="drink")
        deleted = self.svc.transactions.delete(tx_id)
        archive = self.data_dir / "backups" / "deleted.jsonl"
        archived_before = archive.read_bytes()
        self.svc.categories.remove("cafe")
        with self.assertRaises(NotFoundError):
            self.svc.transactions.restore(tx_id)
        self.assertEqual(self.svc.transactions.list_recent(100), [])
        self.assertEqual(archive.read_bytes(), archived_before)

        self.svc.categories.add("cafe")
        self.assertEqual(self.svc.transactions.restore(tx_id), deleted)
        self.assertEqual(archive.read_bytes(), archived_before)

    def test_failed_archiving_or_missing_target_never_rewrites_active_transactions(self) -> None:
        """삭제 이력이 안전하게 저장되기 전에는 원본을 다시 쓰지 않는다."""
        self.seed_january()
        repository = self.svc.transactions.transactions
        original = (self.data_dir / "transactions.jsonl").read_bytes()
        with mock.patch.object(repository, "archive", side_effect=StorageError("이력 저장 실패")) as archive:
            with mock.patch.object(repository, "rewrite") as rewrite:
                with self.assertRaises(StorageError):
                    self.svc.transactions.delete("TX-000002")
                archive.assert_called_once()
                rewrite.assert_not_called()
        self.assertEqual((self.data_dir / "transactions.jsonl").read_bytes(), original)

        # 존재하지 않는 번호의 삭제 요청은 잘못된 복구 기록을 만들지 않는다.
        with mock.patch.object(repository, "archive") as archive:
            with self.assertRaises(NotFoundError):
                self.svc.transactions.delete("TX-999999")
            archive.assert_not_called()
        self.assertEqual((self.data_dir / "transactions.jsonl").read_bytes(), original)

    def test_corrupt_deleted_history_blocks_delete_and_preserves_both_files(self) -> None:
        """이력의 앞부분이 정상이더라도 뒤에 손상 줄이 있으면 삭제와 추가 보관을 막는다."""
        self.seed_january()
        self.svc.transactions.delete("TX-000003")
        archive = self.data_dir / "backups" / "deleted.jsonl"
        archive.write_bytes(archive.read_bytes() + "{손상된 마지막 줄\n".encode("utf-8"))
        active_before = (self.data_dir / "transactions.jsonl").read_bytes()
        archive_before = archive.read_bytes()

        with self.assertRaises(StorageError):
            self.svc.transactions.delete("TX-000002")
        self.assertEqual((self.data_dir / "transactions.jsonl").read_bytes(), active_before)
        self.assertEqual(archive.read_bytes(), archive_before)

    def test_failed_archive_sync_stops_before_active_file_rewrite(self) -> None:
        """보관 파일의 디스크 동기화가 실패하면 활성 파일 재작성 자체를 시작하지 않는다."""
        self.seed_january()
        self.svc.transactions.delete("TX-000003")
        archive = self.data_dir / "backups" / "deleted.jsonl"
        archive_before = archive.read_bytes()
        active_before = (self.data_dir / "transactions.jsonl").read_bytes()
        repository = self.svc.transactions.transactions
        # 저장소 구현의 fsync를 실패시켜 실제 archive 경로를 지나게 한다.
        # TransactionRepository.rewrite만 감시하므로 삭제 이력의 JsonlStore.rewrite는 실제로 실행된다.
        with mock.patch("budget_app.repository.os.fsync", side_effect=OSError("디스크 동기화 실패")) as sync:
            with mock.patch.object(repository, "rewrite") as rewrite:
                with self.assertRaises(StorageError):
                    self.svc.transactions.delete("TX-000002")
                sync.assert_called_once()
                rewrite.assert_not_called()
        self.assertEqual((self.data_dir / "transactions.jsonl").read_bytes(), active_before)
        self.assertEqual(archive.read_bytes(), archive_before)

    def test_failed_restore_write_preserves_active_transactions_and_deleted_history(self) -> None:
        """복구 파일 쓰기가 실패해도 기존 거래와 삭제 이력을 보존해 다시 복구할 수 있다."""
        self.seed_january()
        deleted = self.svc.transactions.delete("TX-000002")
        active_before = (self.data_dir / "transactions.jsonl").read_bytes()
        archive = self.data_dir / "backups" / "deleted.jsonl"
        archive_before = archive.read_bytes()
        with mock.patch("budget_app.repository.os.fsync", side_effect=OSError("복구 쓰기 실패")):
            with self.assertRaises(StorageError):
                self.svc.transactions.restore(deleted.id)
        self.assertEqual((self.data_dir / "transactions.jsonl").read_bytes(), active_before)
        self.assertEqual(archive.read_bytes(), archive_before)
        self.assertEqual(self.svc.transactions.restore(deleted.id), deleted)


class CategoryRemoveScenario(ServicesTestCase):
    """category remove: 없음·차단·--replace 재배정·자기 자신 거부·미사용 즉시 삭제 (D18, D40)."""

    def test_remove_paths(self) -> None:
        """사용 중 분류 삭제를 차단하고 대체 분류 지정 시 거래를 보존하며 옮긴다."""
        self.seed_january()  # food 2건, transport 1건, salary 1건, rent 1건
        with self.assertRaises(NotFoundError):
            self.svc.categories.remove("cafe")
        with self.assertRaises(ConflictError) as ctx:
            self.svc.categories.remove("food")
        self.assertEqual(ctx.exception.message, "'food'를 사용하는 거래가 2건 있어 삭제할 수 없습니다.")
        self.assertIn("--replace", ctx.exception.hint)
        with self.assertRaises(ValidationError):
            self.svc.categories.remove("food", replace="food")
        with self.assertRaises(NotFoundError):
            self.svc.categories.remove("food", replace="coffee")
        self.assertIn("food", self.svc.categories.list_names())  # 실패는 아무것도 바꾸지 않는다
        self.assertEqual(len(self.svc.transactions.search(category="food")), 2)

        self.assertEqual(self.svc.categories.remove("food", replace=" etc "), 2)
        self.assertNotIn("food", self.svc.categories.list_names())
        self.assertEqual([t.id for t in self.svc.transactions.search(category="etc")], ["TX-000003", "TX-000002"])
        self.assertEqual(self.svc.transactions.search(category="food"), [])
        self.assertEqual(len(self.svc.transactions.list_recent(100)), 5)  # 거래 건수 유지, 다른 거래 보존
        self.assertEqual(self.svc.transactions.search(category="transport")[0].id, "TX-000004")

        self.assertEqual(self.svc.categories.remove("etc", replace="transport"), 2)  # 재배정 연쇄
        self.assertEqual(len(self.svc.transactions.search(category="transport")), 3)
        self.svc.categories.add("unused")
        self.assertEqual(self.svc.categories.remove("unused"), 0)                      # 미사용 즉시 삭제
        self.svc.categories.add("unused2")
        self.assertEqual(self.svc.categories.remove("unused2", replace="transport"), 0)  # 미사용 + replace 도 이동 0건
        self.assertEqual(self.svc.categories.list_names(), ["rent", "salary", "transport"])


class BackupScenario(ServicesTestCase):
    """backup: 타임스탬프 폴더에 파일 4개 복사, 같은 초 재실행은 -1/-2 접미사, 원본과 내용 동일 (B1, D43)."""

    def test_backup_creates_three_files_and_never_overwrites(self) -> None:
        """백업 파일 네 개의 내용과 같은 시각 재실행 시 폴더 분리를 확인한다."""
        self.seed_january()
        self.svc.budgets.set_budget("2024-01", 100000)
        with mock.patch("budget_app.services._backup_stamp", return_value="20240131-093000"):
            first = self.svc.backup()
            second = self.svc.backup()
            third = self.svc.backup()
        self.assertEqual(first, self.data_dir / "backups" / "20240131-093000")
        self.assertEqual(second, self.data_dir / "backups" / "20240131-093000-1")
        self.assertEqual(third, self.data_dir / "backups" / "20240131-093000-2")
        for folder in (first, second, third):
            self.assertEqual(sorted(p.name for p in folder.iterdir()), sorted(DATA_FILES))
            for name in DATA_FILES:
                self.assertEqual((folder / name).read_bytes(), (self.data_dir / name).read_bytes())

        real = self.svc.backup()  # 실제 시각 스탬프 형식 YYYYMMDD-HHMMSS
        self.assertRegex(real.name, r"^\d{8}-\d{6}(-\d+)?$")
        self.assertEqual(len(list(real.iterdir())), 4)  # recurring.jsonl 포함 (D44)

        # 백업 뒤 원본이 바뀌어도 백업은 그대로다 (복사본)
        self.svc.transactions.delete("TX-000001")
        self.assertEqual(len(list(JsonlStore(first / "transactions.jsonl").iter_records())), 5)
        self.assertEqual(len(self.svc.transactions.list_recent(100)), 4)

        # 저장 파일이 사라진 상태면 StorageError (복사 실패는 사용자 메시지로)
        (self.data_dir / "budgets.jsonl").unlink()
        with mock.patch("budget_app.services._backup_stamp", return_value="20240131-093001"):
            with self.assertRaises(StorageError):
                self.svc.backup()


class RecurringScenario(ServicesTestCase):
    """반복 내역(B2, D44): add 검증·id, list, apply 생성·말일 보정·중복 방지·미등록 카테고리 skip, remove."""

    def test_add_list_apply_remove(self) -> None:
        """반복 규칙 등록부터 말일 보정·중복 차단·분류 누락·삭제까지 확인한다."""
        self.assertEqual(self.svc.recurring.list_all(), [])
        self.assertEqual(self.svc.recurring.apply("2024-02").rule_count, 0)
        self.assertEqual(self.svc.transactions.list_recent(10), [])

        first = self.svc.recurring.add(day="25", type_=" Income ", category="salary", amount="3000000", memo=" 월급 ")
        second = self.svc.recurring.add(day=31, type_="expense", category="rent", amount=500000, memo="월세", tags="fixed, fixed")
        self.assertEqual((first.id, first.day, first.type, first.amount, first.memo, first.tags), ("RC-000001", 25, "income", 3000000, "월급", []))
        self.assertEqual((second.id, second.day, second.tags), ("RC-000002", 31, ["fixed"]))
        for bad in (dict(day="0"), dict(day="32"), dict(day="1.5"), dict(day="abc"), dict(type_="transfer"),
                    dict(category="coffee"), dict(amount="0")):
            kwargs: dict[str, object] = dict(day=1, type_="expense", category="food", amount=1)
            kwargs.update(bad)
            with self.subTest(bad=bad):
                with self.assertRaises((ValidationError, NotFoundError)):
                    self.svc.recurring.add(**kwargs)  # type: ignore[arg-type]
        self.assertEqual([r.id for r in self.svc.recurring.list_all()], ["RC-000001", "RC-000002"])

        result = self.svc.recurring.apply(" 2024-02 ")
        self.assertEqual((result.month, result.rule_count, result.created, result.skipped), ("2024-02", 2, 2, []))
        txs = {t.id: t for t in self.svc.transactions.list_recent(10)}
        self.assertEqual((txs["TX-000001"].date, txs["TX-000001"].type, txs["TX-000001"].tags), ("2024-02-25", "income", ["rc:RC-000001"]))
        self.assertEqual((txs["TX-000002"].date, txs["TX-000002"].memo, txs["TX-000002"].tags), ("2024-02-29", "월세", ["fixed", "rc:RC-000002"]))  # 윤년 말일 보정

        again = self.svc.recurring.apply("2024-02")
        self.assertEqual((again.created, len(again.skipped)), (0, 2))
        self.assertEqual(again.skipped[0], ("RC-000001", "2024-02 에 이미 적용됨 (TX-000001)"))
        self.assertEqual(len(self.svc.transactions.list_recent(10)), 2)

        self.assertEqual(self.svc.recurring.apply("2023-04").created, 2)  # 30일 달
        april = self.svc.transactions.search(tag="rc:RC-000002", date_from="2023-04-01", date_to="2023-04-30")
        self.assertEqual([t.date for t in april], ["2023-04-30"])
        self.assertEqual(self.svc.transactions.search(tag="rc:RC-000001")[0].date, "2024-02-25")

        # 미등록 카테고리가 된 규칙은 사유와 함께 skip, 나머지는 생성
        self.svc.categories.add("cafe")
        third = self.svc.recurring.add(day=1, type_="expense", category="cafe", amount=4500)
        self.svc.categories.remove("cafe")
        res = self.svc.recurring.apply("2024-05")
        self.assertEqual((res.created, res.skipped), (2, [(third.id, "등록되지 않은 카테고리입니다: cafe")]))

        self.assertEqual(self.svc.recurring.remove(" RC-000003 ").id, "RC-000003")
        with self.assertRaises(NotFoundError) as ctx:
            self.svc.recurring.remove("RC-000003")
        self.assertEqual(ctx.exception.message, "반복 내역을 찾을 수 없습니다: RC-000003")
        with self.assertRaises(ValidationError):
            self.svc.recurring.remove("TX-000001")
        with self.assertRaises(ValidationError):
            self.svc.recurring.apply("2024-2")
        self.assertEqual([r.id for r in self.svc.recurring.list_all()], ["RC-000001", "RC-000002"])
        # 다음 id 는 남은 최대 번호 + 1 이므로 삭제된 RC-000003 이 재발급된다 (TX 와 같은 규칙, D05·D44 의 문서화된 한계)
        self.assertEqual(self.svc.recurring.add(day=5, type_="expense", category="food", amount=1).id, "RC-000003")
        self.assertEqual(sorted(p.name for p in self.data_dir.iterdir() if p.suffix == ".tmp"), [])


if __name__ == "__main__":
    unittest.main()
