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
CURRENT_PHASE = 10  # 과제 P9 이후 사용자 요청으로 추가한 삭제 복구까지 검증한다.

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
    """실패한 조건에 실행 인자·종료 코드·출력을 붙여 재현 정보를 남긴다."""
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
    """출력의 빈 줄을 제외해 의미 있는 결과만 비교한다."""
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
    ["restore"],
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

def smoke_phase1(data_dir: Path) -> None:
    """도움말과 사용법 오류가 종료 코드를 지키고 저장 파일을 만들지 않는지 확인한다."""
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


def check_verbose_contract(data_dir: Path) -> None:
    """--verbose 가 켜져도 오류 두 줄 계약은 유지되고 DEBUG 로그(log_call/timed)는 stderr 에만 나온다 (D22)."""
    proc = run_cli(data_dir, "--verbose", "delete", "--id", "TX-999999")
    expect(proc.returncode == 1 and "[DEBUG]" in proc.stderr and proc.stdout == "", "--verbose 는 stderr 로그만 추가", proc)
    lines = [line for line in proc.stderr.strip().splitlines() if not line.startswith("[DEBUG]")]
    expect(lines == ["[오류] 거래를 찾을 수 없습니다: TX-999999", "[힌트] python -m budget_app list 로 id를 확인하세요."], "오류 두 줄 유지", proc)
    proc = run_cli(data_dir, "--verbose", "list", "--limit", "1")
    expect(proc.returncode == 0 and "ms)" in proc.stderr and "[DEBUG]" not in proc.stdout, "timed 로그는 stderr (D22)", proc)


# ---------------------------------------------------------------------------
# Phase 3 — category list/add, add(대화형 재입력), list(최신순·--limit), 초기화 안내 1회
# ---------------------------------------------------------------------------

INIT_NOTICE = "[안내] 저장 폴더를 초기화했습니다: "


def smoke_phase3(data_dir: Path) -> None:
    # 첫 명령: 폴더 초기화 안내 1회 + 거래 없음 안내
    """첫 초기화부터 카테고리·거래 등록·재입력·목록 조회까지 실제 명령으로 확인한다."""
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
    """대화형 거래 입력을 실제 프로세스에 전달해 스모크 자료를 등록한다."""
    proc = run_cli(data_dir, "add", input_text=f"{date}\n{type_}\n{category}\n{amount}\n{memo}\n{tags}\n")
    expect(proc.returncode == 0 and "[저장 완료] id=" in proc.stdout, "스모크 데이터 add", proc)


def smoke_phase4(data_dir: Path) -> None:
    """예산과 월별 요약·초과 경고·조건 검색을 실제 명령으로 확인한다."""
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
        """실제 검색 명령의 결과 번호를 뽑아 조건별 결과와 정렬을 비교한다."""
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
    expect(proc.returncode == 0 and [cells(line) for line in stdout_lines(proc)] == [["2024-01", "50000원"], ["2024-02", "300000원"]], "budget list (D25)", proc)


# ---------------------------------------------------------------------------
# Phase 5 — update(옵션 기반), delete, category remove(차단 / --replace 재배정)
# ---------------------------------------------------------------------------


def expect_two_line_error(proc: subprocess.CompletedProcess[str], first_line: str, label: str) -> None:
    """실패 종료와 오류·해결 힌트 두 줄이 지켜지는지 확인한다."""
    lines = proc.stderr.strip().splitlines()
    expect(proc.returncode == 1 and proc.stdout == "", f"{label}: 종료 1, stdout 비어 있음", proc)
    expect(len(lines) == 2 and lines[0] == first_line and lines[1].startswith("[힌트] "), f"{label}: [오류]/[힌트] 두 줄", proc)
    expect("Traceback" not in proc.stderr, "스택트레이스가 출력되면 안 됩니다", proc)


def list_rows(data_dir: Path) -> list[list[str]]:
    """실제 목록 명령의 거래 행을 분리해 후속 스모크에서 비교한다."""
    proc = run_cli(data_dir, "list")
    expect(proc.returncode == 0, "list 종료 0", proc)
    return [cells(line) for line in stdout_lines(proc) if not line.startswith("[안내]")]


def smoke_phase5(data_dir: Path) -> None:
    """수정·삭제·카테고리 재배정의 성공과 실패 시 거래 보존을 확인한다."""
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
    """CSV 가져오기·내보내기·재가져오기와 잘못된 사용법을 확인한다."""
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


# ---------------------------------------------------------------------------
# Phase 7 — 테이블 정렬(구분자 위치 일치, 금액 우정렬) + backup(폴더에 4개 파일, 재실행은 다른 폴더)
# ---------------------------------------------------------------------------


