"""CLI 계층: argparse 트리, 대화형 프롬프트(input_fn 주입), 출력 (AGENT.md 7장, D02, D23, D27, D30~D32, D36, D37).

이 모듈은 파일을 직접 열지 않고 서비스만 호출한다. 검증 로직은 models/services 에 있고, 여기서는 호출만 한다.
"""
from __future__ import annotations

import argparse
import functools
import logging
import sys
from pathlib import Path
from typing import Callable, TypeVar

from .errors import EXIT_OK, NotFoundError, ValidationError
from .models import parse_amount, parse_date, parse_memo, parse_tags, parse_type
from .formatting import (
    format_budget_row,
    format_category_row,
    format_transaction_row,
    format_won,
)
from .services import Services, build_services

PROG = "python -m budget_app"
DEFAULT_DATA_DIR = "./data"
DEFAULT_LIST_LIMIT = 20
DEFAULT_SUMMARY_TOP = 5

InputFn = Callable[[str], str]
Handler = Callable[[argparse.Namespace, Services, InputFn], int]
T = TypeVar("T")


# ---------------------------------------------------------------------------
# 환경 설정 (D30, --verbose)
# ---------------------------------------------------------------------------


def configure_console() -> None:
    """Windows cp949 콘솔 대비. 표준 스트림을 UTF-8 로 재설정하고 실패는 무시한다 (D30)."""
    for stream_name in ("stdout", "stderr", "stdin"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass


def configure_logging(verbose: bool) -> None:
    """--verbose 면 DEBUG 로그를 stderr 로 낸다 (log_call / timed 출력)."""
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, stream=sys.stderr, format="[%(levelname)s] %(message)s", force=True)


# ---------------------------------------------------------------------------
# argparse 트리 (전 명령·전 옵션, 롱 옵션만)
# ---------------------------------------------------------------------------


