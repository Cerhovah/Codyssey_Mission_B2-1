from __future__ import annotations

"""짧은 명령과 질문을 기존 CLI로 연결하는 간편 모드(D45)."""

import argparse
import shlex
import sys
from datetime import date
from pathlib import Path

from . import cli
from .decorators import handle_errors
from .errors import EXIT_INTERRUPT, EXIT_OK, ValidationError
from .models import parse_amount, parse_month
from .services import Services, build_services


HELP = """간편 가계부 — 할 일만 입력하고 질문에 답하세요.
  add       수입·지출 기록       list      최근 거래
  search    메모 검색           summary   월별 요약
  budget    예산 조회·설정      category  분류 관리
  update    거래 수정           delete    거래 삭제
  import    CSV 가져오기        export    CSV 내보내기
  backup    백업                recurring 반복 규칙 관리
  help      도움말              exit      종료

예: add → 질문에 답하기 → list → summary
자세한 안내: help add 또는 add --help
옵션도 사용 가능: list --limit 3
Ctrl+C: 현재 작업 취소 / 도움말: help 또는 도움말 / 종료: exit 또는 종료"""

GROUPS = {
    "budget": (("list", "예산 조회"), ("set", "예산 설정")),
    "category": (("list", "분류 조회"), ("add", "분류 추가"), ("remove", "분류 삭제")),
    "recurring": (("list", "규칙 조회"), ("add", "규칙 추가"), ("apply", "월별 적용"), ("remove", "규칙 삭제")),
}
FIELDS = (("amount", "금액"), ("memo", "메모"), ("date", "날짜"),
          ("type", "수입·지출"), ("category", "카테고리"), ("tags", "태그"))


class Prompts:
    """입력 종료를 기억하고, 간편 모드의 기본값과 선택 질문을 제공한다."""

    def __init__(self, input_fn: cli.InputFn) -> None:
        self.input_fn = input_fn
        self.ended = False

    def read(self, prompt: str) -> str:
        """데이터 입력 중 EOF를 명령 취소와 구분한다."""
        try:
            return self.input_fn(prompt)
        except EOFError:
            self.ended = True
            raise

    def required(self, prompt: str) -> str:
        """필수 문자열을 받되 앞뒤 공백을 정리한다."""
        return cli.ask(self.read, prompt, nonempty)

    def month(self) -> str:
        """엔터를 누르면 이번 달을 사용한다."""
        current = date.today().strftime("%Y-%m")

        def parse(value: str) -> str:
            return parse_month(value.strip() or current)

        return cli.ask(self.read, f"대상 월 [엔터: {current}]: ", parse)

    def choose(self, choices: tuple[tuple[str, str], ...]) -> str:
        """번호 또는 명령 이름을 받아 선택한다. 기본값은 첫 번째 항목이다."""
        for number, (name, label) in enumerate(choices, start=1):
            print(f"  {number}. {label} ({name})")

        def parse(value: str) -> str:
            value = value.strip().lower() or choices[0][0]
            for number, (name, _) in enumerate(choices, start=1):
                if value in (str(number), name):
                    return name
            raise ValidationError("목록에 있는 번호나 명령을 입력하세요.", hint=f"1~{len(choices)} 또는 {', '.join(name for name, _ in choices)}")

        return cli.ask(self.read, "선택 [엔터: 1]: ", parse)

    def transaction_input(self, svc: Services, prompt: str) -> str:
        """기존 거래 질문을 오늘 날짜·한글 종류·카테고리 선택으로 돕는다."""
        if prompt == "날짜(YYYY-MM-DD): ":
            return self.read("날짜 [엔터: 오늘]: ").strip() or date.today().isoformat()
        if prompt == "타입(income/expense): ":
            value = self.read("종류 [1: 지출, 2: 수입 / 엔터: 지출]: ").strip().lower()
            return {"": "expense", "1": "expense", "지출": "expense",
                    "2": "income", "수입": "income"}.get(value, value)
        if prompt == "카테고리: ":
            names = svc.categories.list_names()
            print("카테고리: " + ", ".join(f"{i}: {name}" for i, name in enumerate(names, start=1)))
            default = "etc" if "etc" in names else ""
            suffix = " / 엔터: etc" if default else ""
            value = self.read(f"카테고리 [번호 또는 이름{suffix}]: ").strip() or default
            # 숫자로 된 카테고리 이름이 있으면 그 이름을 우선한다.
            if value not in names:
                for number, name in enumerate(names, start=1):
                    if value == str(number):
                        return name
            return value
        return self.read(prompt)


def nonempty(value: str) -> str:
    """빈 필수 입력에 해결 방법을 안내한다."""
    if not value.strip():
        raise ValidationError("값을 입력하세요.", hint="질문에 표시된 값이나 경로를 입력하세요. Ctrl+C로 취소할 수 있습니다.")
    return value.strip()