def smoke_phase7(data_dir: Path) -> None:
    """표 정렬과 네 파일 백업 및 같은 시각의 백업 충돌 회피를 확인한다."""
    run_cli(data_dir, "list")  # 초기화 안내 소비
    add_tx(data_dir, "2024-01-15", "expense", "food", "15000", "점심", "meal")
    add_tx(data_dir, "2024-01-14", "income", "salary", "3000000", "월급")
    add_tx(data_dir, "2024-01-12", "expense", "transport", "20000", "버스")
    run_cli(data_dir, "budget", "set", "--month", "2024-01", "--amount", "100000")

    # 테이블 정렬: 구분자 위치가 모든 행에서 같고, 금액은 우정렬 (ASCII 열만 있으므로 문자 인덱스로 비교 가능)
    proc = run_cli(data_dir, "list")
    lines = stdout_lines(proc)
    expect(len(lines) == 3 and len({tuple(i for i in range(len(l)) if l.startswith(" | ", i)) for l in lines}) == 1, "list 구분자 위치 일치 (D42)", proc)
    raw = [line.split(" | ") for line in lines]
    expect(raw[0][4] == "  15000" and raw[1][4] == "3000000" and raw[2][4] == "  20000", "amount 우정렬", proc)
    expect(raw[1][2] == "income " and raw[0][3] == "food     ", "type·category 좌정렬", proc)
    expect(lines[0].endswith("| 점심") and all(not line.endswith(" ") for line in lines), "memo 는 패딩 없음", proc)
    proc = run_cli(data_dir, "budget", "set", "--month", "2024-02", "--amount", "5000")
    proc = run_cli(data_dir, "budget", "list")
    expect(stdout_lines(proc) == ["2024-01 | 100000원", "2024-02 |   5000원"], "budget list 금액 우정렬 (D42)", proc)

    # backup: 폴더 1개에 파일 4개(recurring.jsonl 포함, D44), 내용 동일, 재실행은 다른 폴더(같은 초면 -1 접미사)
    proc = run_cli(data_dir, "backup")
    expect(proc.returncode == 0 and len(stdout_lines(proc)) == 1, "backup 종료 0, 한 줄 출력", proc)
    line = stdout_lines(proc)[0]
    expect(line.startswith("[완료] ") and line.endswith(" (4 files)"), "backup 출력 형식 (README 5.10)", proc)
    target = Path(line[len("[완료] "):-len(" (4 files)")])
    expect(target.parent == data_dir / "backups" and target.is_dir(), "backups/{스탬프} 폴더", proc)
    expect(sorted(p.name for p in target.iterdir()) == ["budgets.jsonl", "categories.jsonl", "recurring.jsonl", "transactions.jsonl"], "백업 파일 4개", proc)
    for name in ("transactions.jsonl", "categories.jsonl", "budgets.jsonl", "recurring.jsonl"):
        expect((target / name).read_bytes() == (data_dir / name).read_bytes(), f"백업 {name} 내용 동일")
    proc = run_cli(data_dir, "backup")
    second = Path(stdout_lines(proc)[0][len("[완료] "):-len(" (4 files)")])
    expect(second != target and second.is_dir() and len(list(second.iterdir())) == 4, "재실행은 다른 폴더 (D43)", proc)
    expect(len(list((data_dir / "backups").iterdir())) == 2, "backups 폴더에 2개")

    check_verbose_contract(data_dir)


# ---------------------------------------------------------------------------
# Phase 9(예비) — recurring add(재입력) → apply(말일 보정) → list → 재 apply(중복 방지) → 미등록 카테고리 skip → remove
# ---------------------------------------------------------------------------


