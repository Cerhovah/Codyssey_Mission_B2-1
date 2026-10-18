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
CURRENT_PHASE = 3  # 구현이 끝난 마지막 Phase. Phase 를 완료할 때마다 올린다.

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
    ["search", "--category", "food"],
    ["summary", "--month", "2024-01"],
    ["budget", "set", "--month", "2024-01", "--amount", "500000"],
    ["budget", "list"],
    ["category", "remove", "--name", "food"],
    ["update", "--id", "TX-000001", "--amount", "1"],
    ["delete", "--id", "TX-000001"],
    ["import", "--from", "x.csv"],
    ["export", "--out", "x.csv", "--month", "2024-01"],
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

    check_unimplemented(data_dir)


SMOKES: dict[int, SmokeFn] = {
    1: smoke_phase1,
    3: smoke_phase3,
    # 4: search/summary/budget, 5: update/delete/remove, 6: import/export, 7: backup
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
