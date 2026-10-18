"""cli 계층 테스트: 진입점(entry) 을 직접 호출해 CSV 라운드트립과 종료 코드를 시나리오 단위로 확인한다 (AGENT.md 9장 P6, 10장)."""
from __future__ import annotations

import contextlib
import csv
import io
import tempfile
import unittest
from pathlib import Path

from budget_app.__main__ import entry
from budget_app.services import build_services

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "samples" / "import_sample.csv"
HEADER = ["date", "type", "category", "amount", "memo", "tags"]


class CliTestCase(unittest.TestCase):
    def setUp(self) -> None:
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
        svc = build_services(data_dir)
        return {(t.date, t.type, t.category, t.amount, t.memo, ",".join(t.tags)) for t in svc.transactions.list_recent(1000)}


class RoundTripScenario(CliTestCase):
    """샘플 import → export → 빈 폴더에 import 하면 건수와 필드가 같다 (D19, D20, D41)."""

    def test_import_export_roundtrip(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