def smoke_phase9(data_dir: Path) -> None:
    """반복 규칙의 생성·적용·말일 보정·중복 방지·삭제를 확인한다."""
    run_cli(data_dir, "list")  # 초기화 안내 소비
    expect(data_dir.joinpath("recurring.jsonl").is_file(), "초기화가 recurring.jsonl 도 만든다 (D44)")
    proc = run_cli(data_dir, "recurring", "list")
    expect(proc.returncode == 0 and stdout_lines(proc) == ["[안내] 등록된 반복 내역이 없습니다"], "규칙 0건 list 안내", proc)
    proc = run_cli(data_dir, "recurring", "apply", "--month", "2024-02")
    expect(proc.returncode == 0 and stdout_lines(proc) == ["[안내] 등록된 반복 내역이 없습니다"], "규칙 0건 apply 안내, 종료 0", proc)

    proc = run_cli(data_dir, "recurring", "add", input_text="25\nincome\nsalary\n3000000\n월급\n\n")
    expect(proc.returncode == 0 and "[저장 완료] id=RC-000001" in proc.stdout, "recurring add 1", proc)
    proc = run_cli(data_dir, "recurring", "add", input_text="0\n31\nexpense\nrent\n500000\n월세\nfixed\n")
    expect(proc.returncode == 0 and "[저장 완료] id=RC-000002" in proc.stdout, "recurring add 2 (잘못된 일 재입력 후)", proc)
    expect("[오류] 매월 일은 1~31 사이의 정수여야 합니다 (입력: 0)" in proc.stdout and proc.stdout.count("매월 며칠(1~31): ") == 2, "일 재입력 (D13)", proc)

    proc = run_cli(data_dir, "recurring", "list")
    rows = [cells(line) for line in stdout_lines(proc)]
    expect(rows == [["RC-000001", "매월 25일", "income", "salary", "3000000", "월급"], ["RC-000002", "매월 31일", "expense", "rent", "500000", "월세"]], "recurring list 테이블", proc)

    proc = run_cli(data_dir, "recurring", "apply", "--month", "2024-02")
    expect(proc.returncode == 0 and stdout_lines(proc) == ["[완료] 2024-02 반복 내역 적용 created=2, skipped=0"], "apply 2024-02", proc)
    rows = list_rows(data_dir)
    expect([r[:5] for r in rows] == [["TX-000002", "2024-02-29", "expense", "rent", "500000"], ["TX-000001", "2024-02-25", "income", "salary", "3000000"]], "생성 거래 (31일 → 02-29 보정)")
    proc = run_cli(data_dir, "search", "--tag", "rc:RC-000002")
    expect([cells(line)[0] for line in stdout_lines(proc)] == ["TX-000002"], "rc: 태그로 추적 가능", proc)
    proc = run_cli(data_dir, "search", "--tag", "fixed")
    expect([cells(line)[0] for line in stdout_lines(proc)] == ["TX-000002"], "규칙 태그 유지", proc)

    proc = run_cli(data_dir, "recurring", "apply", "--month", "2024-02")
    lines = stdout_lines(proc)
    expect(proc.returncode == 0 and lines[0] == "[완료] 2024-02 반복 내역 적용 created=0, skipped=2", "재 apply 는 중복 생성 안 함", proc)
    expect(lines[1] == "  - RC-000001: 2024-02 에 이미 적용됨 (TX-000001)" and lines[2].startswith("  - RC-000002: 2024-02 에 이미 적용됨"), "skip 사유 줄", proc)
    expect(len(list_rows(data_dir)) == 2, "거래 건수 유지")
    proc = run_cli(data_dir, "recurring", "apply", "--month", "2024-04")
    expect(stdout_lines(proc)[0] == "[완료] 2024-04 반복 내역 적용 created=2, skipped=0", "다른 달은 생성", proc)
    proc = run_cli(data_dir, "search", "--from", "2024-04-30", "--to", "2024-04-30")
    expect([cells(line)[3] for line in stdout_lines(proc)] == ["rent"], "30일 달 보정", proc)

    # 미등록 카테고리가 된 규칙은 skip 사유 출력
    run_cli(data_dir, "category", "add", "cafe")
    proc = run_cli(data_dir, "recurring", "add", input_text="1\nexpense\ncafe\n4500\n커피\n\n")
    expect("[저장 완료] id=RC-000003" in proc.stdout, "recurring add 3", proc)
    proc = run_cli(data_dir, "category", "remove", "--name", "cafe")
    expect(proc.returncode == 0, "규칙만 쓰는 카테고리는 삭제 가능", proc)
    proc = run_cli(data_dir, "recurring", "apply", "--month", "2024-05")
    expect(stdout_lines(proc) == ["[완료] 2024-05 반복 내역 적용 created=2, skipped=1", "  - RC-000003: 등록되지 않은 카테고리입니다: cafe"], "미등록 카테고리 skip", proc)

    expect_two_line_error(run_cli(data_dir, "recurring", "remove", "--id", "RC-000009"), "[오류] 반복 내역을 찾을 수 없습니다: RC-000009", "없는 규칙 remove")
    expect_two_line_error(run_cli(data_dir, "recurring", "remove", "--id", "TX-000001"), "[오류] 반복 내역 id 형식이 올바르지 않습니다 (입력: TX-000001)", "id 형식 오류")
    proc = run_cli(data_dir, "recurring", "remove", "--id", "RC-000003")
    expect(proc.returncode == 0 and stdout_lines(proc) == ["[삭제 완료] id=RC-000003"], "recurring remove", proc)
    proc = run_cli(data_dir, "recurring", "list")
    expect([cells(line)[0] for line in stdout_lines(proc)] == ["RC-000001", "RC-000002"], "remove 후 list", proc)
    expect_two_line_error(run_cli(data_dir, "recurring", "apply", "--month", "2024-13"), "[오류] 존재하지 않는 월입니다: 2024-13", "월 검증")
    proc = run_cli(data_dir, "recurring", "remove")
    expect(proc.returncode == 2 and "Traceback" not in proc.stderr, "--id 누락은 사용법 오류 2", proc)
    for target in (["recurring"], ["recurring", "add"], ["recurring", "list"], ["recurring", "remove"], ["recurring", "apply"]):
        proc = run_cli(data_dir, *target, "--help")
        expect(proc.returncode == 0 and "usage" in proc.stdout.lower(), "recurring --help", proc)


