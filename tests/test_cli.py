"""기존 CLI와 간편 진입점의 CSV 왕복·출력·종료 코드·삭제 복구를 사용자 흐름으로 확인한다."""
from __future__ import annotations

import contextlib
import csv
import io
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from budget_app.__main__ import entry
from budget_app.formatting import display_width, format_budget_table, format_transaction_table
from budget_app.models import Budget, Transaction
from budget_app.services import build_services

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "samples" / "import_sample.csv"
HEADER = ["date", "type", "category", "amount", "memo", "tags"]


class CliTestCase(unittest.TestCase):
    """터미널 명령 시나리오용 임시 저장소와 출력 수집 도구를 제공한다."""
    def setUp(self) -> None:
        """실제 사용자 데이터와 분리된 임시 저장 폴더를 준비한다."""
        self._tmp = tempfile.TemporaryDirectory(prefix="budget_app_cli_")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def run_cli(self, data_dir: Path, *argv: str) -> tuple[int, list[str], str]:
        """entry() 를 호출해 (종료 코드, stdout 비어 있지 않은 줄, stderr) 를 돌려준다. argparse 의 SystemExit 도 코드로 바꾼다."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = entry(["--data-dir", str(data_dir), *argv])
            except SystemExit as exc:
                code = int(exc.code or 0)
        lines = [line for line in out.getvalue().splitlines() if line.strip() and not line.startswith("[안내] 저장 폴더")]
        return code, lines, err.getvalue()

    def rows_of(self, data_dir: Path) -> set[tuple[str, str, str, int, str, str]]:
        """번호를 제외한 거래 내용을 집합으로 만들어 CSV 왕복 결과를 비교한다."""
        svc = build_services(data_dir)
        return {(t.date, t.type, t.category, t.amount, t.memo, ",".join(t.tags)) for t in svc.transactions.list_recent(1000)}


class RoundTripScenario(CliTestCase):
    """샘플 import → export → 빈 폴더에 import 하면 건수와 필드가 같다 (D19, D20, D41)."""

    def test_import_export_roundtrip(self) -> None:
        """CSV 가져오기·내보내기 뒤 다른 저장소에서도 거래 내용이 같은지 확인한다."""
        first = self.tmp / "first"
        code, lines, err = self.run_cli(first, "import", "--from", str(SAMPLE))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(lines, ["[완료] imported=5, skipped=1", "  - 3행: 금액은 양의 정수여야 합니다 (입력: -500)"])
        self.assertEqual(sorted(t.id for t in build_services(first).transactions.list_recent(10)),
                         ["TX-000001", "TX-000002", "TX-000003", "TX-000004", "TX-000005"])

        out = self.tmp / "export.csv"
        code, lines, err = self.run_cli(first, "export", "--out", str(out), "--month", "2024-01")
        self.assertEqual((code, lines, err), (0, [f"[완료] {out} (5 records)"], ""))
        raw = out.read_bytes()
        self.assertNotIn(b"\r\n", raw)                      # newline="" → LF 만
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))   # BOM 없음
        with open(out, encoding="utf-8", newline="") as handle:
            records = list(csv.reader(handle))
        self.assertEqual(records[0], HEADER)
        self.assertEqual(len(records), 6)
        self.assertEqual([r[0] for r in records[1:]], ["2024-01-20", "2024-01-15", "2024-01-14", "2024-01-12", "2024-01-05"])  # 최신순
        self.assertEqual(records[2], ["2024-01-15", "expense", "food", "15000", "점심", "meal"])
        self.assertEqual(records[4][5], "commute,daily")   # 태그는 쉼표 결합 문자열

        second = self.tmp / "second"
        code, lines, _ = self.run_cli(second, "import", "--from", str(out))
        self.assertEqual((code, lines), (0, ["[완료] imported=5, skipped=0"]))
        self.assertEqual(self.rows_of(second), self.rows_of(first))
        self.assertEqual(len(self.rows_of(second)), 5)

        # --from/--to 와 --month 는 AND. 0건도 헤더만 있는 파일을 만든다 (D20)
        empty = self.tmp / "empty.csv"
        code, lines, _ = self.run_cli(first, "export", "--out", str(empty), "--month", "2024-01", "--from", "2024-02-01")
        self.assertEqual((code, lines), (0, [f"[완료] {empty} (0 records)"]))
        self.assertEqual(empty.read_text(encoding="utf-8").splitlines(), [",".join(HEADER)])
        code, lines, _ = self.run_cli(first, "export", "--out", str(empty), "--from", "2024-01-13", "--to", "2024-01-15")
        self.assertEqual((code, lines), (0, [f"[완료] {empty} (2 records)"]))


class ExitCodeScenario(CliTestCase):
    """export 조건 없음 2, import 파일 없음·헤더 불일치 1(저장 없음), BOM 파일 허용, skip 행 보고."""

    def test_export_and_import_failures(self) -> None:
        """파일·헤더 오류의 종료 코드와 유효 행만 저장하는 가져오기 동작을 확인한다."""
        data_dir = self.tmp / "data"
        code, lines, err = self.run_cli(data_dir, "export", "--out", str(self.tmp / "x.csv"))
        self.assertEqual((code, lines), (2, []))
        self.assertIn("기간 조건이 필요합니다", err)
        self.assertNotIn("Traceback", err)
        self.assertFalse((self.tmp / "x.csv").exists())

        code, lines, err = self.run_cli(data_dir, "export", "--out", str(self.tmp / "no_dir" / "x.csv"), "--month", "2024-01")
        self.assertEqual((code, lines), (1, []))
        self.assertTrue(err.startswith("[오류] CSV 파일을 쓸 수 없습니다"))

        code, _, err = self.run_cli(data_dir, "import", "--from", str(self.tmp / "missing.csv"))
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("[오류] 가져올 파일을 찾을 수 없습니다"))

        bad_header = self.tmp / "bad.csv"
        bad_header.write_text("date,type,amount\n2024-01-15,expense,100\n", encoding="utf-8")
        code, lines, err = self.run_cli(data_dir, "import", "--from", str(bad_header))
        self.assertEqual((code, lines), (1, []))
        self.assertIn("[오류] CSV 헤더가 올바르지 않습니다 (누락: category, memo, tags)", err)
        self.assertIn("[힌트] 필수 헤더: date,type,category,amount,memo,tags", err)
        self.assertEqual(self.rows_of(data_dir), set())  # 저장 없음

        # BOM + 열 순서 바뀜 + 추가 열 + 모자란 행 + 미등록 카테고리 + 따옴표 안 줄바꿈 뒤의 행 번호
        mixed = self.tmp / "mixed.csv"
        mixed.write_text(
            "tags,memo,amount,category,type,date,extra\n"
            "meal,점심,15000,food,expense,2024-01-15,무시\n"
            ",,100,coffee,expense,2024-01-16,\n"
            '"a,b","두 줄\n메모",200,etc,income,2024-01-17,\n'
            "2024-01-18,expense\n"
            ",,300,rent,expense,2024-1-9,\n",
            encoding="utf-8-sig",
            newline="\n",  # Windows 텍스트 모드의 CRLF 변환을 막아 따옴표 안 줄바꿈을 LF 로 유지
        )
        code, lines, err = self.run_cli(data_dir, "import", "--from", str(mixed))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(
            lines,
            [
                "[완료] imported=2, skipped=3",
                "  - 3행: 등록되지 않은 카테고리입니다: coffee",
                "  - 6행: 타입은 income 또는 expense 여야 합니다 (입력: )",
                "  - 7행: 날짜 형식이 올바르지 않습니다 (YYYY-MM-DD).",
            ],
        )
        rows = self.rows_of(data_dir)
        self.assertIn(("2024-01-15", "expense", "food", 15000, "점심", "meal"), rows)
        self.assertIn(("2024-01-17", "income", "etc", 200, "두 줄\n메모", "a,b"), rows)


class TableFormattingScenario(CliTestCase):
    """테이블 정렬(B3, D42): 전각 폭 계산, 좌/우정렬, 마지막 열 패딩 없음, list 출력에서 구분자 위치 일치."""

    @staticmethod
    def separator_positions(line: str) -> list[int]:
        """표시 폭 기준으로 ' | ' 구분자의 위치를 구한다 (전각 문자가 섞여도 같은 열은 같은 위치여야 한다)."""
        positions, col = [], 0
        i = 0
        while i < len(line):
            if line.startswith(" | ", i):
                positions.append(col)
                col += 3
                i += 3
                continue
            col += display_width(line[i])
            i += 1
        return positions

    def test_width_and_alignment(self) -> None:
        """한글 표시 폭과 금액 정렬이 실제 목록 출력에도 적용되는지 확인한다."""
        self.assertEqual(display_width("food"), 4)
        self.assertEqual(display_width("식비"), 4)      # 한글 2자 = 4칸
        self.assertEqual(display_width("café"), 4)
        self.assertEqual(format_transaction_table([]), [])

        rows = [
            Transaction("TX-000012", "expense", "2024-01-15", 15000, "food", "점심", ["meal"]),
            Transaction("TX-000011", "income", "2024-01-14", 3000000, "salary", "", []),
            Transaction("TX-000010", "expense", "2024-01-12", 20000, "교통비", "버스", []),
        ]
        lines = format_transaction_table(rows)
        self.assertEqual(len(lines), 3)
        self.assertEqual(len({tuple(self.separator_positions(line)) for line in lines}), 1)  # 모든 행의 구분자 위치 동일
        cells = [[c.strip() for c in line.split("|")] for line in lines]
        self.assertEqual(cells[0], ["TX-000012", "2024-01-15", "expense", "food", "15000", "점심"])
        self.assertEqual(cells[1], ["TX-000011", "2024-01-14", "income", "salary", "3000000", ""])
        raw_cells = [line.split(" | ") for line in lines]
        self.assertEqual(raw_cells[1][2], "income ")             # type 좌정렬, 최소 폭 7
        self.assertEqual(raw_cells[0][4], "  15000")             # amount 우정렬 (최대 7자리)
        self.assertEqual(raw_cells[1][4], "3000000")
        self.assertEqual(raw_cells[0][3], "food  ")              # category 는 '교통비'(6칸) 에 맞춰 좌정렬
        self.assertEqual(raw_cells[2][3], "교통비")
        self.assertEqual(raw_cells[0][5], "점심")                # 마지막 열은 패딩 없음
        self.assertTrue(lines[1].endswith(" | "))                # 빈 메모는 구분자 뒤에 아무것도 붙지 않음

        budget_lines = format_budget_table([Budget("2024-01", 50000), Budget("2024-02", 300000)])
        self.assertEqual(budget_lines, ["2024-01 |  50000원", "2024-02 | 300000원"])
        self.assertEqual(format_budget_table([]), [])

        # CLI 끝까지: 한글 카테고리를 등록해 list 를 찍어도 구분자 위치가 모두 같다
        data_dir = self.tmp / "data"
        self.run_cli(data_dir, "category", "add", "교통비")
        for argv in (
            ("add", "2024-01-15", "expense", "food", "15000", "점심", "meal"),
            ("add", "2024-01-14", "income", "salary", "3000000", "", ""),
            ("add", "2024-01-12", "expense", "교통비", "20000", "버스", ""),
        ):
            svc = build_services(data_dir)
            svc.transactions.add(date=argv[1], type_=argv[2], category=argv[3], amount=argv[4], memo=argv[5], tags=argv[6])
        code, lines, _ = self.run_cli(data_dir, "list")
        self.assertEqual(code, 0)
        self.assertEqual(len(lines), 3)
        self.assertEqual(len({tuple(self.separator_positions(line)) for line in lines}), 1)
        self.assertEqual([line.split("|")[0].strip() for line in lines], ["TX-000001", "TX-000002", "TX-000003"])


class EasyModeScenario(CliTestCase):
    """실제 Python 프로세스에서 간편 실행·연속 작업·오류 복구와 입력 중단을 확인한다(D45)."""

    def run_easy(
        self,
        data_dir: Path,
        *argv: str,
        input_text: str = "",
        module: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        """두 간편 진입점 중 하나를 실행한다. 질문 입력 오류가 무한 대기로 이어지지 않게 제한한다."""
        command = [sys.executable, "-m", "budget_app.easy"] if module else [sys.executable, str(ROOT / "budget.py")]
        return subprocess.run(
            [*command, "--data-dir", str(data_dir), *argv],
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=ROOT,
            timeout=15,
        )

    def test_help_at_both_entry_points_does_not_initialize_data(self) -> None:
        """실행 도움말과 셸 도움말은 저장 파일을 만들지 않고, 명령 도움말 뒤에도 셸을 유지한다."""
        for module in (False, True):
            with self.subTest(module=module):
                data_dir = self.tmp / ("module" if module else "script")
                result = self.run_easy(data_dir, "--help", module=module)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("add", result.stdout)
                self.assertFalse(data_dir.exists())

                result = self.run_easy(data_dir, "--data-dir=-ledger", "help", "add", module=module)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(data_dir.exists())

                result = self.run_easy(
                    data_dir,
                    input_text="help\n도움말\nhelp add\nadd --help\n종료\n",
                    module=module,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("add", result.stdout)
                self.assertNotIn("Traceback", result.stdout + result.stderr)
                self.assertFalse(data_dir.exists())

    def test_default_add_search_summary_update_and_delete_in_one_session(self) -> None:
        """빈 날짜·종류·분류로 거래를 추가하고, 짧은 명령만으로 조회부터 수정·삭제까지 수행한다."""
        data_dir = self.tmp / "ledger"
        result = self.run_easy(
            data_dir,
            input_text="\n".join([
                "add", "", "", "", "1200", "점심", "meal",
                "list", "summary", "", "search", "점심",
                "update", "TX-000001", "1", "1500", "list",
                "update", "TX-000001", "2", "", "list",
                "delete", "TX-000001", "list", "exit", "",
            ]),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("[저장 완료] id=TX-000001", result.stdout)
        self.assertIn(date.today().isoformat(), result.stdout)
        self.assertIn("expense", result.stdout)
        self.assertIn("etc", result.stdout)
        self.assertIn("총 지출: 1200원", result.stdout)
        self.assertIn("1500", result.stdout)
        self.assertEqual(result.stdout.count("[수정 완료] id=TX-000001"), 2)
        self.assertIn("[삭제 완료] id=TX-000001", result.stdout)
        self.assertIn("거래가 없습니다", result.stdout)
        self.assertEqual(build_services(data_dir).transactions.list_recent(20), [])

    def test_zero_interactive_values_retry_before_saving_positive_values(self) -> None:
        """거래·예산·반복 규칙의 0 입력은 같은 항목을 재질문하고 고친 값만 한 번 저장한다."""
        data_dir = self.tmp / "ledger"
        result = self.run_easy(
            data_dir,
            input_text="\n".join([
                "add", "2024-01-10", "1", "food", "0", "1200", "재입력 거래", "",
                "budget set", "2024-01", "0", "20000",
                "recurring add", "0", "15", "1", "rent", "0", "5000", "재입력 규칙", "",
                "list", "exit", "",
            ]),
        )
        self.assertEqual((result.returncode, result.stderr), (0, ""), result.stdout)
        self.assertEqual(result.stdout.count("[오류] 금액은 양의 정수여야 합니다 (입력: 0)"), 3)
        self.assertIn("[오류] 매월 일은 1~31 사이의 정수여야 합니다 (입력: 0)", result.stdout)
        self.assertEqual(result.stdout.count("금액(양수 정수):"), 6)
        self.assertEqual(result.stdout.count("매월 며칠(1~31):"), 2)
        self.assertEqual(result.stdout.count("[저장 완료] id=TX-000001"), 1)
        self.assertEqual(result.stdout.count("[저장 완료] id=RC-000001"), 1)
        self.assertNotIn("Traceback", result.stdout)
        svc = build_services(data_dir)
        self.assertEqual([(row.id, row.amount) for row in svc.transactions.list_recent(20)], [("TX-000001", 1200)])
        self.assertEqual(svc.budgets.summary("2024-01", 5).budget.amount, 20000)
        self.assertEqual([(rule.day, rule.amount) for rule in svc.recurring.list_all()], [(15, 5000)])

    def test_zero_options_preserve_saved_data_and_shell_accepts_next_command(self) -> None:
        """금액 0은 종료 1, 출력 건수 0은 종료 2이며 원본을 보존하고 셸은 다음 조회를 받는다."""
        data_dir = self.tmp / "ledger"
        prepared = self.run_easy(
            data_dir,
            input_text="\n".join([
                "add", "2024-01-10", "1", "food", "1200", "유지할 거래", "",
                "budget set", "2024-01", "20000", "exit", "",
            ]),
        )
        self.assertEqual((prepared.returncode, prepared.stderr), (0, ""), prepared.stdout)
        before = {path.name: path.read_bytes() for path in data_dir.glob("*.jsonl")}
        cases = [
            (("update", "--id", "TX-000001", "--amount", "0"), 1),
            (("budget", "set", "--month", "2024-01", "--amount", "0"), 1),
            (("list", "--limit", "0"), 2),
            (("search", "--limit", "0"), 2),
            (("summary", "--month", "2024-01", "--top", "0"), 2),
        ]
        for argv, expected_code in cases:
            with self.subTest(argv=argv):
                result = self.run_easy(data_dir, *argv)
                self.assertEqual(result.returncode, expected_code, result.stdout + result.stderr)
                self.assertIn("양의 정수", result.stderr)
                self.assertNotIn("Traceback", result.stdout + result.stderr)
                self.assertEqual({path.name: path.read_bytes() for path in data_dir.glob("*.jsonl")}, before)

        result = self.run_easy(data_dir, input_text="list --limit 0\nlist --limit 1\nexit\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("양의 정수", result.stderr)
        self.assertEqual(result.stdout.count("[안내] 작업을 마치지 못했습니다."), 1)
        self.assertEqual(result.stdout.count("TX-000001 |"), 1)
        self.assertEqual({path.name: path.read_bytes() for path in data_dir.glob("*.jsonl")}, before)

    def test_csv_zero_amount_rows_are_skipped_without_saving_zero_values(self) -> None:
        """CSV의 0원 행은 건너뛰고 정상 행만 저장하며 전부 0원이어도 처리 결과를 보고한다."""
        data_dir = self.tmp / "ledger"
        source_csv = self.tmp / "zero.csv"
        source_csv.write_text(
            ",".join(HEADER) + "\n"
            "2024-01-10,expense,food,0,저장하면 안 되는 거래,\n"
            "2024-01-11,expense,food,1200,저장할 거래,\n",
            encoding="utf-8",
        )
        result = self.run_easy(data_dir, "import", "--from", str(source_csv))
        self.assertEqual((result.returncode, result.stderr), (0, ""), result.stdout)
        self.assertIn("[완료] imported=1, skipped=1", result.stdout)
        self.assertIn("2행: 금액은 양의 정수여야 합니다 (입력: 0)", result.stdout)
        self.assertEqual(
            [(row.id, row.amount, row.memo) for row in build_services(data_dir).transactions.list_recent(20)],
            [("TX-000001", 1200, "저장할 거래")],
        )

        # 행별 오류를 건너뛰는 기존 정책은 유지하며, 저장된 거래도 바뀌지 않아야 한다.
        before = (data_dir / "transactions.jsonl").read_bytes()
        source_csv.write_text(
            ",".join(HEADER) + "\n2024-01-12,expense,food,0,모든 행이 0원,\n",
            encoding="utf-8",
        )
        result = self.run_easy(data_dir, "import", "--from", str(source_csv))
        self.assertEqual((result.returncode, result.stderr), (0, ""), result.stdout)
        self.assertIn("[완료] imported=0, skipped=1", result.stdout)
        self.assertIn("입력: 0", result.stdout)
        self.assertNotIn("Traceback", result.stdout)
        self.assertEqual((data_dir / "transactions.jsonl").read_bytes(), before)

    def test_delete_shortcuts_normalize_ids_and_preserve_other_transactions(self) -> None:
        """영어·한글 삭제의 한 줄 입력·질문·기존 옵션은 대소문자를 정리해 지정한 거래만 지운다."""
        commands = [
            "delete TX-000002",
            "delete tx-000002",
            "삭제 Tx-000002",
            "delete\n  tx-000002  ",
            "삭제\n  Tx-000002  ",
            "delete --id Tx-000002",
            "delete --id=tx-000002",
        ]
        for index, command in enumerate(commands):
            with self.subTest(command=command):
                data_dir = self.tmp / f"delete_{index}"
                code, _, err = self.run_cli(data_dir, "import", "--from", str(SAMPLE))
                self.assertEqual((code, err), (0, ""))
                before = {row.id: row for row in build_services(data_dir).transactions.list_recent(20)}

                result = self.run_easy(data_dir, input_text=f"{command}\nlist\nexit\n", module=bool(index % 2))
                self.assertEqual((result.returncode, result.stderr), (0, ""), result.stdout)
                self.assertIn("[삭제 완료] id=TX-000002", result.stdout)
                self.assertNotIn("TX-000002 |", result.stdout)
                self.assertIn("TX-000001 |", result.stdout)
                remaining = {row.id: row for row in build_services(data_dir).transactions.list_recent(20)}
                self.assertEqual(remaining, {key: row for key, row in before.items() if key != "TX-000002"})

    def test_invalid_delete_commands_leave_saved_transactions_unchanged(self) -> None:
        """잘못된 번호·없는 번호·오타·여분 인자는 오류를 알리고 기존 거래 파일을 유지한다."""
        data_dir = self.tmp / "ledger"
        code, _, err = self.run_cli(data_dir, "import", "--from", str(SAMPLE))
        self.assertEqual((code, err), (0, ""))
        transactions = data_dir / "transactions.jsonl"
        before = transactions.read_bytes()
        cases = [
            (("delete", "TX-1"), 1),
            (("삭제", "tx_000002"), 1),
            (("delete", "--id=tx-00000a"), 1),
            (("delete", "tx-999999"), 1),
            (("delet", "tx-000002"), 2),
            (("delete", "tx-000001", "tx-000002"), 2),
        ]
        for argv, expected_code in cases:
            with self.subTest(argv=argv):
                result = self.run_easy(data_dir, *argv)
                self.assertEqual(result.returncode, expected_code, result.stdout + result.stderr)
                self.assertTrue(result.stderr)
                self.assertNotIn("[삭제 완료]", result.stdout)
                self.assertNotIn("Traceback", result.stdout + result.stderr)
                self.assertEqual(transactions.read_bytes(), before)

    def test_restore_shortcuts_work_after_delete_process_has_exited(self) -> None:
        """삭제한 프로세스가 종료되어도 영어·한글 짧은 명령으로 원래 거래 전체를 복구한다."""
        commands = [
            ("restore",),
            ("복구",),
            ("restore", "tx-000002"),
            ("복구", "  Tx-000002  "),
            ("restore", "--id", "Tx-000002"),
            ("restore", "--id=tx-000002"),
        ]
        for index, argv in enumerate(commands):
            with self.subTest(argv=argv):
                data_dir = self.tmp / f"restore_{index}"
                code, _, err = self.run_cli(data_dir, "import", "--from", str(SAMPLE))
                self.assertEqual((code, err), (0, ""))
                before = {tx.id: tx for tx in build_services(data_dir).transactions.list_recent(20)}

                deleted = self.run_easy(data_dir, "delete", "tx-000002")
                self.assertEqual((deleted.returncode, deleted.stderr), (0, ""), deleted.stdout)
                self.assertEqual(len(build_services(data_dir).transactions.list_recent(20)), 4)
                restored = self.run_easy(data_dir, *argv, module=bool(index % 2))
                self.assertEqual((restored.returncode, restored.stderr), (0, ""), restored.stdout)
                self.assertIn("[복구 완료] id=TX-000002", restored.stdout)
                self.assertEqual({tx.id: tx for tx in build_services(data_dir).transactions.list_recent(20)}, before)

        # 셸의 복구 명령도 추가 질문 없이 다음 list를 명령으로 처리해야 한다.
        data_dir = self.tmp / "shell_restore"
        self.run_cli(data_dir, "import", "--from", str(SAMPLE))
        result = self.run_easy(data_dir, input_text="삭제 tx-000002\n복구\nlist\nexit\n")
        self.assertEqual((result.returncode, result.stderr), (0, ""), result.stdout)
        self.assertIn("[복구 완료] id=TX-000002", result.stdout)
        self.assertIn("TX-000002 |", result.stdout)

    def test_core_restore_selects_id_and_duplicate_restore_keeps_saved_data(self) -> None:
        """기존 CLI의 옵션으로 이전 삭제를 고르고 중복 복구 오류 뒤에도 전체 거래를 보존한다."""
        data_dir = self.tmp / "ledger"
        self.run_cli(data_dir, "import", "--from", str(SAMPLE))
        original = {tx.id: tx for tx in build_services(data_dir).transactions.list_recent(20)}
        for tx_id in ("TX-000002", "TX-000004"):
            result = self.run_easy(data_dir, "delete", tx_id)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        for argv, tx_id in ((("restore", "--id", "TX-000002"), "TX-000002"), (("restore",), "TX-000004")):
            with self.subTest(argv=argv):
                result = subprocess.run(
                    [sys.executable, "-m", "budget_app", "--data-dir", str(data_dir), *argv],
                    capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=15,
                )
                self.assertEqual((result.returncode, result.stderr), (0, ""), result.stdout)
                self.assertIn(f"[복구 완료] id={tx_id}", result.stdout)
        self.assertEqual({tx.id: tx for tx in build_services(data_dir).transactions.list_recent(20)}, original)

        saved = (data_dir / "transactions.jsonl").read_bytes()
        code, lines, err = self.run_cli(data_dir, "restore", "--id", "TX-000002")
        self.assertEqual((code, lines), (1, []))
        self.assertIn("[오류]", err)
        self.assertIn("[힌트]", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual((data_dir / "transactions.jsonl").read_bytes(), saved)

    def test_restore_help_and_invalid_ids_never_restore_an_unintended_transaction(self) -> None:
        """복구 도움말은 파일을 만들지 않고 잘못된 번호·없는 이력은 거래를 바꾸지 않는다."""
        help_dir = self.tmp / "not_created_restore"
        for argv in (("restore", "--help"), ("복구", "--help"), ("help", "복구"), ("help", "restore")):
            with self.subTest(argv=argv):
                result = self.run_easy(help_dir, *argv)
                self.assertEqual((result.returncode, result.stderr), (0, ""), result.stdout)
                self.assertIn("restore", result.stdout)
                self.assertFalse(help_dir.exists())

        data_dir = self.tmp / "ledger"
        self.run_cli(data_dir, "import", "--from", str(SAMPLE))
        before = (data_dir / "transactions.jsonl").read_bytes()
        cases = [
            (("restore",), 1),
            (("복구", "TX-2"), 1),
            (("restore", "tx-999999"), 1),
            (("restore", "tx-000001", "tx-000002"), 2),
        ]
        for argv, expected_code in cases:
            with self.subTest(argv=argv):
                result = self.run_easy(data_dir, *argv)
                self.assertEqual(result.returncode, expected_code, result.stdout + result.stderr)
                self.assertTrue(result.stderr)
                self.assertNotIn("[복구 완료]", result.stdout)
                self.assertNotIn("Traceback", result.stdout + result.stderr)
                self.assertEqual((data_dir / "transactions.jsonl").read_bytes(), before)

    def test_delete_alias_help_and_original_cli_syntax_do_not_initialize_data(self) -> None:
        """한글 삭제 도움말은 저장소를 만들지 않고, 기존 CLI는 계속 --id를 요구한다."""
        data_dir = self.tmp / "not_created"
        for argv in (("삭제", "--help"), ("help", "삭제")):
            with self.subTest(argv=argv):
                result = self.run_easy(data_dir, *argv)
                self.assertEqual((result.returncode, result.stderr), (0, ""))
                self.assertIn("delete", result.stdout)
                self.assertFalse(data_dir.exists())

        result = subprocess.run(
            [sys.executable, "-m", "budget_app", "--data-dir", str(data_dir), "delete", "TX-000002"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=ROOT,
            timeout=15,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("--id", result.stderr)
        self.assertFalse(data_dir.exists())

    def test_group_choices_and_csv_paths_with_spaces(self) -> None:
        """예산·카테고리·반복 규칙 선택과 공백 경로의 CSV 입출력이 기존 저장소에 반영된다."""
        data_dir = self.tmp / "ledger"
        source_csv = self.tmp / "가져올 내역.csv"
        source_csv.write_bytes(SAMPLE.read_bytes())
        output_csv = self.tmp / "내보낸 내역.csv"
        result = self.run_easy(
            data_dir,
            input_text="\n".join([
                "category", "2", "카페 공간", "category", "",
                "budget", "2", "2024-01", "20000", "budget", "",
                "import", str(source_csv),
                f'export --out "{output_csv}" --month 2024-01',
                "recurring", "2", "31", "1", "etc", "500", "정기 지출", "",
                "recurring", "3", "2024-02", "recurring", "",
                "recurring", "4", "RC-000001", "exit", "",
            ]),
            module=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("category=카페 공간", result.stdout)
        self.assertIn("imported=5, skipped=1", result.stdout)
        self.assertIn("created=1, skipped=0", result.stdout)
        self.assertIn("[삭제 완료] id=RC-000001", result.stdout)
        with output_csv.open(encoding="utf-8", newline="") as handle:
            self.assertEqual(len(list(csv.DictReader(handle))), 5)
        svc = build_services(data_dir)
        self.assertIn("카페 공간", svc.categories.list_names())
        self.assertEqual(svc.budgets.summary("2024-01", 5).budget.amount, 20000)
        rows = svc.transactions.list_recent(20)
        self.assertEqual(len(rows), 6)
        self.assertTrue(any(row.date == "2024-02-29" and row.amount == 500 for row in rows))
        self.assertEqual(svc.recurring.list_all(), [])

    def test_malformed_commands_and_help_recover_to_next_command(self) -> None:
        """알 수 없는 명령·잘못된 옵션·닫히지 않은 따옴표를 입력해도 다음 조회를 실행한다."""
        data_dir = self.tmp / "ledger"
        result = self.run_easy(
            data_dir,
            input_text='unknown-command\nlist --limit zero\nsummary --month\n"닫히지 않음\nhelp add\nadd --help\nlist\nexit\n',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("거래가 없습니다", result.stdout)
        self.assertIn("add", result.stdout)
        self.assertTrue(result.stderr)
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        self.assertEqual(build_services(data_dir).transactions.list_recent(20), [])

    def test_full_launch_commands_and_short_list_show_the_same_limited_rows(self) -> None:
        """터미널용 실행 문장을 붙여도 짧은 조회와 같은 세 건만 출력하고 저장 파일을 바꾸지 않는다."""
        data_dir = self.tmp / "ledger"
        code, _, err = self.run_cli(data_dir, "import", "--from", str(SAMPLE))
        self.assertEqual((code, err), (0, ""))
        before = {path.name: path.read_bytes() for path in data_dir.glob("*.jsonl")}
        commands = [
            "list --limit 3",
            "python -m budget_app list --limit 3",
            "python3.12 -m budget_app list --limit 3",
            "python budget.py list --limit 3",
            "python3 -m budget_app.easy list --limit 3",
            f'"{sys.executable}" ./budget.py list --limit 3',
            "python3.12.exe -m budget_app list --limit 3",
        ]
        result = self.run_easy(data_dir, input_text="\n".join([*commands, "exit", ""]))
        self.assertEqual((result.returncode, result.stderr), (0, ""), result.stdout)
        # 각 입력의 출력 구간을 따로 확인해 일부 명령의 중복 실행도 찾아낸다.
        outputs = result.stdout.split("가계부> ")[1:-1]
        self.assertEqual(len(outputs), len(commands), result.stdout)
        expected_ids = [tx.id for tx in build_services(data_dir).transactions.list_recent(3)]
        for command, output in zip(commands, outputs):
            with self.subTest(command=command):
                ids = [line.split("|", 1)[0].strip() for line in output.splitlines() if line.startswith("TX-")]
                self.assertEqual(ids, expected_ids)
        self.assertEqual({path.name: path.read_bytes() for path in data_dir.glob("*.jsonl")}, before)

    def test_full_launch_mutations_execute_once_without_duplicate_transactions(self) -> None:
        """긴 추가·가져오기·수정·분류·삭제·복구 명령을 한 세션에서 각각 한 번만 처리한다."""
        data_dir = self.tmp / "ledger"
        source_csv = self.tmp / "가져올 예시.csv"
        source_csv.write_bytes(SAMPLE.read_bytes())
        result = self.run_easy(
            data_dir,
            input_text="\n".join([
                "python -m budget_app add", "2024-01-10", "1", "food", "1000", "python -m budget_app", "meal",
                f'python3.12 budget.py import --from "{source_csv}"',
                "python -m budget_app update --id TX-000001 --amount 2000",
                "python -m budget_app.easy category add cafe",
                "python -m budget_app delete --id tx-000002",
                "python budget.py 복구 tx-000002",
                'python -m budget_app search --q "python -m budget_app"', "list", "exit", "",
            ]),
            module=True,
        )
        self.assertEqual((result.returncode, result.stderr), (0, ""), result.stdout)
        for message in (
            "[저장 완료] id=TX-000001", "[완료] imported=5, skipped=1",
            "[수정 완료] id=TX-000001", "[저장 완료] category=cafe",
            "[삭제 완료] id=TX-000002", "[복구 완료] id=TX-000002",
        ):
            with self.subTest(message=message):
                self.assertEqual(result.stdout.count(message), 1, result.stdout)
        svc = build_services(data_dir)
        rows = svc.transactions.list_recent(20)
        self.assertEqual(len(rows), 6)
        self.assertEqual({tx.id for tx in rows}, {f"TX-{number:06d}" for number in range(1, 7)})
        added = next(tx for tx in rows if tx.id == "TX-000001")
        self.assertEqual((added.amount, added.memo, added.tags), (2000, "python -m budget_app", ["meal"]))
        # 실행 문장이 메모나 검색값에 들어 있으면 일반 데이터로 그대로 유지한다.
        self.assertEqual(result.stdout.count("| python -m budget_app"), 2)
        self.assertEqual(svc.categories.list_names().count("cafe"), 1)
        self.assertEqual(len((data_dir / "backups" / "deleted.jsonl").read_text(encoding="utf-8").splitlines()), 1)

    def test_full_launch_data_dir_override_applies_to_only_one_command(self) -> None:
        """실행 문장의 저장 폴더는 해당 작업에만 적용하고 다음 짧은 명령은 세션 폴더를 사용한다."""
        data_dir = self.tmp / "기본 가계부"
        alternate = self.tmp / "다른 가계부"
        for directory, memo in ((data_dir, "기본 내역"), (alternate, "다른 내역")):
            build_services(directory).transactions.add(
                date="2024-01-10", type_="expense", category="food", amount="1000", memo=memo, tags="",
            )
        before = {path.name: path.read_bytes() for path in data_dir.glob("*.jsonl")}
        result = self.run_easy(
            data_dir,
            input_text="\n".join([
                "python -m budget_app list",
                f'python -m budget_app --data-dir "{alternate}" list',
                f'python budget.py --data-dir "{alternate}" add',
                "2024-01-11", "1", "food", "2000", "다른 폴더에 추가", "",
                "list", "exit", "",
            ]),
        )
        self.assertEqual((result.returncode, result.stderr), (0, ""), result.stdout)
        self.assertEqual(result.stdout.count("| 기본 내역"), 2)
        self.assertEqual(result.stdout.count("| 다른 내역"), 1)
        self.assertNotIn("| 다른 폴더에 추가", result.stdout)
        self.assertEqual({path.name: path.read_bytes() for path in data_dir.glob("*.jsonl")}, before)
        other_rows = build_services(alternate).transactions.list_recent(20)
        self.assertEqual({tx.memo for tx in other_rows}, {"다른 내역", "다른 폴더에 추가"})

    def test_full_launch_help_and_unsupported_python_commands_preserve_data(self) -> None:
        """실행 부분만 입력하면 도움말을 보여주고 다른 Python 실행·연결 문장·중첩 실행은 거부한다."""
        help_dir = self.tmp / "도움말은 미생성"
        result = self.run_easy(
            help_dir,
            input_text="\n".join([
                "python -m budget_app", "python budget.py", "python3 -m budget_app.easy",
                "python -m budget_app --help", "python budget.py list --help", "exit", "",
            ]),
        )
        self.assertEqual((result.returncode, result.stderr), (0, ""), result.stdout)
        self.assertIn("list", result.stdout)
        self.assertFalse(help_dir.exists())

        data_dir = self.tmp / "ledger"
        self.run_cli(data_dir, "import", "--from", str(SAMPLE))
        before = {path.name: path.read_bytes() for path in data_dir.glob("*.jsonl")}
        marker = self.tmp / "python_must_not_run.txt"
        unsupported = [
            f'python -c "open(\'{marker}\', \'w\').write(\'실행됨\')"',
            "python -m this", "python other.py", "python -u -m budget_app list",
            "python -m budget_app python -m budget_app list",
            "python -m budget_app list --limit 1 && python -m budget_app delete --id TX-000001",
            "python -m budget_app list --limit 1 ; python -m budget_app delete --id TX-000001",
        ]
        result = self.run_easy(data_dir, input_text="\n".join([*unsupported, "list --limit 1", "exit", ""]))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result.stderr)
        self.assertEqual(result.stdout.count("[안내] 작업을 마치지 못했습니다."), len(unsupported), result.stdout)
        outputs = result.stdout.split("가계부> ")[1:-1]
        self.assertEqual(len(outputs), len(unsupported) + 1, result.stdout)
        for command, output in zip(unsupported, outputs):
            with self.subTest(command=command):
                self.assertFalse(any(line.startswith("TX-") for line in output.splitlines()), output)
        self.assertTrue(any(line.startswith("TX-") for line in outputs[-1].splitlines()), result.stdout)
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        self.assertNotIn("[삭제 완료]", result.stdout)
        self.assertFalse(marker.exists())
        self.assertFalse((data_dir / "backups").exists())
        self.assertEqual({path.name: path.read_bytes() for path in data_dir.glob("*.jsonl")}, before)

    def test_eof_at_command_prompt_is_success_and_during_input_is_interruption(self) -> None:
        """명령 대기 EOF는 0, 거래 입력 중 EOF는 두 진입점 모두 130이며 미완성 거래를 저장하지 않는다."""
        for module in (False, True):
            with self.subTest(module=module):
                data_dir = self.tmp / ("module" if module else "script")
                result = self.run_easy(data_dir, module=module)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(data_dir.exists())

                result = self.run_easy(data_dir, input_text="add\n2024-01-01\n", module=module)
                self.assertEqual(result.returncode, 130, result.stdout + result.stderr)
                self.assertNotIn("Traceback", result.stdout + result.stderr)
                transactions = data_dir / "transactions.jsonl"
                if transactions.exists():
                    self.assertEqual(transactions.read_text(encoding="utf-8"), "")

    def test_injected_interrupt_windows_path_and_empty_memo_argument(self) -> None:
        """공개 입력 훅으로 Ctrl+C를 주입한 뒤 작업을 계속하고, 역슬래시와 빈 옵션 값을 보존한다."""
        data_dir = self.tmp / "ledger"
        windows_path = r"C:\Users\name\My Files\missing.csv"
        events = [
            "add", None,
            f'import --from "{windows_path}"',
            "add", "2024-01-10", "1", "food", "1000", "원본 메모", "",
            "update", "TX-000001", "2", "--help", "search", "--help",
            'update --id TX-000001 --memo ""', "list", "exit",
        ]
        script = f'''from __future__ import annotations
import sys
from budget_app.easy import main
events = iter({events!r})
def read(prompt: str) -> str:
    print(prompt, end="", flush=True)
    try:
        answer = next(events)
    except StopIteration:
        raise EOFError from None
    if answer is None:
        raise KeyboardInterrupt
    return answer
sys.exit(main(sys.argv[1:], input_fn=read))
'''
        result = subprocess.run(
            [sys.executable, "-c", script, "--data-dir", str(data_dir)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=ROOT,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(windows_path, result.stderr)
        self.assertIn("| --help", result.stdout)
        self.assertNotIn("expected one argument", result.stderr)
        self.assertIn("[수정 완료] id=TX-000001", result.stdout)
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        rows = build_services(data_dir).transactions.list_recent(20)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].memo, "")
        self.assertEqual(rows[0].amount, 1000)


if __name__ == "__main__":
    unittest.main()
