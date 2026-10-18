"""models 계층 테스트: 검증 함수와 직렬화를 시나리오 단위로 확인한다 (AGENT.md 10장)."""
from __future__ import annotations

import unittest
from typing import Any, Callable

from budget_app.errors import AppError, ValidationError
from budget_app.models import (
    Budget,
    Category,
    Transaction,
    format_transaction_id,
    parse_amount,
    parse_category_name,
    parse_date,
    parse_month,
    parse_tags,
    parse_type,
    transaction_number,
)


class FieldValidationScenarios(unittest.TestCase):
    """D08~D12 검증 규칙: 허용 값은 정규화되어 돌아오고, 거부 값은 ValidationError 다."""

    def assert_rejected(self, func: Callable[[Any], object], values: list[Any]) -> None:
        for value in values:
            with self.subTest(value=value):
                with self.assertRaises(ValidationError) as ctx:
                    func(value)
                self.assertIsInstance(ctx.exception, AppError)
                self.assertEqual(ctx.exception.exit_code, 1)
                self.assertTrue(ctx.exception.format_lines()[0].startswith("[오류] "))

    def test_date_scenarios(self) -> None:
        self.assertEqual(parse_date("2024-01-15"), "2024-01-15")
        self.assertEqual(parse_date("  2024-02-29 "), "2024-02-29")  # 윤년 + 공백 제거
        self.assert_rejected(
            parse_date, ["2024-13-40", "2024-1-5", "2023-02-29", "20240115", "2024/01/15", "", "오늘"]
        )

    def test_month_scenarios(self) -> None:
        self.assertEqual(parse_month("2024-01"), "2024-01")
        self.assert_rejected(parse_month, ["2024-13", "2024-1", "2024-01-15", "202401", ""])

    def test_amount_scenarios(self) -> None:
        self.assertEqual(parse_amount("15000"), 15000)
        self.assertEqual(parse_amount(" 3000000 "), 3000000)
        self.assertEqual(parse_amount(42), 42)
        self.assert_rejected(parse_amount, ["0", "-500", "15000.5", "1,000", "+5", "abc", "", 0, -1, True])

    def test_type_scenarios(self) -> None:
        self.assertEqual(parse_type("expense"), "expense")
        self.assertEqual(parse_type(" Income "), "income")  # strip + lower
        self.assert_rejected(parse_type, ["transfer", "", "in come"])

    def test_tags_scenarios(self) -> None:
        self.assertEqual(parse_tags("meal, daily ,meal,, "), ["meal", "daily"])  # strip·빈 값·중복 제거, 순서 유지
        self.assertEqual(parse_tags(""), [])
        self.assertEqual(parse_tags(None), [])
        self.assertEqual(parse_tags(["a", " b", "a"]), ["a", "b"])
        self.assert_rejected(parse_tags, [["a", 1], 123])

    def test_category_name_scenarios(self) -> None:
        self.assertEqual(parse_category_name(" food "), "food")
        self.assertEqual(parse_category_name("Food"), "Food")  # 대소문자 구분 (소문자로 바꾸지 않음)
        self.assert_rejected(parse_category_name, ["", "   "])

    def test_transaction_id_scenarios(self) -> None:
        self.assertEqual(format_transaction_id(12), "TX-000012")
        self.assertEqual(format_transaction_id(1234567), "TX-1234567")  # 999999 초과 시 자연 확장
        self.assertEqual(transaction_number("TX-000012"), 12)
        self.assertEqual(transaction_number("TX-1234567"), 1234567)
        self.assert_rejected(transaction_number, ["TX-12", "12", "tx-000012", ""])
        with self.assertRaises(ValidationError):
            format_transaction_id(0)


class SerializationScenarios(unittest.TestCase):
    """to_dict / from_dict 왕복과 손상 레코드 거부 (AGENT.md 6장)."""

    def test_transaction_roundtrip_and_defaults(self) -> None:
        tx = Transaction(
            id="TX-000012", type="expense", date="2024-01-15", amount=15000,
            category="food", memo="점심", tags=["meal"],
        )
        data = tx.to_dict()
        self.assertEqual(
            data,
            {
                "id": "TX-000012", "type": "expense", "date": "2024-01-15", "amount": 15000,
                "category": "food", "memo": "점심", "tags": ["meal"],
            },
        )
        self.assertEqual(Transaction.from_dict(data), tx)
        self.assertEqual(tx.sort_key(), ("2024-01-15", "TX-000012"))

        minimal = Transaction.from_dict(
            {"id": "TX-000001", "type": "Income", "date": "2024-01-14", "amount": 3000000,
             "category": "salary", "unknown_key": "무시"}
        )
        self.assertEqual(minimal.type, "income")
        self.assertEqual(minimal.memo, "")
        self.assertEqual(minimal.tags, [])

    def test_transaction_from_dict_rejects_broken_records(self) -> None:
        base = {"id": "TX-000001", "type": "expense", "date": "2024-01-15", "amount": 100, "category": "food"}
        broken: list[Any] = [
            {**base, "amount": "100"},          # 타입 불일치 (문자열)
            {**base, "amount": 0},
            {**base, "amount": True},
            {**base, "date": "2024-1-5"},
            {**base, "type": "transfer"},
            {**base, "tags": ["a", 1]},
            {k: v for k, v in base.items() if k != "id"},
            {**base, "id": ""},
            {**base, "category": " "},
            "not a dict",
        ]
        for record in broken:
            with self.subTest(record=record):
                with self.assertRaises(ValidationError):
                    Transaction.from_dict(record)
        # tags 가 문자열로 들어와도 D11 규칙으로 정규화한다
        self.assertEqual(Transaction.from_dict({**base, "tags": "meal, daily"}).tags, ["meal", "daily"])

    def test_category_and_budget_roundtrip(self) -> None:
        category = Category(name="food")
        self.assertEqual(Category.from_dict(category.to_dict()), category)
        with self.assertRaises(ValidationError):
            Category.from_dict({"name": ""})

        budget = Budget(month="2024-01", amount=500000)
        self.assertEqual(Budget.from_dict(budget.to_dict()), budget)
        for record in ({"month": "2024-1", "amount": 1}, {"month": "2024-01", "amount": -1}, {"month": "2024-01"}):
            with self.subTest(record=record):
                with self.assertRaises(ValidationError):
                    Budget.from_dict(record)


if __name__ == "__main__":
    unittest.main()