# ---------------------------------------------------------------------------
# 추가 기능 10 — 삭제 → 다른 프로세스에서 최근/번호별 복구 → 중복 차단 → 간편 모드 확인
# ---------------------------------------------------------------------------


def smoke_restore(data_dir: Path) -> None:
    """다섯 거래 중 삭제한 거래만 복구하고 간편 명령과 재실행의 지속성을 확인한다."""
    proc = run_cli(data_dir, "import", "--from", str(SAMPLE_CSV))
    expect(proc.returncode == 0 and "imported=5" in proc.stdout, "복구 스모크 자료 5건", proc)
    before = list_rows(data_dir)

    # 각 호출은 다른 Python 프로세스다. 삭제 이력이 디스크에 남아야 복구할 수 있다.
    proc = run_cli(data_dir, "delete", "--id", "TX-000002")
    expect(proc.returncode == 0 and len(list_rows(data_dir)) == 4, "대상 거래 삭제", proc)
    proc = run_cli(data_dir, "restore")
    expect(proc.returncode == 0 and "[복구 완료] id=TX-000002" in proc.stdout, "최근 삭제 복구", proc)
    expect(list_rows(data_dir) == before, "복구 뒤 전체 목록과 원래 필드 일치")
    proc = run_cli(data_dir, "restore")
    expect(proc.returncode == 1 and "[오류]" in proc.stderr and "Traceback" not in proc.stderr, "중복 복구는 사용자 오류", proc)
    expect(list_rows(data_dir) == before, "중복 복구 실패 뒤 거래 보존")

    # 마지막 삭제와 다른 번호를 지정하면 그 번호의 이력을 골라 복구한다.
    for tx_id in ("TX-000002", "TX-000004"):
        proc = run_cli(data_dir, "delete", "--id", tx_id)
        expect(proc.returncode == 0, "번호별 복구 준비 삭제", proc)
    proc = run_cli(data_dir, "restore", "--id", "TX-000002")
    expect(proc.returncode == 0 and "[복구 완료] id=TX-000002" in proc.stdout, "번호 지정 복구", proc)

    proc = subprocess.run(
        [sys.executable, str(ROOT / "budget.py"), "--data-dir", str(data_dir)],
        input="복구 tx-000004\nlist\nexit\n", cwd=ROOT,
        capture_output=True, text=True, encoding="utf-8", timeout=15,
    )
    expect(proc.returncode == 0 and proc.stderr == "", "간편 모드 복구와 다음 명령 실행", proc)
    expect("[복구 완료] id=TX-000004" in proc.stdout, "한글 복구와 소문자 번호 지원", proc)
    expect(list_rows(data_dir) == before, "다른 거래를 유지하며 원래 다섯 건 복구")


SMOKES: dict[int, SmokeFn] = {
    1: smoke_phase1,
    3: smoke_phase3,
    4: smoke_phase4,
    5: smoke_phase5,
    6: smoke_phase6,
    7: smoke_phase7,
    9: smoke_phase9,
    10: smoke_restore,
}


# ---------------------------------------------------------------------------
# 게이트 실행
# ---------------------------------------------------------------------------


def run_unittests() -> tuple[bool, int]:
    """기존 네 테스트 파일을 자동 발견해 실행하고 통과 여부와 개수를 돌려준다."""
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return result.wasSuccessful(), result.testsRun


def run_smokes(up_to_phase: int) -> list[int]:
    """각 시나리오를 별도 임시 폴더에서 순서대로 실행하고 성공 번호를 모은다."""
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
    """단위 테스트와 스모크를 하나의 게이트로 묶어 최종 종료 코드를 정한다."""
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
