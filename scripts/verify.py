"""단일 검증 게이트 (AGENT.md 9~10장, D24).

사용법: python scripts/verify.py [--phase N]

1. tests/ 의 unittest 전체를 실행한다.
2. 임시 --data-dir 로 실제 진입점(`python -m budget_app`)을 subprocess 로 호출하는 스모크 시나리오를
   Phase 번호 순으로 실행한다. 아직 구현되지 않은 Phase 의 스모크는 CURRENT_PHASE 로 건너뛴다.
표준 라이브러리만 사용하며, 모두 통과하면 종료 0, 하나라도 실패하면 종료 1.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
CURRENT_PHASE = 6  # 구현이 끝난 마지막 Phase. Phase 를 완료할 때마다 올린다.

SmokeFn = Callable[[Path], None]


class SmokeFailure(AssertionError):
    """스모크 시나리오 실패. 메시지에 재현 정보를 담는다."""


def run_cli(data_dir: Path, *argv: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    """실제 진입점을 호출하고 stdout/stderr/종료 코드를 돌려준다."""
    return subprocess.run(
        [sys.executable, "-m", "budget_app", "--data-dir", str(data_dir), *argv],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        input=input_text,
    )


def expect(condition: bool, message: str, proc: subprocess.CompletedProcess[str] | None = None) -> None:
    if condition:
        return
    detail = ""
    if proc is not None:
        detail = (
            f"\n  argv: {proc.args[5:]}\n  exit: {proc.returncode}"
            f"\n  stdout: {proc.stdout.strip()!r}\n  stderr: {proc.stderr.strip()!r}"
        )
    raise SmokeFailure(message + detail)


def stdout_lines(proc: subprocess.CompletedProcess[str]) -> list[str]:
    return [line for line in proc.stdout.splitlines() if line.strip()]


def cells(line: str) -> list[str]:
    """`id | date | type | category | amount | memo` 행을 열 단위로 나눈다. 공백 정렬(P7)에 영향받지 않게 strip 한다."""
    return [cell.strip() for cell in line.split("|")]


# ---------------------------------------------------------------------------
# Phase 1 — 골격과 계약: --help 전부 0, 사용법 오류 2 (서비스 조립 전에 끝나므로 저장 폴더를 만들지 않는다, D36)
# ---------------------------------------------------------------------------

HELP_TARGETS: list[list[str]] = [
    [],
    ["add"],
    ["list"],
    ["search"],
    ["summary"],
    ["budget"],
    ["budget", "set"],
    ["budget", "list"],
    ["category"],
    ["category", "add"],
    ["category", "list"],
    ["category", "remove"],
    ["update"],
    ["delete"],
    ["import"],
    ["export"],
    ["backup"],
]

USAGE_ERROR_TARGETS: list[list[str]] = [
    [],                                   # 명령 없음
    ["frobnicate"],                       # 알 수 없는 명령
    ["list", "--bogus"],                  # 알 수 없는 옵션
    ["list", "-l", "3"],                  # 단축 옵션 없음 (C4)
    ["-h"],                               # -h 도 없음, --help 만 (C4)
    ["list", "--limit", "abc"],           # 정수 아님
    ["list", "--limit", "0"],             # 양의 정수 아님 (D32)
    ["list", "--data-dir", "x"],          # 전역 옵션은 서브커맨드 앞 (D23)
    ["summary"],                          # 필수 옵션 누락
    ["budget"],                           # 하위 명령 없음
    ["category", "remove"],               # --name 누락
    ["update", "--id", "TX-000001"],      # 수정 옵션 없음 (D03)
    ["export", "--out", "x.csv"],         # 기간 조건 없음 (D20)
    ["import"],                           # --from 누락
]

# 아직 구현되지 않은 명령. Phase 가 끝날 때마다 구현된 명령을 여기서 빼고 해당 Phase 스모크로 옮긴다.
UNIMPLEMENTED_TARGETS: list[list[str]] = [
    ["backup"],
]


def smoke_phase1(data_dir: Path) -> None:
    for target in HELP_TARGETS:
        proc = run_cli(data_dir, *target, "--help")
        expect(proc.returncode == 0, "--help 는 종료 0 이어야 합니다", proc)
        expect("usage" in proc.stdout.lower(), "--help 출력에 usage 가 있어야 합니다", proc)
        expect("Traceback" not in proc.stderr, "스택트레이스가 출력되면 안 됩니다", proc)

    for target in USAGE_ERROR_TARGETS:
        proc = run_cli(data_dir, *target)
        expect(proc.returncode == 2, "사용법 오류는 종료 2 이어야 합니다", proc)
        expect("Traceback" not in proc.stderr, "스택트레이스가 출력되면 안 됩니다", proc)

    expect(not data_dir.joinpath("transactions.jsonl").exists(), "--help/사용법 오류는 저장 폴더를 만들지 않습니다 (D36)")


def check_unimplemented(data_dir: Path) -> None:
    """남은 미구현 명령은 [오류] 두 줄 + 종료 1, stdout 비어 있음. 초기화가 끝난 폴더에서 호출한다."""
    for target in UNIMPLEMENTED_TARGETS:
        proc = run_cli(data_dir, *target)
        expect(proc.returncode == 1, "미구현 명령은 종료 1 이어야 합니다", proc)
        lines = proc.stderr.strip().splitlines()
        expect(len(lines) == 2, "미구현 명령 오류는 정확히 두 줄이어야 합니다", proc)
        expect(lines[0] == "[오류] 아직 구현되지 않은 명령입니다", "첫 줄은 [오류] 원인", proc)
        expect(lines[1].startswith("[힌트] Phase "), "둘째 줄은 [힌트] Phase N", proc)
        expect(proc.stdout == "", "미구현 명령은 stdout 에 아무것도 쓰지 않습니다", proc)

    # --verbose 가 켜져도 오류 두 줄 계약은 유지되고 DEBUG 로그(log_call)는 stderr 에만 나온다.
    proc = run_cli(data_dir, "--verbose", *UNIMPLEMENTED_TARGETS[0])
    expect(proc.returncode == 1 and "[DEBUG]" in proc.stderr and proc.stdout == "", "--verbose 는 stderr 로그만 추가", proc)


# ---------------------------------------------------------------------------
# Phase 3 — category list/add, add(대화형 재입력), list(최신순·--limit), 초기화 안내 1회
# ---------------------------------------------------------------------------

INIT_NOTICE = "[안내] 저장 폴더를 초기화했습니다: "


def smoke_phase3(data_dir: Path) -> None:
    # 첫 명령: 폴더 초기화 안내 1회 + 거래 없음 안내
    proc = run_cli(data_dir, "list")
    expect(proc.returncode == 0, "빈 폴더의 list 는 종료 0", proc)
    expect(stdout_lines(proc) == [INIT_NOTICE + str(data_dir), "[안내] 거래가 없습니다"], "첫 실행은 초기화 안내 + 거래 없음", proc)
    for name in ("transactions.jsonl", "categories.jsonl", "budgets.jsonl"):
        expect(data_dir.joinpath(name).is_file(), f"초기화 후 {name} 이 있어야 합니다")

    # category list: 기본 5개가 이름 오름차순, 안내는 다시 나오지 않는다
    proc = run_cli(data_dir, "category", "list")
    expect(proc.returncode == 0, "category list 종료 0", proc)
    expect(stdout_lines(proc) == ["- etc", "- food", "- rent", "- salary", "- transport"], "기본 카테고리 5개 오름차순 (D04)", proc)

    # category add: 위치 인자 / 대화형 / 중복
    proc = run_cli(data_dir, "category", "add", "cafe")
    expect(proc.returncode == 0 and stdout_lines(proc) == ["[저장 완료] category=cafe"], "category add cafe", proc)
    proc = run_cli(data_dir, "category", "add", input_text="book\n")
    expect(proc.returncode == 0 and "[저장 완료] category=book" in proc.stdout, "category add 대화형 (D26)", proc)
    proc = run_cli(data_dir, "category", "add", "cafe")
    expect(proc.returncode == 1 and proc.stderr.startswith("[오류]") and proc.stdout == "", "중복 카테고리는 종료 1", proc)
    proc = run_cli(data_dir, "category", "list")
    expect(stdout_lines(proc) == ["- book", "- cafe", "- etc", "- food", "- rent", "- salary", "- transport"], "추가 후 정렬 유지", proc)

    # add 3건: 2건째는 잘못된 날짜를 먼저 넣어 재입력 흐름을 지나고, 3건째는 미등록 카테고리 재입력을 지난다 (D13, D37)
    proc = run_cli(data_dir, "add", input_text="2024-01-15\nexpense\nfood\n15000\n점심\nmeal\n")
    expect(proc.returncode == 0 and "[저장 완료] id=TX-000001" in proc.stdout, "add 1건째", proc)
    expect(proc.stderr == "", "정상 add 는 stderr 가 비어 있다", proc)

    proc = run_cli(data_dir, "add", input_text="2024-13-40\n2024-01-14\n Income \nsalary\n3000000\n\n\n")
    expect(proc.returncode == 0 and "[저장 완료] id=TX-000002" in proc.stdout, "add 2건째 (날짜 재입력 후 저장)", proc)
    expect("[오류] 존재하지 않는 날짜입니다: 2024-13-40" in proc.stdout and "[힌트] 예: 2024-01-15" in proc.stdout, "재입력 안내 두 줄은 stdout (D37)", proc)
    expect(proc.stdout.count("날짜(YYYY-MM-DD): ") == 2 and proc.stdout.count("타입(income/expense): ") == 1, "같은 항목만 다시 묻는다", proc)

    proc = run_cli(data_dir, "add", input_text="2024-01-15\nexpense\ncoffee\ncafe\n4500\n커피\n\n")
    expect(proc.returncode == 0 and "[저장 완료] id=TX-000003" in proc.stdout, "add 3건째 (카테고리 재입력 후 저장)", proc)
    expect("[오류] 등록되지 않은 카테고리입니다: coffee" in proc.stdout and "[힌트] 등록된 카테고리: book, cafe" in proc.stdout, "미등록 카테고리 안내", proc)

    # 중단: 입력이 끊기면(EOF) 종료 130, 저장되지 않음
    proc = run_cli(data_dir, "add", input_text="2024-01-16\n")
    expect(proc.returncode == 130 and "[안내] 중단했습니다" in proc.stderr and "[저장 완료]" not in proc.stdout, "EOF 는 130 (D13)", proc)
    proc = run_cli(data_dir, "add", input_text="2024-01-16\nexpense\nfood\n0\n")
    expect(proc.returncode == 130 and "[오류] 금액은 양의 정수여야 합니다" in proc.stdout, "금액 재입력 중 EOF 도 130", proc)

    # list: 최신순(날짜 내림차순, 같은 날짜는 id 내림차순), --limit
    proc = run_cli(data_dir, "list", "--limit", "2")
    rows = [cells(line) for line in stdout_lines(proc)]
    expect(proc.returncode == 0 and len(rows) == 2, "list --limit 2 는 2건", proc)
    expect(rows[0] == ["TX-000003", "2024-01-15", "expense", "cafe", "4500", "커피"], "1행: 같은 날짜 중 큰 id (D06)", proc)
    expect(rows[1] == ["TX-000001", "2024-01-15", "expense", "food", "15000", "점심"], "2행", proc)
    proc = run_cli(data_dir, "list")
    rows = [cells(line) for line in stdout_lines(proc)]
    expect([r[0] for r in rows] == ["TX-000003", "TX-000001", "TX-000002"], "list 기본 limit 20 으로 전체 최신순", proc)
    expect(rows[2][:5] == ["TX-000002", "2024-01-14", "income", "salary", "3000000"], "income 행", proc)


# ---------------------------------------------------------------------------
# Phase 4 — budget set/list, summary(집계·TOP·예산·경고·데이터 없음), search(조건별 건수)
# ---------------------------------------------------------------------------


def add_tx(data_dir: Path, date: str, type_: str, category: str, amount: str, memo: str = "", tags: str = "") -> None:
    proc = run_cli(data_dir, "add", input_text=f"{date}\n{type_}\n{category}\n{amount}\n{memo}\n{tags}\n")
    expect(proc.returncode == 0 and "[저장 완료] id=" in proc.stdout, "스모크 데이터 add", proc)


def smoke_phase4(data_dir: Path) -> None:
    run_cli(data_dir, "list")  # 초기화 안내 소비
    add_tx(data_dir, "2024-01-14", "income", "salary", "3000000", "월급")
    add_tx(data_dir, "2024-01-15", "expense", "food", "15000", "점심", "meal")
    add_tx(data_dir, "2024-01-20", "expense", "food", "30000", "저녁 Dinner", "meal,family")
    add_tx(data_dir, "2024-01-12", "expense", "transport", "20000", "버스")

    # budget set → summary: 총액, 예산 사용률, TOP 2 순서
    proc = run_cli(data_dir, "budget", "set", "--month", "2024-01", "--amount", "100000")
    expect(proc.returncode == 0 and stdout_lines(proc) == ["[저장 완료] 2024-01 예산 100000원"], "budget set", proc)
    proc = run_cli(data_dir, "summary", "--month", "2024-01", "--top", "2")
    expect(proc.returncode == 0, "summary 종료 0", proc)
    expect(
        stdout_lines(proc) == [
            "총 수입: 3000000원", "총 지출: 65000원", "잔액: 2935000원", "예산: 100000원 (사용률 65.0%)",
            "지출 TOP 2", "1) food 45000원", "2) transport 20000원",
        ],
        "summary 출력 (README 5.4)", proc,
    )
    expect("[경고]" not in proc.stdout, "예산 이내면 경고 없음", proc)

    # 예산을 지출보다 작게 다시 set → 덮어쓰기 + [경고] 초과
    proc = run_cli(data_dir, "budget", "set", "--month", "2024-01", "--amount", "50000")
    expect(proc.returncode == 0, "budget set 덮어쓰기", proc)
    proc = run_cli(data_dir, "summary", "--month", "2024-01")
    lines = stdout_lines(proc)
    expect(proc.returncode == 0 and "예산: 50000원 (사용률 130.0%)" in lines, "덮어쓴 예산으로 사용률 계산 (D17)", proc)
    expect(lines[lines.index("예산: 50000원 (사용률 130.0%)") + 1] == "[경고] 예산 초과: +15000원", "경고 줄은 예산 줄 바로 다음", proc)
    expect("지출 TOP 5" in lines and lines[-1] == "2) transport 20000원", "--top 기본값 5 (D27)", proc)

    # 데이터 없는 달: 안내만, 예산이 있으면 예산 줄 한 개 추가 (D16)
    proc = run_cli(data_dir, "summary", "--month", "2024-02")
    expect(proc.returncode == 0 and stdout_lines(proc) == ["[안내] 2024-02 데이터 없음"], "데이터 없음", proc)
    run_cli(data_dir, "budget", "set", "--month", "2024-02", "--amount", "300000")
    proc = run_cli(data_dir, "summary", "--month", "2024-02")
    expect(stdout_lines(proc) == ["[안내] 2024-02 데이터 없음", "예산: 300000원 (사용률 0.0%)"], "데이터 없음 + 예산 줄", proc)
    for target in (["summary", "--month", "2024-13"], ["budget", "set", "--month", "2024-01", "--amount", "1,000"]):
        proc = run_cli(data_dir, *target)
        expect(proc.returncode == 1 and proc.stderr.startswith("[오류]") and proc.stdout == "", "월·금액 검증 실패는 종료 1 (D32)", proc)

    # search: 조건별 건수와 최신순
    def search_ids(*argv: str) -> list[str]:
        proc = run_cli(data_dir, "search", *argv)
        expect(proc.returncode == 0, "search 종료 0", proc)
        return [cells(line)[0] for line in stdout_lines(proc) if not line.startswith("[안내]")]

    expect(search_ids("--type", "income") == ["TX-000001"], "--type")
    expect(search_ids("--category", "food") == ["TX-000003", "TX-000002"], "--category 최신순")
    expect(search_ids("--q", "dinner") == ["TX-000003"], "--q 대소문자 무시 부분 일치")
    expect(search_ids("--tag", "meal") == ["TX-000003", "TX-000002"], "--tag 정확 일치")
    expect(search_ids("--from", "2024-01-13", "--to", "2024-01-15") == ["TX-000002", "TX-000001"], "--from/--to 포함 범위")
    expect(search_ids("--from", "2024-01-15", "--limit", "1") == ["TX-000003"], "--limit")
    expect(search_ids("--category", "food", "--type", "income") == [], "AND 조건 0건은 안내만")
    proc = run_cli(data_dir, "search", "--tag", "없는태그")
    expect(proc.returncode == 0 and stdout_lines(proc) == ["[안내] 조건에 맞는 거래가 없습니다"], "0건 안내 (D28)", proc)
    proc = run_cli(data_dir, "search", "--from", "2024-1-5")
    expect(proc.returncode == 1 and proc.stderr.startswith("[오류] 날짜 형식"), "날짜 형식 오류는 종료 1", proc)
    proc = run_cli(data_dir, "search", "--limit", "0")
    expect(proc.returncode == 2, "--limit 0 은 사용법 오류 2 (D32)", proc)

    # budget list: 월 오름차순
    proc = run_cli(data_dir, "budget", "list")
    expect(proc.returncode == 0 and stdout_lines(proc) == ["2024-01 | 50000원", "2024-02 | 300000원"], "budget list (D25)", proc)


# ---------------------------------------------------------------------------
# Phase 5 — update(옵션 기반), delete, category remove(차단 / --replace 재배정)
# ---------------------------------------------------------------------------


def expect_two_line_error(proc: subprocess.CompletedProcess[str], first_line: str, label: str) -> None:
    lines = proc.stderr.strip().splitlines()
    expect(proc.returncode == 1 and proc.stdout == "", f"{label}: 종료 1, stdout 비어 있음", proc)
    expect(len(lines) == 2 and lines[0] == first_line and lines[1].startswith("[힌트] "), f"{label}: [오류]/[힌트] 두 줄", proc)
    expect("Traceback" not in proc.stderr, "스택트레이스가 출력되면 안 됩니다", proc)


def list_rows(data_dir: Path) -> list[list[str]]:
    proc = run_cli(data_dir, "list")
    expect(proc.returncode == 0, "list 종료 0", proc)
    return [cells(line) for line in stdout_lines(proc) if not line.startswith("[안내]")]


def smoke_phase5(data_dir: Path) -> None:
    run_cli(data_dir, "list")  # 초기화 안내 소비
    add_tx(data_dir, "2024-01-15", "expense", "food", "15000", "점심", "meal")
    add_tx(data_dir, "2024-01-14", "income", "salary", "3000000", "월급")
    add_tx(data_dir, "2024-01-12", "expense", "transport", "20000", "버스", "commute")

    # update: 금액·메모 변경이 list 에 반영되고 다른 거래는 그대로
    proc = run_cli(data_dir, "update", "--id", "TX-000001", "--amount", "18000", "--memo", "점심+커피")
    expect(proc.returncode == 0 and stdout_lines(proc) == ["[수정 완료] id=TX-000001"], "update 성공 (README 5.7)", proc)
    rows = list_rows(data_dir)
    expect(rows[0] == ["TX-000001", "2024-01-15", "expense", "food", "18000", "점심+커피"], "update 반영", proc)
    expect(rows[1][:5] == ["TX-000002", "2024-01-14", "income", "salary", "3000000"], "다른 거래 보존")
    expect(rows[2] == ["TX-000003", "2024-01-12", "expense", "transport", "20000", "버스"], "다른 거래 보존 2")

    proc = run_cli(data_dir, "update", "--id", "TX-000001", "--tags", "")
    expect(proc.returncode == 0, '--tags "" 비움', proc)
    proc = run_cli(data_dir, "search", "--tag", "meal")
    expect(stdout_lines(proc) == ["[안내] 조건에 맞는 거래가 없습니다"], "태그가 비워졌다", proc)

    expect_two_line_error(run_cli(data_dir, "update", "--id", "TX-999999", "--amount", "1"), "[오류] 거래를 찾을 수 없습니다: TX-999999", "없는 id")
    expect_two_line_error(run_cli(data_dir, "update", "--id", "TX-000001", "--amount", "1,000"), "[오류] 금액은 양의 정수여야 합니다 (입력: 1,000)", "금액 검증")
    expect_two_line_error(run_cli(data_dir, "update", "--id", "TX-000001", "--category", "coffee"), "[오류] 등록되지 않은 카테고리입니다: coffee", "미등록 카테고리")
    proc = run_cli(data_dir, "update", "--id", "TX-000001")
    expect(proc.returncode == 2 and "Traceback" not in proc.stderr, "수정 옵션 없음은 사용법 오류 2 (D03)", proc)
    expect(list_rows(data_dir)[0][4] == "18000", "실패한 update 는 파일을 바꾸지 않는다")

    # delete: 건수 감소, 재삭제는 없는 id
    proc = run_cli(data_dir, "delete", "--id", "TX-000003")
    expect(proc.returncode == 0 and stdout_lines(proc) == ["[삭제 완료] id=TX-000003"], "delete 성공 (README 5.8)", proc)
    expect([r[0] for r in list_rows(data_dir)] == ["TX-000001", "TX-000002"], "delete 후 2건")
    expect_two_line_error(run_cli(data_dir, "delete", "--id", "TX-000003"), "[오류] 거래를 찾을 수 없습니다: TX-000003", "없는 id delete")

    # category remove: 사용 중 차단 → --replace 검증 → 재배정 후 삭제 → 미사용 즉시 삭제
    expect_two_line_error(run_cli(data_dir, "category", "remove", "--name", "food"), "[오류] 'food'를 사용하는 거래가 1건 있어 삭제할 수 없습니다.", "사용 중 차단 (D18)")
    expect_two_line_error(run_cli(data_dir, "category", "remove", "--name", "food", "--replace", "food"), "[오류] 대체 카테고리가 삭제 대상과 같습니다: food", "자기 자신 거부")
    expect_two_line_error(run_cli(data_dir, "category", "remove", "--name", "food", "--replace", "coffee"), "[오류] 등록되지 않은 카테고리입니다: coffee", "없는 대체 카테고리")
    expect_two_line_error(run_cli(data_dir, "category", "remove", "--name", "cafe"), "[오류] 카테고리를 찾을 수 없습니다: cafe", "없는 카테고리")
    proc = run_cli(data_dir, "category", "remove", "--name", "food", "--replace", "etc")
    expect(proc.returncode == 0 and stdout_lines(proc) == ["[완료] 거래 1건을 'etc'로 이동하고 category=food 를 삭제했습니다."], "--replace 재배정 (README 5.6)", proc)
    proc = run_cli(data_dir, "search", "--category", "etc")
    expect([cells(line)[0] for line in stdout_lines(proc)] == ["TX-000001"], "재배정된 거래를 search --category 로 확인", proc)
    proc = run_cli(data_dir, "search", "--category", "food")
    expect(stdout_lines(proc) == ["[안내] 조건에 맞는 거래가 없습니다"], "옛 카테고리는 0건", proc)
    proc = run_cli(data_dir, "category", "remove", "--name", "rent")
    expect(proc.returncode == 0 and stdout_lines(proc) == ["[삭제 완료] category=rent"], "미사용 즉시 삭제", proc)
    proc = run_cli(data_dir, "category", "list")
    expect(stdout_lines(proc) == ["- etc", "- salary", "- transport"], "삭제 후 category list", proc)


# ---------------------------------------------------------------------------
# Phase 6 — import(샘플 CSV, skip 보고) → export(헤더·행수) → 라운드트립 → 조건 없음 2
# ---------------------------------------------------------------------------

SAMPLE_CSV = ROOT / "samples" / "import_sample.csv"
CSV_HEADER = "date,type,category,amount,memo,tags"


def smoke_phase6(data_dir: Path) -> None:
    first = data_dir / "first"
    proc = run_cli(first, "import", "--from", str(SAMPLE_CSV))
    expect(proc.returncode == 0, "import 샘플 종료 0", proc)
    expect(
        stdout_lines(proc)[1:] == ["[완료] imported=5, skipped=1", "  - 3행: 금액은 양의 정수여야 합니다 (입력: -500)"],
        "import 요약과 skip 사유 (README 5.9, D19)", proc,
    )
    expect(len(list_rows(first)) == 5, "import 후 5건")

    out = data_dir / "export.csv"
    proc = run_cli(first, "export", "--out", str(out), "--month", "2024-01")
    expect(proc.returncode == 0 and stdout_lines(proc) == [f"[완료] {out} (5 records)"], "export --month (D20)", proc)
    lines = out.read_text(encoding="utf-8").splitlines()
    expect(lines[0] == CSV_HEADER and len(lines) == 6, "export 파일: 헤더 + 5행", proc)
    expect(lines[1].startswith("2024-01-20,expense,food,30000,") and lines[-1].startswith("2024-01-05,expense,rent,500000,"), "export 는 최신순", proc)
    expect(b"\r\n" not in out.read_bytes(), "newline='' 로 빈 줄 없음")

    second = data_dir / "second"
    proc = run_cli(second, "import", "--from", str(out))
    expect(proc.returncode == 0 and stdout_lines(proc)[1:] == ["[완료] imported=5, skipped=0"], "export 파일을 새 폴더에 import", proc)
    expect(
        sorted(r[1:] for r in list_rows(second)) == sorted(r[1:] for r in list_rows(first)),
        "라운드트립: id 를 제외한 필드가 같다",
    )

    proc = run_cli(first, "export", "--out", str(data_dir / "range.csv"), "--from", "2024-01-13", "--to", "2024-01-15")
    expect(proc.returncode == 0 and "(2 records)" in proc.stdout, "export --from/--to 포함 범위", proc)
    proc = run_cli(first, "export", "--out", str(out))
    expect(proc.returncode == 2 and "Traceback" not in proc.stderr, "export 조건 없음은 사용법 오류 2 (D20)", proc)
    expect_two_line_error(run_cli(first, "import", "--from", str(data_dir / "없음.csv")), f"[오류] 가져올 파일을 찾을 수 없습니다: {data_dir / '없음.csv'}", "import 파일 없음")

    check_unimplemented(first)


SMOKES: dict[int, SmokeFn] = {
    1: smoke_phase1,
    3: smoke_phase3,
    4: smoke_phase4,
    5: smoke_phase5,
    6: smoke_phase6,
    # 7: backup
}


# ---------------------------------------------------------------------------
# 게이트 실행
# ---------------------------------------------------------------------------


def run_unittests() -> tuple[bool, int]:
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return result.wasSuccessful(), result.testsRun


def run_smokes(up_to_phase: int) -> list[int]:
    passed: list[int] = []
    for phase in sorted(SMOKES):
        if phase > up_to_phase:
            print(f"smoke {phase}: 건너뜀 (Phase {up_to_phase} 까지만 실행)")
            continue
        with tempfile.TemporaryDirectory(prefix="budget_app_smoke_") as tmp:
            SMOKES[phase](Path(tmp))
        print(f"smoke {phase}: OK")
        passed.append(phase)
    return passed


def configure_console() -> None:
    """게이트 자체의 한글 출력도 Windows 파이프(cp949)에서 깨지지 않게 한다 (D30과 동일)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass


def main(argv: list[str] | None = None) -> int:
    configure_console()
    parser = argparse.ArgumentParser(description="budget_app 검증 게이트 (unittest + CLI 스모크)")
    parser.add_argument("--phase", type=int, default=CURRENT_PHASE, metavar="N", help=f"이 Phase 까지의 스모크만 실행 (기본값: {CURRENT_PHASE})")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(ROOT))
    ok, test_count = run_unittests()
    if not ok:
        print(f"verify: FAIL (unittest {test_count}개 중 실패 있음)")
        return 1

    try:
        passed = run_smokes(args.phase)
    except SmokeFailure as failure:
        print(f"smoke 실패: {failure}")
        print("verify: FAIL (smoke)")
        return 1

    smoke_label = ", ".join(str(p) for p in passed) if passed else "없음"
    print(f"verify: PASS (unittest {test_count}개, smoke {smoke_label})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
