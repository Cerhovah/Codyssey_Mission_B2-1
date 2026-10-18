"""데이터 모델과 단일 필드 검증 (AGENT.md 6장, D05, D08~D12).

이 모듈은 파일을 열지 않고, 카테고리 존재 여부처럼 저장소가 필요한 검사는 하지 않는다.
모든 검증 함수는 실패 시 ValidationError를 던지고, 성공 시 정규화된 값을 돌려준다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .errors import ValidationError

TYPE_INCOME = "income"
TYPE_EXPENSE = "expense"
TRANSACTION_TYPES: tuple[str, ...] = (TYPE_INCOME, TYPE_EXPENSE)

TRANSACTION_ID_PREFIX = "TX-"
TRANSACTION_ID_WIDTH = 6
RECURRING_ID_PREFIX = "RC-"  # D44

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_AMOUNT_RE = re.compile(r"^[0-9]+$")
_TRANSACTION_ID_RE = re.compile(r"^TX-(\d{6,})$")
_RECURRING_ID_RE = re.compile(r"^RC-(\d{6,})$")

DATE_HINT = "예: 2024-01-15"
MONTH_HINT = "예: 2024-01"
AMOUNT_HINT = "예: 15000 (소수점·쉼표·부호 없이 양의 정수)"
TYPE_HINT = "income 또는 expense 중 하나를 입력하세요"
DAY_HINT = "1~31 사이의 정수 (그 달에 없는 날은 말일로 보정됩니다)"


# ---------------------------------------------------------------------------
# 단일 필드 검증
# ---------------------------------------------------------------------------


def parse_date(value: str) -> str:
    """`YYYY-MM-DD` 형식의 실제 존재하는 날짜만 허용한다 (D09). `2024-1-5` 는 거부한다."""
    text = value.strip()
    if not _DATE_RE.match(text):
        raise ValidationError("날짜 형식이 올바르지 않습니다 (YYYY-MM-DD).", hint=DATE_HINT)
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        raise ValidationError(f"존재하지 않는 날짜입니다: {text}", hint=DATE_HINT) from None
    return text


def parse_month(value: str) -> str:
    """`YYYY-MM` 형식의 월만 허용한다 (summary/budget 공용)."""
    text = value.strip()
    if not _MONTH_RE.match(text):
        raise ValidationError("월 형식이 올바르지 않습니다 (YYYY-MM).", hint=MONTH_HINT)
    try:
        datetime.strptime(text, "%Y-%m")
    except ValueError:
        raise ValidationError(f"존재하지 않는 월입니다: {text}", hint=MONTH_HINT) from None
    return text


def parse_amount(value: str | int) -> int:
    """양의 정수만 허용한다 (D08). 소수·쉼표·`+` 기호·공백 섞인 값은 거부한다."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValidationError("금액은 양의 정수여야 합니다", hint=AMOUNT_HINT)
    if isinstance(value, int):
        number = value
        shown = str(value)
    else:
        shown = value.strip()
        if not _AMOUNT_RE.match(shown):
            raise ValidationError(f"금액은 양의 정수여야 합니다 (입력: {shown})", hint=AMOUNT_HINT)
        number = int(shown)
    if number <= 0:
        raise ValidationError(f"금액은 양의 정수여야 합니다 (입력: {shown})", hint=AMOUNT_HINT)
    return number


def parse_type(value: str) -> str:
    """income / expense 만 허용한다. 앞뒤 공백 제거와 소문자 변환 후 비교한다 (D10)."""
    text = value.strip().lower()
    if text not in TRANSACTION_TYPES:
        raise ValidationError(
            f"타입은 income 또는 expense 여야 합니다 (입력: {value.strip()})", hint=TYPE_HINT
        )
    return text


def parse_tags(value: str | list[str] | None) -> list[str]:
    """쉼표 분리 → strip → 빈 값 제거 → 순서 유지 중복 제거 (D11). 리스트 입력도 같은 규칙을 적용한다."""
    if value is None:
        return []
    if isinstance(value, str):
        parts: list[object] = value.split(",")
    elif isinstance(value, list):
        parts = list(value)
    else:
        raise ValidationError("태그는 쉼표로 구분한 문자열이어야 합니다", hint="예: meal,daily")
    result: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if not isinstance(part, str):
            raise ValidationError("태그는 문자열이어야 합니다", hint="예: meal,daily")
        tag = part.strip()
        if tag and tag not in seen:
            seen.add(tag)
            result.append(tag)
    return result


def parse_category_name(value: str) -> str:
    """카테고리 이름: strip 후 빈 문자열 금지, 대소문자 구분 (D12)."""
    if not isinstance(value, str):
        raise ValidationError("카테고리 이름은 문자열이어야 합니다", hint="예: food")
    text = value.strip()
    if not text:
        raise ValidationError("카테고리 이름이 비어 있습니다", hint="예: food")
    return text


