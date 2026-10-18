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
CURRENT_PHASE = 1  # 구현이 끝난 마지막 Phase. Phase 를 완료할 때마다 올린다.

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


# ---------------------------------------------------------------------------
# Phase 1 — 골격과 계약: --help 전부 0, 사용법 오류 2, 미구현 명령 [오류] 두 줄 + 1
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

UNIMPLEMENTED_TARGETS: list[list[str]] = [
    ["list"],
    ["search", "--category", "food"],
    ["summary", "--month", "2024-01"],
    ["budget", "set", "--month", "2024-01", "--amount", "500000"],
    ["budget", "list"],
    ["category", "add", "cafe"],
    ["category", "list"],
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

    for target in UNIMPLEMENTED_TARGETS:
        proc = run_cli(data_dir, *target)
        expect(proc.returncode == 1, "미구현 명령은 종료 1 이어야 합니다", proc)
        lines = proc.stderr.strip().splitlines()
        expect(len(lines) == 2, "미구현 명령 오류는 정확히 두 줄이어야 합니다", proc)
        expect(lines[0] == "[오류] 아직 구현되지 않은 명령입니다", "첫 줄은 [오류] 원인", proc)
        expect(lines[1].startswith("[힌트] Phase "), "둘째 줄은 [힌트] Phase N", proc)
        expect(proc.stdout == "", "미구현 명령은 stdout 에 아무것도 쓰지 않습니다", proc)

    # add 는 대화형이지만 P1 에서는 카테고리 조회 단계에서 미구현 오류로 끝나야 한다 (입력을 기다리지 않음).
    proc = run_cli(data_dir, "add", input_text="")
    expect(proc.returncode == 1 and "[오류]" in proc.stderr, "add 는 P1 에서 미구현 오류 종료 1", proc)

    # --verbose 가 켜져도 오류 두 줄 계약은 유지되고 DEBUG 로그는 stderr 에만 나온다.
    proc = run_cli(data_dir, "--verbose", "list")
    expect(proc.returncode == 1 and "[DEBUG]" in proc.stderr and proc.stdout == "", "--verbose 는 stderr 로그만 추가", proc)


SMOKES: dict[int, SmokeFn] = {
    1: smoke_phase1,
    # 3: smoke_phase3 (category/add/list), 4: search/summary/budget, 5: update/delete/remove, 6: import/export, 7: backup
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
