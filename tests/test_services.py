"""services 계층 테스트: 카테고리 관리, 거래 추가, 최신순 목록을 시나리오 단위로 확인한다 (AGENT.md 9장 P3, 10장)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from budget_app.errors import ConflictError, NotFoundError, ValidationError
from budget_app.repository import CATEGORIES_FILE, DEFAULT_CATEGORIES, JsonlStore
from budget_app.services import Services, build_services


class ServicesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="budget_app_svc_")
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name) / "data"
        self.svc: Services = build_services(self.data_dir)

    def add(self, date: str, type_: str = "expense", category: str = "food", amount: int = 1000) -> str:
        return self.svc.transactions.add(date=date, type_=type_, category=category, amount=amount).id


class BuildAndCategoryScenario(ServicesTestCase):
    """build_services 가 초기화하고(D36), CategoryService 는 정렬·정규화·중복 오류를 지킨다 (D12, D26, D35)."""

    def test_initialization_and_category_management(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