def parse_memo(value: str | None) -> str:
    """메모는 선택 항목. None 은 빈 문자열로, 앞뒤 공백은 제거한다."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValidationError("메모는 문자열이어야 합니다")
    return value.strip()


def format_transaction_id(number: int) -> str:
    """`TX-` + 6자리 0패딩. 999999 를 넘으면 자리수가 자연히 늘어난다 (D05)."""
    if number <= 0:
        raise ValidationError(f"거래 번호는 1 이상이어야 합니다 (입력: {number})")
    return f"{TRANSACTION_ID_PREFIX}{number:0{TRANSACTION_ID_WIDTH}d}"


def transaction_number(tx_id: str) -> int:
    """`TX-000012` → 12. 형식이 다르면 ValidationError."""
    match = _TRANSACTION_ID_RE.match(tx_id.strip()) if isinstance(tx_id, str) else None
    if match is None:
        raise ValidationError(f"거래 id 형식이 올바르지 않습니다 (입력: {tx_id})", hint="예: TX-000012")
    return int(match.group(1))


def parse_day(value: str | int) -> int:
    """반복 내역의 매월 일: 1~31 정수 (D44). 그 달에 없는 날은 apply 시 말일로 보정한다."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValidationError("매월 일은 1~31 사이의 정수여야 합니다", hint=DAY_HINT)
    if isinstance(value, int):
        number = value
        shown = str(value)
    else:
        shown = value.strip()
        if not _AMOUNT_RE.match(shown):
            raise ValidationError(f"매월 일은 1~31 사이의 정수여야 합니다 (입력: {shown})", hint=DAY_HINT)
        number = int(shown)
    if not 1 <= number <= 31:
        raise ValidationError(f"매월 일은 1~31 사이의 정수여야 합니다 (입력: {shown})", hint=DAY_HINT)
    return number


def format_recurring_id(number: int) -> str:
    """`RC-` + 6자리 0패딩 (D44). 규칙은 TX 와 같다."""
    if number <= 0:
        raise ValidationError(f"반복 내역 번호는 1 이상이어야 합니다 (입력: {number})")
    return f"{RECURRING_ID_PREFIX}{number:0{TRANSACTION_ID_WIDTH}d}"


def recurring_number(rule_id: str) -> int:
    """`RC-000001` → 1. 형식이 다르면 ValidationError."""
    match = _RECURRING_ID_RE.match(rule_id.strip()) if isinstance(rule_id, str) else None
    if match is None:
        raise ValidationError(f"반복 내역 id 형식이 올바르지 않습니다 (입력: {rule_id})", hint="예: RC-000001")
    return int(match.group(1))


# ---------------------------------------------------------------------------
# dataclass 와 직렬화
# ---------------------------------------------------------------------------


def _require_mapping(data: object, what: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValidationError(f"{what} 레코드는 JSON 객체여야 합니다")
    return data


def _require_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ValidationError(f"필수 항목 '{key}'이(가) 없거나 문자열이 아닙니다")
    return value


def _require_int(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"필수 항목 '{key}'이(가) 없거나 정수가 아닙니다")
    return value


@dataclass(slots=True)
class Transaction:
    """거래 1건. 모든 필드는 검증이 끝난 값으로 보관한다."""

    id: str
    type: str
    date: str
    amount: int
    category: str
    memo: str = ""
    tags: list[str] = field(default_factory=list)

    def sort_key(self) -> tuple[str, str]:
        """최신순 정렬 키 `(date, id)` (D06). 내림차순으로 쓴다."""
        return (self.date, self.id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "date": self.date,
            "amount": self.amount,
            "category": self.category,
            "memo": self.memo,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Transaction:
        """JSON 객체 → Transaction. 알 수 없는 키는 무시하고, 필수 키 누락·타입 불일치는 ValidationError."""
        record = _require_mapping(data, "거래")
        tx_id = _require_str(record, "id").strip()
        if not tx_id:
            raise ValidationError("필수 항목 'id'이(가) 비어 있습니다")
        return cls(
            id=tx_id,
            type=parse_type(_require_str(record, "type")),
            date=parse_date(_require_str(record, "date")),
            amount=parse_amount(_require_int(record, "amount")),
            category=parse_category_name(_require_str(record, "category")),
            memo=parse_memo(record.get("memo", "")),
            tags=parse_tags(record.get("tags", [])),
        )


@dataclass(slots=True)
class Category:
    """카테고리. 이름 하나만 가진다 (D12)."""

    name: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Category:
        record = _require_mapping(data, "카테고리")
        return cls(name=parse_category_name(_require_str(record, "name")))


@dataclass(slots=True)
class Budget:
    """월 예산 (D25)."""

    month: str
    amount: int

    def to_dict(self) -> dict[str, Any]:
        return {"month": self.month, "amount": self.amount}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Budget:
        record = _require_mapping(data, "예산")
        return cls(
            month=parse_month(_require_str(record, "month")),
            amount=parse_amount(_require_int(record, "amount")),
        )


@dataclass(slots=True)
class RecurringRule:
    """반복 내역 규칙: 매월 `day` 일에 생성할 거래의 틀 (보너스 B2, D44)."""

    id: str
    day: int
    type: str
    amount: int
    category: str
    memo: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "day": self.day,
            "type": self.type,
            "category": self.category,
            "amount": self.amount,
            "memo": self.memo,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RecurringRule:
        record = _require_mapping(data, "반복 내역")
        rule_id = _require_str(record, "id").strip()
        if not rule_id:
            raise ValidationError("필수 항목 'id'이(가) 비어 있습니다")
        return cls(
            id=rule_id,
            day=parse_day(_require_int(record, "day")),
            type=parse_type(_require_str(record, "type")),
            amount=parse_amount(_require_int(record, "amount")),
            category=parse_category_name(_require_str(record, "category")),
            memo=parse_memo(record.get("memo", "")),
            tags=parse_tags(record.get("tags", [])),
        )