def positive_int(text: str) -> int:
    """`--limit`, `--top` 전용 argparse 타입. 양의 정수가 아니면 사용법 오류(종료 2) (D32)."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"양의 정수여야 합니다 (입력: {text})") from None
    if value <= 0:
        raise argparse.ArgumentTypeError(f"양의 정수여야 합니다 (입력: {text})")
    return value


def _check_update(sub: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """update 는 수정 옵션이 최소 1개 필요하다 (D03). 없으면 종료 2."""
    fields = (args.date, args.type, args.category, args.amount, args.memo, args.tags)
    if all(value is None for value in fields):
        sub.error("수정할 옵션을 최소 하나 지정하세요: --date --type --category --amount --memo --tags")


def _check_export(sub: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """export 는 --month 또는 --from/--to 중 하나 이상이 필수다 (D20). 없으면 종료 2."""
    if args.month is None and args.date_from is None and args.date_to is None:
        sub.error("기간 조건이 필요합니다: --month YYYY-MM 또는 --from/--to YYYY-MM-DD")


def _add_help(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """argparse 기본 `-h` 대신 `--help` 만 둔다 (C4: 단축 옵션 금지)."""
    parser.add_argument("--help", action="help", help="이 도움말을 출력하고 종료")
    return parser


def _subparser(commands: argparse._SubParsersAction, name: str, help_text: str) -> argparse.ArgumentParser:  # type: ignore[type-arg]
    return _add_help(commands.add_parser(name, help=help_text, add_help=False))


def build_parser() -> argparse.ArgumentParser:
    """전역 옵션은 서브커맨드 앞에 둔다 (D23). 단축 옵션은 만들지 않는다 (C4)."""
    parser = _add_help(
        argparse.ArgumentParser(
            prog=PROG,
            description="나만의 용돈 기입장 — 파일 기반 콘솔 가계부 (JSONL 저장, 표준 라이브러리만 사용)",
            epilog="각 명령의 자세한 사용법: %(prog)s <command> --help",
            add_help=False,
        )
    )
    parser.add_argument(
        "--data-dir",
        default=DEFAULT_DATA_DIR,
        metavar="PATH",
        help=f"저장 폴더 (기본값: {DEFAULT_DATA_DIR}). 서브커맨드 앞에 둔다",
    )
    parser.add_argument("--verbose", action="store_true", help="DEBUG 로그(호출·실행 시간)를 stderr 로 출력")

    commands = parser.add_subparsers(dest="command", metavar="<command>", title="명령", required=True)

    _subparser(commands, "add", "거래 추가 (대화형: 날짜, 타입, 카테고리, 금액, 메모, 태그)")

    list_parser = _subparser(commands, "list", "최신순 거래 목록")
    list_parser.add_argument(
        "--limit", type=positive_int, default=DEFAULT_LIST_LIMIT, metavar="N",
        help=f"출력 건수 (기본값: {DEFAULT_LIST_LIMIT})",
    )

    search_parser = _subparser(commands, "search", "조건 검색 (모든 조건은 AND, 최신순)")
    search_parser.add_argument("--from", dest="date_from", metavar="YYYY-MM-DD", help="시작일 (포함)")
    search_parser.add_argument("--to", dest="date_to", metavar="YYYY-MM-DD", help="종료일 (포함)")
    search_parser.add_argument("--category", metavar="NAME", help="카테고리 정확 일치")
    search_parser.add_argument("--type", metavar="TYPE", help="income 또는 expense")
    search_parser.add_argument("--q", dest="query", metavar="TEXT", help="메모 부분 일치 (대소문자 무시)")
    search_parser.add_argument("--tag", metavar="TAG", help="태그 정확 일치")
    search_parser.add_argument("--limit", type=positive_int, default=None, metavar="N", help="최대 건수 (기본: 무제한)")

    summary_parser = _subparser(commands, "summary", "월별 요약: 총수입/총지출/잔액, 예산 사용률, 지출 TOP N")
    summary_parser.add_argument("--month", required=True, metavar="YYYY-MM", help="요약할 월")
    summary_parser.add_argument(
        "--top", type=positive_int, default=DEFAULT_SUMMARY_TOP, metavar="N",
        help=f"카테고리별 지출 상위 건수 (기본값: {DEFAULT_SUMMARY_TOP})",
    )

    budget_parser = _subparser(commands, "budget", "월 예산 설정/조회")
    budget_commands = budget_parser.add_subparsers(dest="budget_command", metavar="<subcommand>", required=True)
    budget_set = _subparser(budget_commands, "set", "월 예산 저장 (같은 달은 덮어쓰기)")
    budget_set.add_argument("--month", required=True, metavar="YYYY-MM", help="대상 월")
    budget_set.add_argument("--amount", required=True, metavar="AMOUNT", help="예산 금액 (양의 정수)")
    _subparser(budget_commands, "list", "예산 목록 (월 오름차순)")

    category_parser = _subparser(commands, "category", "카테고리 관리")
    category_commands = category_parser.add_subparsers(
        dest="category_command", metavar="<subcommand>", required=True
    )
    category_add = _subparser(category_commands, "add", "카테고리 추가 (이름을 생략하면 대화형)")
    category_add.add_argument("name", nargs="?", default=None, metavar="NAME", help="카테고리 이름")
    _subparser(category_commands, "list", "카테고리 목록 (이름 오름차순)")
    category_remove = _subparser(category_commands, "remove", "카테고리 삭제 (사용 중이면 차단)")
    category_remove.add_argument("--name", required=True, metavar="NAME", help="삭제할 카테고리")
    category_remove.add_argument(
        "--replace", default=None, metavar="NAME", help="사용 중인 거래를 이 카테고리로 옮긴 뒤 삭제"
    )

    update_parser = _subparser(commands, "update", "거래 수정 (옵션 기반, 최소 1개 옵션 필요)")
    update_parser.add_argument("--id", dest="tx_id", required=True, metavar="ID", help="수정할 거래 id (예: TX-000012)")
    update_parser.add_argument("--date", metavar="YYYY-MM-DD", help="날짜")
    update_parser.add_argument("--type", metavar="TYPE", help="income 또는 expense")
    update_parser.add_argument("--category", metavar="NAME", help="등록된 카테고리")
    update_parser.add_argument("--amount", metavar="AMOUNT", help="양의 정수")
    update_parser.add_argument("--memo", metavar="TEXT", help="메모")
    update_parser.add_argument("--tags", metavar="A,B", help='쉼표 구분 태그. "" 로 비울 수 있다')
    update_parser.set_defaults(check=functools.partial(_check_update, update_parser))

    delete_parser = _subparser(commands, "delete", "거래 삭제")
    delete_parser.add_argument("--id", dest="tx_id", required=True, metavar="ID", help="삭제할 거래 id")

    import_parser = _subparser(commands, "import", "CSV 에서 거래 일괄 등록")
    import_parser.add_argument("--from", dest="source", required=True, metavar="CSV", help="가져올 CSV 파일 경로")

    export_parser = _subparser(commands, "export", "조건에 맞는 거래를 CSV 로 내보내기 (기간 조건 필수)")
    export_parser.add_argument("--out", required=True, metavar="CSV", help="내보낼 CSV 파일 경로")
    export_parser.add_argument("--month", metavar="YYYY-MM", help="대상 월")
    export_parser.add_argument("--from", dest="date_from", metavar="YYYY-MM-DD", help="시작일 (포함)")
    export_parser.add_argument("--to", dest="date_to", metavar="YYYY-MM-DD", help="종료일 (포함)")
    export_parser.set_defaults(check=functools.partial(_check_export, export_parser))

    _subparser(commands, "backup", "타임스탬프 폴더에 저장 파일 3개를 백업")

    return parser


# ---------------------------------------------------------------------------
# 명령 핸들러 (서비스 호출 + 출력)
# ---------------------------------------------------------------------------


def ask(input_fn: InputFn, prompt: str, parse: Callable[[str], T]) -> T:
    """검증을 통과할 때까지 같은 항목을 다시 묻는다 (D13, D37). 오류 두 줄은 프롬프트와 같은 stdout 에 쓴다."""
    while True:
        raw = input_fn(prompt)
        try:
            return parse(raw)
        except (ValidationError, NotFoundError) as err:
            for line in err.format_lines():
                print(line)


def cmd_add(args: argparse.Namespace, svc: Services, input_fn: InputFn) -> int:
    """대화형 6항목 → 저장 → id 출력. 중단(Ctrl+C/EOF)은 handle_errors 가 130 으로 바꾼다."""
    date = ask(input_fn, "날짜(YYYY-MM-DD): ", parse_date)
    type_ = ask(input_fn, "타입(income/expense): ", parse_type)
    category = ask(input_fn, "카테고리: ", svc.categories.require)
    amount = ask(input_fn, "금액(양수 정수): ", parse_amount)
    memo = ask(input_fn, "메모(선택): ", parse_memo)
    tags = ask(input_fn, "태그(쉼표로 구분, 없으면 엔터): ", parse_tags)
    tx = svc.transactions.add(date=date, type_=type_, category=category, amount=amount, memo=memo, tags=tags)
    print(f"[저장 완료] id={tx.id}")
    return EXIT_OK


def cmd_list(args: argparse.Namespace, svc: Services, input_fn: InputFn) -> int:
    rows = svc.transactions.list_recent(args.limit)
    if not rows:
        print("[안내] 거래가 없습니다")
        return EXIT_OK
    for tx in rows:
        print(format_transaction_row(tx))
    return EXIT_OK


def cmd_search(args: argparse.Namespace, svc: Services, input_fn: InputFn) -> int:
    rows = svc.transactions.search(
        date_from=args.date_from,
        date_to=args.date_to,
        category=args.category,
        type_=args.type,
        query=args.query,
        tag=args.tag,
        limit=args.limit,
    )
    if not rows:
        print("[안내] 조건에 맞는 거래가 없습니다")
        return EXIT_OK
    for tx in rows:
        print(format_transaction_row(tx))
    return EXIT_OK


def cmd_summary(args: argparse.Namespace, svc: Services, input_fn: InputFn) -> int:
    result = svc.budgets.summary(args.month, args.top)
    if result.count == 0:
        print(f"[안내] {result.month} 데이터 없음")
        if result.budget is not None:
            print(f"예산: {format_won(result.budget.amount)} (사용률 0.0%)")
        return EXIT_OK
    print(f"총 수입: {format_won(result.income)}")
    print(f"총 지출: {format_won(result.expense)}")
    print(f"잔액: {format_won(result.balance)}")
    if result.budget is not None:
        usage = result.expense / result.budget.amount * 100
        print(f"예산: {format_won(result.budget.amount)} (사용률 {usage:.1f}%)")
        if result.expense > result.budget.amount:
            print(f"[경고] 예산 초과: +{format_won(result.expense - result.budget.amount)}")
    print()
    print(f"지출 TOP {args.top}")
    for rank, (name, total) in enumerate(result.top_expenses, start=1):
        print(f"{rank}) {name} {format_won(total)}")
    return EXIT_OK


def cmd_budget_set(args: argparse.Namespace, svc: Services, input_fn: InputFn) -> int:
    budget = svc.budgets.set_budget(args.month, args.amount)
    print(f"[저장 완료] {budget.month} 예산 {format_won(budget.amount)}")
    return EXIT_OK


def cmd_budget_list(args: argparse.Namespace, svc: Services, input_fn: InputFn) -> int:
    budgets = svc.budgets.list_all()
    if not budgets:
        print("[안내] 설정된 예산이 없습니다")
        return EXIT_OK
    for budget in budgets:
        print(format_budget_row(budget))
    return EXIT_OK


def cmd_category_add(args: argparse.Namespace, svc: Services, input_fn: InputFn) -> int:
    name = args.name if args.name is not None else input_fn("카테고리명: ")
    created = svc.categories.add(name)
    print(f"[저장 완료] category={created}")
    return EXIT_OK


def cmd_category_list(args: argparse.Namespace, svc: Services, input_fn: InputFn) -> int:
    for name in svc.categories.list_names():
        print(format_category_row(name))
    return EXIT_OK


def cmd_category_remove(args: argparse.Namespace, svc: Services, input_fn: InputFn) -> int:
    moved = svc.categories.remove(args.name, replace=args.replace)
    if moved:
        print(f"[완료] 거래 {moved}건을 '{args.replace}'로 이동하고 category={args.name} 를 삭제했습니다.")
    else:
        print(f"[삭제 완료] category={args.name}")
    return EXIT_OK


def cmd_update(args: argparse.Namespace, svc: Services, input_fn: InputFn) -> int:
    tx = svc.transactions.update(
        args.tx_id,
        date=args.date,
        type_=args.type,
        category=args.category,
        amount=args.amount,
        memo=args.memo,
        tags=args.tags,
    )
    print(f"[수정 완료] id={tx.id}")
    return EXIT_OK


def cmd_delete(args: argparse.Namespace, svc: Services, input_fn: InputFn) -> int:
    tx = svc.transactions.delete(args.tx_id)
    print(f"[삭제 완료] id={tx.id}")
    return EXIT_OK


def cmd_import(args: argparse.Namespace, svc: Services, input_fn: InputFn) -> int:
    result = svc.transactions.import_csv(Path(args.source))
    print(f"[완료] imported={result.imported}, skipped={len(result.skipped)}")
    for line_no, reason in result.skipped:
        print(f"  - {line_no}행: {reason}")
    return EXIT_OK


def cmd_export(args: argparse.Namespace, svc: Services, input_fn: InputFn) -> int:
    count = svc.transactions.export_csv(
        Path(args.out), month=args.month, date_from=args.date_from, date_to=args.date_to
    )
    print(f"[완료] {args.out} ({count} records)")
    return EXIT_OK


def cmd_backup(args: argparse.Namespace, svc: Services, input_fn: InputFn) -> int:
    target = svc.backup()
    print(f"[완료] {target} (3 files)")
    return EXIT_OK


HANDLERS: dict[str, Handler] = {
    "add": cmd_add,
    "list": cmd_list,
    "search": cmd_search,
    "summary": cmd_summary,
    "budget set": cmd_budget_set,
    "budget list": cmd_budget_list,
    "category add": cmd_category_add,
    "category list": cmd_category_list,
    "category remove": cmd_category_remove,
    "update": cmd_update,
    "delete": cmd_delete,
    "import": cmd_import,
    "export": cmd_export,
    "backup": cmd_backup,
}


def handler_key(args: argparse.Namespace) -> str:
    """`budget set`, `category add` 처럼 중첩 명령은 공백으로 이어 붙인 키를 쓴다."""
    if args.command == "budget":
        return f"budget {args.budget_command}"
    if args.command == "category":
        return f"category {args.category_command}"
    return str(args.command)


def dispatch(args: argparse.Namespace, svc: Services, input_fn: InputFn) -> int:
    return HANDLERS[handler_key(args)](args, svc, input_fn)


def main(argv: list[str] | None = None, input_fn: InputFn = input) -> int:
    """인자 해석 → 로깅 설정 → 서비스 조립 → 명령 실행. 오류 변환은 __main__.entry 의 handle_errors 가 맡는다."""
    configure_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    check = getattr(args, "check", None)
    if check is not None:
        check(args)
    configure_logging(args.verbose)
    svc = build_services(Path(args.data_dir))
    if svc.initialized:
        print(f"[안내] 저장 폴더를 초기화했습니다: {args.data_dir}")  # D23, D36
    return dispatch(args, svc, input_fn)