def complete_command(words: list[str], prompts: Prompts) -> list[str]:
    """옵션 없는 짧은 명령에 필요한 값만 질문해 기존 명령으로 바꾼다."""
    if len(words) == 1 and words[0] in GROUPS:
        words = [words[0], prompts.choose(GROUPS[words[0]])]
    match words:
        case ["search"]:
            return [*words, "--q=" + prompts.read("메모 검색어 [전체 조회는 엔터]: ")]
        case ["summary"] | ["recurring", "apply"]:
            return [*words, "--month=" + prompts.month()]
        case ["budget", "set"]:
            month = prompts.month()
            amount = cli.ask(prompts.read, "예산 금액(양수 정수): ", parse_amount)
            return [*words, f"--month={month}", f"--amount={amount}"]
        case ["delete"] | ["recurring", "remove"]:
            label = "거래 번호 (예: TX-000001): " if words[0] == "delete" else "규칙 번호 (예: RC-000001): "
            return [*words, "--id=" + prompts.required(label)]
        case ["update"]:
            tx_id = prompts.required("수정할 거래 번호 (예: TX-000001): ")
            field = prompts.choose(FIELDS)
            value = prompts.read("새 값 [메모·태그는 엔터로 비움]: ")
            return [*words, f"--id={tx_id}", f"--{field}={value}"]
        case ["category", "remove"]:
            name = prompts.required("삭제할 카테고리 이름: ")
            replacement = prompts.read("대체 카테고리 [사용한 거래가 없으면 엔터]: ").strip()
            return [*words, f"--name={name}", *([f"--replace={replacement}"] if replacement else [])]
        case ["import"]:
            return [*words, "--from=" + prompts.required("가져올 CSV 경로: ")]
        case ["export"]:
            output = prompts.required("내보낼 CSV 경로: ")
            return [*words, f"--out={output}", "--month=" + prompts.month()]
        case _:
            return words


@handle_errors
def execute(words: list[str], options: argparse.Namespace, prompts: Prompts) -> int:
    """질문과 기존 파서·검증·서비스·핸들러를 연결한다. 파일을 직접 다루지 않는다."""
    # 도움말은 질문이나 저장 폴더 초기화보다 먼저 처리한다.
    if words[0] in ("help", "도움말"):
        words = [*words[1:], "--help"] if len(words) > 1 else ["--help"]
    if words == ["--help"]:
        print(HELP)
        print("\n실행: python budget.py [--data-dir 폴더] [--verbose] [명령]")
        return EXIT_OK
    if "--help" not in words:
        words = complete_command(words, prompts)
    parser = cli.build_parser()
    prefix = [f"--data-dir={options.data_dir}"]
    if options.verbose:
        prefix.append("--verbose")
    args = parser.parse_args([*prefix, *words])
    check = getattr(args, "check", None)
    if check is not None:
        check(args)
    cli.configure_logging(args.verbose)
    svc = build_services(Path(args.data_dir))
    if svc.initialized:
        print(f"[안내] 저장 폴더를 초기화했습니다: {args.data_dir}")

    def input_fn(prompt: str) -> str:
        return prompts.transaction_input(svc, prompt)

    return cli.dispatch(args, svc, input_fn)


def run_command(words: list[str], options: argparse.Namespace, prompts: Prompts) -> int:
    """argparse의 도움말·사용법 종료를 셸 안에서 처리한다."""
    try:
        return execute(words, options, prompts)
    except SystemExit as exc:
        return int(exc.code or 0)


def shell(options: argparse.Namespace, prompts: Prompts) -> int:
    """명령을 반복해서 받고, 오류가 생겨도 다음 명령을 기다린다."""
    print(HELP)
    print(f"\n저장 폴더: {options.data_dir}")
    while True:
        try:
            raw = prompts.input_fn("가계부> ")
            lexer = shlex.shlex(raw, posix=True)
            lexer.whitespace_split = True
            lexer.commenters = ""
            lexer.escape = ""
            words = list(lexer)
        except EOFError:
            print("\n[안내] 가계부를 종료합니다.")
            return EXIT_OK
        except KeyboardInterrupt:
            print("\n[안내] 현재 작업을 취소했습니다. 종료하려면 exit를 입력하세요.")
            continue
        except ValueError:
            print("[오류] 따옴표가 닫히지 않았습니다.", file=sys.stderr)
            print("[힌트] 경로·메모를 감싼 따옴표를 확인하세요.", file=sys.stderr)
            continue
        if not words:
            continue
        if words in (["exit"], ["종료"]):
            print("[안내] 가계부를 종료합니다.")
            return EXIT_OK
        code = run_command(words, options, prompts)
        if prompts.ended:
            return EXIT_INTERRUPT
        if code != EXIT_OK:
            print("[안내] 작업을 마치지 못했습니다. help로 사용법을 보거나 다음 명령을 입력하세요.")


@handle_errors
def main(argv: list[str] | None = None, input_fn: cli.InputFn = input) -> int:
    """실행 옵션을 한 번 정하고 단일 명령 또는 대화형 모드로 들어간다."""
    cli.configure_console()
    parser = argparse.ArgumentParser(prog="python budget.py", add_help=False, allow_abbrev=False)
    parser.add_argument("--data-dir", default=cli.DEFAULT_DATA_DIR)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--help", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    options = parser.parse_args(argv)
    prompts = Prompts(input_fn)
    if options.help:
        return run_command(["--help"], options, prompts)
    if options.command:
        if options.command in (["exit"], ["종료"]):
            return EXIT_OK
        return run_command(options.command, options, prompts)
    return shell(options, prompts)


if __name__ == "__main__":
    sys.exit(main())
