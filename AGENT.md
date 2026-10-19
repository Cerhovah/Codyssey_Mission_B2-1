# AGENT.md — budget_app 명세 주도 개발 지침

버전 1.5 / 기준일 2026-10-19 / 대상: 이 저장소에서 코드를 작성하는 모든 AI 에이전트와 사람

## 1. 목적과 읽는 순서

이 저장소는 Codyssey Mission B2-1 "나만의 용돈 기입장" 콘솔 가계부를 **명세 주도 개발(SDD)** 로 완성한다. 문서가 진실의 원천이고 코드는 문서의 산출물이다. 작업을 시작하기 전에 아래 세 문서를 순서대로 끝까지 읽는다.

1. [docs/MISSION_SPEC.md](docs/MISSION_SPEC.md) — 과제 명세 원문. **수정 금지.** 모든 요구의 근거.
2. [README.md](README.md) — 명세 심층 분석(요구사항 R01~R25, B1~B4), 사용자 관점 사양(실행·저장·명령·CSV·종료 코드), 진행 현황.
3. 이 문서 — 헌장(불변 규칙), 결정표 D01~D49, 계층·계약, Phase 계획, 검증 정책, Git 규칙.

세 문서가 충돌하면 우선순위는 **원문 > 이 문서의 결정표 > README 사양 > 코드**다. 원문이 모호한 부분은 결정표가 해소한다. 결정표에 없는 모호함을 만나면 추측해서 구현하지 않고, 결정표에 D50부터 새 항목을 추가한 뒤 구현한다.

## 2. 명세 주도 개발 원칙 (이 저장소의 SDD 해석)

- **Spec-first, then spec-anchored.** 명세와 결정표가 먼저 있고, 구현 후에도 문서를 코드와 함께 유지한다. 동작을 바꾸려면 결정표나 README 사양을 먼저 고치고 같은 커밋에 코드를 반영한다. 코드만 고치고 문서를 남겨 두는 커밋은 금지한다.
- **추측 대신 결정.** Spec Kit의 `[NEEDS CLARIFICATION]` 표식에 해당하는 것이 이 저장소의 결정표다. 모호한 요구는 "Don't guess" 원칙에 따라 결정표에 먼저 기록한다.
- **작게 나누되, 검증은 한 번.** Atlassian의 규칙 "Break large requests into small, verifiable steps"를 따르되, 이 과제는 커밋·푸시 **10회 이내** 제약이 있으므로 단계는 9개로 크게 묶고 각 단계의 검증은 **게이트 하나**(`python scripts/verify.py`)로 끝낸다.
- **문서 과잉 금지.** Böckeler가 경고한 "sledgehammer to crack a nut"를 피한다. 문서는 세 개(원문 / README / AGENT)로 고정한다. 새 마크다운, 계획 파일, ADR 폴더를 만들지 않는다. 설계 메모가 필요하면 이 문서의 해당 장을 수정한다.
- **개발자는 검토자.** 산출물을 만든 뒤 반드시 게이트를 실제로 실행하고 결과를 보고 다음 단계로 간다. 파일을 만들었다는 이유로 완료를 선언하지 않는다.
- **범위 고정.** 요구사항 매트릭스(README 1.3)와 결정표에 없는 기능은 만들지 않는다. 좋은 아이디어라도 D31+에 기록하고 사용자 승인 없이는 구현하지 않는다.

## 3. 헌장 (Constitution) — 어떤 Phase에서도 바꾸지 않는 규칙

| # | 규칙 | 근거 |
| --- | --- | --- |
| C1 | **표준 라이브러리만** 사용한다. `pip install`이 필요한 패키지는 테스트·도구를 포함해 전면 금지. 테스트 러너는 `unittest`. | 원문 7장 |
| C2 | Python **3.10 이상** 문법만. `match` 문과 `X \| Y` 타입은 허용, 3.11+ 전용 기능(`tomllib`, `ExceptionGroup`, `Self`)은 금지. | 원문 6장 |
| C3 | 저장 포맷은 **JSONL**. 활성 파일은 기본 3개(`transactions.jsonl`, `categories.jsonl`, `budgets.jsonl`) + 반복 내역 `recurring.jsonl`(D44, 원문 "3개 이상" 충족). 삭제 복구용 `backups/deleted.jsonl`은 D47의 보관 이력으로 허용한다. 그 외 카운터·메타 파일 추가 금지. | 원문 4-3, D01, D05, D44, D47 |
| C4 | 옵션은 **`--long` 형식만**. 단축 옵션(`-l`)을 만들지 않는다. | 원문 4-1, 7장 |
| C5 | 저장소 읽기는 **전부 제너레이터**(`yield`). `readlines()`, `json.load(전체)`, 리스트 변환 후 처리 금지. 정렬이 필요하면 `heapq.nlargest` 또는 필터 후 부분집합 정렬만 허용. | 원문 4-5, 4-7 |
| C6 | 파일 재작성은 **임시 파일 + `os.replace`**. 원본을 직접 열어 덮어쓰지 않는다. | 원문 4-6, 보너스 4 |
| C7 | **스택트레이스 출력 금지.** 모든 오류는 `[오류] 원인` / `[힌트] 해결` 두 줄. 종료 코드 0/1/2/130 고정. | 원문 4-13, 7장 |
| C8 | 데코레이터 `handle_errors`, `log_call`, `timed` 를 구현하고 **실제 적용**한다. 장식용으로 정의만 해 두지 않는다. | 원문 4-12 |
| C9 | **모든 함수·메서드에 타입 힌트.** 파일 첫 줄에 `from __future__ import annotations`. `Any`는 JSON 경계에서만. | 원문 3장 |
| C10 | 모듈 책임 분리: `cli → services → repository → models` 단방향. 역방향 import 금지. `cli`에서 파일을 직접 열지 않는다. | 원문 4-14 |
| C11 | 사용자 메시지·주석·docstring은 **한국어**, 식별자·JSON 키·CSV 헤더는 영어. 파일은 UTF-8(BOM 없음), LF. | 프로젝트 관례 |
| C12 | `data/`, 백업, 내보낸 CSV, `__pycache__`는 커밋하지 않는다. 샘플 CSV만 `samples/`에 둔다. | 안전 |

## 4. 결정표 (모호성 해소) — D01~D49

원문이 선택을 맡기거나 침묵한 지점의 **고정 결정**이다. 구현은 이 표를 따른다. 바꾸려면 표를 먼저 고친다.

| ID | 주제 | 결정 | 이유 |
| --- | --- | --- | --- |
| D01 | 저장 포맷 | JSONL. 1줄 = JSON 객체 1개, `ensure_ascii=False`, UTF-8, LF | tags 리스트·메모 쉼표 안전, append 1줄, 스트리밍 자연 |
| D02 | 옵션 표기 | 롱 옵션만. 원문의 `-limit`, `-from`, `-top`, `-data-dir`는 `--`의 표기 손실로 해석 | 원문 4-1 "`--`로 통일" |
| D03 | update 방식 | **옵션 기반(안 A)** 고정. `update --id <id> [--date] [--type] [--category] [--amount] [--memo] [--tags]`. 최소 1개 필요 | 스크립트·테스트 가능, 검증 단위 최소화 |
| D04 | 빈 카테고리 | **안 A** 기본 카테고리 자동 생성: `food, transport, rent, salary, etc` | 첫 실행에서 바로 add 가능, 예시 화면의 salary 포함 |
| D05 | id 규칙 | `TX-` + 6자리 0패딩. 다음 번호 = 스트리밍으로 구한 최대 번호 + 1. 999999 초과 시 7자리로 자연 확장 | 메타 파일 없이 3파일 유지. 유일성은 항상 보장 (삭제 후 번호 재사용 가능함은 문서화된 한계) |
| D06 | "최신순" | `date` 내림차순, 같은 날짜는 `id` 내림차순 | 입력 순서보다 거래일이 사용자 기대에 맞음 |
| D07 | 스트리밍 + 정렬 | list: `heapq.nlargest(limit, gen, key=(date, id))`. search: 필터 통과 레코드만 모아 정렬, `--limit` 선택 지원(기본 무제한) | 전체 로드 금지와 최신순 요구를 동시에 충족 |
| D08 | amount | 양의 **정수**만. `int(str)` 성공 + `> 0`. 소수·쉼표·`+` 기호 거부 | CSV 스키마 "양수 정수"와 일치 |
| D09 | date | `datetime.strptime(s, "%Y-%m-%d")` 엄격 검증. `2024-1-5` 거부 | 원문 YYYY-MM-DD |
| D10 | type | `income` / `expense`. 입력은 strip + lower 후 비교 | 사용자 편의, 저장은 소문자 고정 |
| D11 | tags | 쉼표 분리 → strip → 빈 값 제거 → 순서 유지 중복 제거. JSONL은 리스트, CSV는 `"a,b"` | 원문 CSV 스키마 |
| D12 | category 모델 | `{"name": str}` 하나. 수입/지출 타입 구분 없음. 대소문자 구분, strip, 빈 문자열 금지, 중복 등록 오류 | 원문이 타입 구분을 요구하지 않음 |
| D13 | 검증 실패 처리 | 대화형: `[오류]`+`[힌트]` 출력 후 **같은 항목 재입력**(제한 없음). 옵션형: 즉시 종료 코드 1. Ctrl+C/EOF: `[안내] 중단했습니다` 후 130 | 원문 4-2 "재입력 요구 또는 오류 메시지" |
| D14 | 종료 코드 | 0 정상 / 1 입력·도메인·파일 오류 / 2 argparse 사용법 오류 / 130 사용자 중단 | 원문 4-13 |
| D15 | 오류 포맷 | `[오류] {원인}` 줄바꿈 `[힌트] {힌트}`. 힌트가 없으면 두 번째 줄 생략. 예기치 않은 예외는 `[오류] 예기치 않은 오류: {type}` + `--verbose` 안내, 종료 1 | 원문 7장 |
| D16 | summary 데이터 없음 | 해당 월 거래 0건 → `[안내] {YYYY-MM} 데이터 없음`, 종료 0. 예산이 있으면 `예산: N원 (사용률 0.0%)` 한 줄 추가 | 원문 4-8 |
| D17 | 예산 사용률 | `총지출 / 예산 * 100`, 소수 1자리. 지출 > 예산이면 다음 줄 `[경고] 예산 초과: +{차액}원` | 원문 4-9 |
| D18 | category remove | 사용 중이면 기본 **차단**(종료 1, 건수 안내). `--replace <name>` 지정 시 해당 거래를 재배정(원자적 재작성) 후 삭제. 대체 카테고리는 존재해야 하고 자기 자신 불가. 미사용이면 바로 삭제 | 원문 4-10 두 선택지 모두 충족 |
| D19 | import | 행 단위 검증. 유효 행은 저장, 실패 행은 `  - {행번호}행: {사유}` 출력. 미등록 카테고리는 skip(자동 생성 안 함). 요약 `[완료] imported=N, skipped=M`, skipped>0 이어도 종료 0. 파일 없음·헤더 불일치는 저장 없이 종료 1 | 부분 성공을 명확히 보고 |
| D20 | export | `--month` 또는 `--from`/`--to` 중 하나 이상 필수(없으면 argparse error → 2). 열 고정 `date,type,category,amount,memo,tags`, id 제외. `newline=""`, UTF-8 BOM 없음. 0건도 헤더만 있는 파일 생성, `[완료] {파일} (0 records)` | 원문 4-11 |
| D21 | 재작성 방식 | `tempfile.NamedTemporaryFile(dir=같은 폴더, delete=False)` → 전체 쓰기 → `flush` + `os.fsync` → `os.replace(tmp, target)`. 실패 시 임시 파일 삭제, 원본 유지 | C6, 보너스 4 |
| D22 | 데코레이터 | `handle_errors`: CLI 진입 함수에 적용, `AppError`→메시지+코드, `KeyboardInterrupt/EOFError`→130, 그 외→D15. `log_call`: 서비스 공개 메서드에 적용, 호출명·인자 요약 DEBUG 로그. `timed`: list/search/summary/import/export에 적용, 경과 ms DEBUG 로그 | C8 |
| D23 | 데이터 폴더 | 전역 옵션 `--data-dir PATH` (서브커맨드 **앞**), 기본 `./data`. 없으면 생성 + `[안내] 저장 폴더를 초기화했습니다: {path}` 1회 출력 | 원문 4-3 |
| D24 | 테스트 러너 | `unittest` 만. 테스트 파일은 계층당 1개(총 4개 이하). 단일 게이트 `scripts/verify.py` 가 unittest + CLI 스모크를 순서대로 실행 | C1, 검증 최소화 |
| D25 | budget 조회 | `budget list` 추가(월 오름차순). `budget set`은 같은 달 덮어쓰기. amount는 D08과 동일 검증 | 원문 2-5 "설정/조회" |
| D26 | category add 입력 | 위치 인자 `category add [name]` 선택. 없으면 대화형 `카테고리명: ` 프롬프트 | 원문 예시는 대화형, 스크립트 편의 추가 |
| D27 | 기본값 | `list --limit` 20, `summary --top` 5, `search --limit` 무제한 | 원문 "기본값 제공" |
| D28 | search 의미 | `--q` 메모 부분 일치(대소문자 무시), `--tag` 태그 정확 일치, `--from/--to` 포함 범위, 모든 조건 AND. 0건은 `[안내] 조건에 맞는 거래가 없습니다`, 종료 0 | 원문 4-7 |
| D29 | 보너스 범위 | P7에서 테이블 정렬(B3)과 backup(B1)만 필수. 반복 내역(B2)은 P7 에 넣지 않았고, 사용자 결정(2026-10-18)으로 남은 예비 커밋(P9)에서 D44 로 구현 | 커밋 수 제한 |
| D30 | 콘솔 인코딩 | 진입점에서 `sys.stdout/stderr/stdin.reconfigure(encoding="utf-8")` 시도(실패 무시). 모든 파일 I/O `encoding="utf-8"` 명시 | Windows cp949 대비 |
| D31 | 옵션형 `--type` 검증 위치 | `search --type`, `update --type` 은 argparse `choices` 로 제한하지 않고 서비스에서 `parse_type`(D10, strip + lower)로 검증한다. 실패는 종료 1 | D10의 관용 규칙(`Expense` 허용)을 옵션형에도 동일 적용, 검증 로직을 models 한 곳에 유지 |
| D32 | 숫자 옵션의 검증 위치 | `--limit`·`--top` 은 argparse `type=positive_int` 로 검증(비정수·0·음수 → 사용법 오류, 종료 2). `--amount`·`--id`·날짜·월 옵션은 문자열로 받아 서비스에서 D08/D09 로 검증(종료 1) | 출력 건수는 사용법의 일부이고, 금액·날짜는 데이터 입력값이므로 종료 코드로 구분 |
| D33 | 손상 줄 판정과 변환 위치 | JSON 파싱 실패, JSON 객체가 아닌 줄, `from_dict` 의 ValidationError(필수 키 누락·타입 불일치), 거래 id 형식 불일치(`TX-` + 숫자 6자리 이상) 는 모두 `StorageError("저장 파일 {파일명} {n}행이 손상되었습니다", hint="해당 줄을 수정하거나 backup에서 복구하세요")` 로 종료 1. 행 번호 n 은 빈 줄을 포함한 물리적 줄 번호. 변환은 `JsonlStore.iter_parsed(from_dict)` 한 곳에서 하고, models 는 그대로 ValidationError 만 던진다 | 6장 계약 구현. 파일이 3개이므로 파일명을 포함해야 사용자가 고칠 줄을 찾을 수 있음 |
| D34 | 저장 파일 부재와 OSError | 읽기(`iter_records`)에서 파일이 없으면 빈 파일로 취급(0건). `append` 는 파일을 새로 만든다. 폴더가 없거나 권한·디스크 오류 등 `OSError` 는 repository 에서 `StorageError(원인, hint="폴더와 권한을 확인하세요: {경로}")` 로 감싼다. `rewrite` 는 임시 파일을 `.{파일명}.*.tmp` 로 같은 폴더에 만들고, 실패 시 삭제 후 원본을 그대로 둔다. 레코드 제너레이터가 던진 AppError 와 그 외 예외는 감싸지 않고 그대로 올린다 | `ensure_initialized` 전에 Store 를 직접 쓰는 테스트·서비스가 안전해야 함. 8장 "표준 예외는 그 자리에서 AppError 로 감싼다" |
| D35 | 저장소 수준 무결성과 초기화 반환값 | `CategoryStore.add` 는 이름을 `parse_category_name` 으로 정규화하고 중복이면 ConflictError, `remove` 는 없는 이름이면 NotFoundError(사용 중 여부 검사는 서비스 책임, D18). `BudgetStore.set` 은 같은 달을 자리 그대로 덮어쓴다. `ensure_initialized(data_dir)` 는 폴더·파일 3개 중 하나라도 새로 만들었을 때만 True 를 돌려주고(기본 카테고리만 채운 경우는 False), `[안내]` 출력은 반환값을 받은 cli 계층이 P3 에서 한다. 기본 카테고리는 카테고리 파일에 레코드가 0건일 때 D04 순서대로 등록한다 | 유일성은 저장 파일의 불변 조건이라 저장소가 지킨다. repository 는 print 하지 않음(5장) |
| D36 | 초기화 호출 위치와 안내 출력 | `services.build_services(data_dir)` 가 모든 명령 진입에서 `ensure_initialized` 를 호출하고 결과를 `Services.initialized` 로 돌려준다. `cli.main` 은 서비스 조립 직후 그 값이 True 일 때만 `[안내] 저장 폴더를 초기화했습니다: {--data-dir 인자 그대로}` 를 stdout 에 1회 출력한 뒤 명령을 실행한다. `--help`·사용법 오류(종료 2)는 서비스 조립 전에 끝나므로 폴더를 만들지 않는다 | C10(cli 는 repository 를 import 하지 않음), D23 |
| D37 | 대화형 프롬프트 규약 | add 는 `날짜(YYYY-MM-DD): `, `타입(income/expense): `, `카테고리: `, `금액(양수 정수): `, `메모(선택): `, `태그(쉼표로 구분, 없으면 엔터): ` 순서로 `input_fn` 을 호출한다. 각 항목은 `models.parse_*`(날짜·타입·금액·메모·태그)와 `CategoryService.require`(카테고리 존재, 힌트에 등록 목록) 로 검증하고, ValidationError/NotFoundError 면 `[오류]`/`[힌트]` 두 줄을 **stdout** 에 쓴 뒤 같은 항목을 다시 묻는다(D13). 그 외 예외는 올린다. 저장은 `TransactionService.add` 가 다시 한 번 검증한다 | 프롬프트와 오류가 같은 스트림에 있어야 순서가 보존됨. cli 는 검증을 구현하지 않고 호출만 한다(5장) |
| D38 | search 조건 세부 | `--from/--to` 는 `parse_date` 로 검증(종료 1)하고 `--from` 이 `--to` 보다 늦으면 ValidationError(종료 1). `--category`·`--tag` 는 strip 후 정확 일치(등록 여부는 검사하지 않음 → 미등록이면 0건). `--q` 는 strip 후 `casefold` 부분 일치. strip 결과가 빈 문자열인 조건은 "조건 없음" 으로 본다. 필터는 제너레이터로 통과분만 모아 `(date, id)` 내림차순 정렬, `--limit` 이 있으면 `heapq.nlargest` | D28 보완. 검색은 조회이므로 카테고리 등록 검사를 강제하지 않음 |
| D39 | summary 집계 세부 | 한 번의 순회로 수입 합·지출 합·건수(수입+지출)·카테고리별 지출 합을 구한다. TOP 은 지출 합 내림차순, 같으면 이름 오름차순, `--top` 개까지. 지출 카테고리가 N 개 미만이어도 헤더는 `지출 TOP N` 그대로 두고 있는 만큼만 나열(수입만 있는 달은 헤더만). 사용률·초과 계산은 cli 가 `MonthlySummary` 값으로 한다(D17). `budget list` 는 월 문자열 오름차순 | D16·D17 보완. 집계와 표시의 책임 분리(5장) |
| D40 | update/delete/remove 처리 순서 | `--id` 는 `transaction_number` 로 형식 검증(형식 오류 ValidationError, 종료 1). update 는 (1) 주어진 옵션 값을 add 와 같은 `parse_*`·`require_category` 로 먼저 검증, (2) `iter_all` 스트리밍으로 대상 존재 확인(없으면 `NotFoundError("거래를 찾을 수 없습니다: {id}", hint="python -m budget_app list 로 id를 확인하세요.")`, 파일 미변경), (3) `rewrite` 1회. `--memo ""`·`--tags ""` 는 비움. delete 도 (2)→(3). category remove 는 (1) 이름 존재(없으면 NotFoundError), (2) `--replace` 가 있으면 존재 검사 + 자기 자신 금지(ValidationError), (3) 사용 건수 스트리밍 1회, (4) 사용 중 + `--replace` 없음 → `ConflictError("'{name}'를 사용하는 거래가 {n}건 있어 삭제할 수 없습니다.", hint="--replace <대체카테고리> 를 지정하면 해당 거래를 옮긴 뒤 삭제합니다.")`, 사용 중 + `--replace` → 재배정 rewrite 후 삭제, 미사용 → `--replace` 유무와 무관하게 바로 삭제(이동 0건) | D03·D18 보완. 검증은 전부 파일을 건드리기 전에 끝내고, 재작성은 명령당 최대 1회 |
| D41 | import/export 세부 | **export**: `--month` 와 `--from/--to` 를 함께 주면 AND. 조건은 D38 과 같이 검증(`--from` > `--to` 종료 1). 통과분을 `(date, id)` 내림차순으로 `csv.writer`(`newline=""`, `lineterminator="
"` 으로 LF 고정, UTF-8 BOM 없음) 에 쓰고, 출력 파일의 폴더가 없으면 `StorageError`(자동 생성 안 함). **import**: 파일 없음은 `StorageError("가져올 파일을 찾을 수 없습니다: {path}")` 종료 1. `utf-8-sig` 로 열어 BOM 을 허용하고, `csv.DictReader` 의 헤더에 필수 6열(`date,type,category,amount,memo,tags`, 이름 정확 일치) 이 모두 없으면 `ValidationError`(힌트에 필수 헤더) 로 저장 없이 종료 1. 열 순서는 무관하고 추가 열은 무시. 행 번호는 `reader.line_num`(헤더 1행, 첫 데이터 2행, 따옴표 안 줄바꿈 포함). 각 행은 `parse_*`·`require_category` 로 검증하고 AppError 의 `message` 를 skip 사유로 쓴다. 비어 있거나 모자란 열은 빈 문자열로 본다. id 는 `next_id` 로 시작 번호를 1회 구한 뒤 유효 행마다 +1 하여 `append` | D19·D20 보완. 대량 import 에서 next_id 재스캔(O(n²)) 회피 |
| D42 | 테이블 정렬 (B3) | list/search/budget list 는 `formatting.format_transaction_table(rows)` / `format_budget_table(budgets)` 로 출력한다. 열 순서 `id \| date \| type \| category \| amount \| memo`, 구분자 ` \| `, id·date·type·category 좌정렬, amount 우정렬, 마지막 열(memo·금액원) 은 패딩 없음. 열 너비는 그 명령의 결과 리스트에서 계산하며, 너비 계산은 `unicodedata.east_asian_width` 가 W/F 인 문자를 2칸으로 센다. type 열 최소 너비 7. 결과는 `--limit`(list) 또는 필터 통과분(search) 으로 이미 메모리에 있는 소량 리스트이므로 렌더 전 너비 계산은 C5 위반이 아니다. 금액은 천 단위 구분 없이 숫자 그대로(README 5장 예시·스모크와 일치). 단일 행 함수 `format_transaction_row`/`format_budget_row` 는 호환용으로 남긴다 | 원문 보너스 3. 한글 메모·카테고리가 있어도 열이 어긋나지 않음 |
| D43 | backup (B1) 과 B2 | `backup` 은 `{data_dir}/backups/{YYYYMMDD-HHMMSS}/` 를 만들고 저장 파일 4개(D44 포함)를 `shutil.copy2` 로 복사한다(`repository.backup_files`). 같은 초에 다시 실행해 폴더가 이미 있으면 `-1`, `-2`, … 접미사를 붙여 덮어쓰지 않는다. 출력 `[완료] {경로} (4 files)`. 복사 실패는 StorageError. 반복 내역(B2) 은 예비 커밋에서 D44 로 구현했다(C3 개정) | 원문 보너스 1, D29 |
| D44 | 반복 내역 (B2) | 저장 파일 `recurring.jsonl`(4번째, C3 개정). 레코드 `{"id":"RC-000001","day":25,"type":"income","category":"salary","amount":3000000,"memo":"월급","tags":[]}`, 모델 `RecurringRule`, id 는 `RC-` + 6자리(TX 와 같은 규칙: 스트리밍 최대 + 1, 삭제 후 재발급 가능), `day` 는 1~31 정수(`parse_day`). 명령 `recurring add`(대화형: `매월 며칠(1~31): `, 타입, 카테고리, 금액, 메모, 태그 — add 와 같은 `ask` 루프·검증), `recurring list`(`id \| 매월 N일 \| type \| category \| amount \| memo` 테이블, 0건 `[안내] 등록된 반복 내역이 없습니다`), `recurring remove --id RC-xxxxxx`(형식 오류 ValidationError, 없는 id `NotFoundError("반복 내역을 찾을 수 없습니다: {id}")` 종료 1, 성공 `[삭제 완료] id=RC-000001`), `recurring apply --month YYYY-MM`: 규칙 0건이면 `[안내] 등록된 반복 내역이 없습니다` 종료 0. 거래 파일을 1회 스트리밍해 해당 월에 `rc:{규칙id}` 태그가 있는 규칙 집합을 만든 뒤, 규칙마다 (이미 적용 → skip `{월} 에 이미 적용됨 ({거래id})`, 미등록 카테고리 → skip 사유 = NotFoundError 메시지) 아니면 날짜 `{월}-{min(day, 말일):02d}`(`calendar.monthrange`), 태그 = 규칙 태그 + `rc:{규칙id}`, id 는 `next_id` 1회 후 +1 로 append. 출력 `[완료] {월} 반복 내역 적용 created=N, skipped=M` + skip 사유 줄 `  - RC-000001: {사유}`. `ensure_initialized` 는 4개 파일을 만들고 `backup` 은 4개를 복사(`(4 files)`) | 원문 보너스 2. 사용자 결정(2026-10-18)으로 남은 예비 커밋 1회를 사용. 중복 생성 방지는 거래 자체에 남는 `rc:` 태그로 하여 추가 메타 파일을 두지 않음 |

### D45 — 간편 실행 모듈 (사용자 요청 2026-10-19)

- 기존 폴더와 핵심 코드는 유지하고 `budget.py`(실행 파일), `budget_app/easy.py`(간편 CLI) 두 파일만 추가한다. 표준 라이브러리만 사용한다.
- `python budget.py` 또는 `python -m budget_app.easy`로 대화형 모드에 들어간다. 이후 `add`, `list`, `search`, `summary`, `budget`, `category`, `update`, `delete`, `import`, `export`, `backup`, `recurring`, `help`, `exit`를 입력한다. `도움말`, `종료`도 지원한다. `python budget.py add`처럼 한 번 실행하는 방식도 제공한다.
- 옵션 없이 입력한 명령은 필요한 값을 질문한다. 날짜·월은 오늘·이번 달을 기본값으로 제안하고, 수입·지출과 카테고리는 번호 선택을 제공한다. `search`는 메모 키워드를 질문한다. 그룹 명령은 하위 작업을 선택한다. `update`는 변경할 필드와 값을 질문한 뒤 기존 옵션형 명령으로 전달한다(D03 유지). 옵션을 직접 지정한 명령은 기존 CLI 형식과 검증을 따른다.
- 간편 모듈은 기존 `cli.build_parser`/`dispatch`, 서비스·모델 검증, `handle_errors`를 재사용한다. 저장 형식·폴더 기본값은 동일하고, 도움말·잘못된 명령은 저장 폴더를 만들지 않는다. `--data-dir`, `--verbose`는 실행 시 지정해 세션 내에서 유지한다.
- 셸의 명령 입력은 따옴표와 Windows 경로의 백슬래시를 보존한다. 데이터 질문의 답은 한 줄 전체를 사용한다. 명령 실패·사용법 오류·Ctrl+C는 해당 작업만 취소하고 셸을 유지한다. 명령 대기 중 EOF 또는 `exit`는 정상 종료, 데이터 입력 중 EOF는 중단 코드 130이다.
- 검증은 기존 `tests/test_cli.py`에 실제 프로세스 시나리오를 추가하고 `scripts/verify.py` 게이트로 실행한다. README에 간편 사용법과 실제 검증 결과를 반영한다. 이번 요청은 완료된 P0~P9 이후의 확장이므로 원래 10회 구현 한도와 구분해 한 번 커밋·푸시한다. 사용자가 `main` 커밋·푸시를 명시 승인했다.
- 로컬 Git 인증 연결이 끊긴 경우 연결된 GitHub 앱으로 같은 저장소의 권한을 확인한 뒤 검증된 트리를 한 번 커밋하고 `main`을 fast-forward 갱신할 수 있다. 이후 로컬 `main`도 해당 커밋으로 동기화한다. 공동 작성자 표기는 실제 사용한 도구를 따른다.

### D46 — 간편 모드 삭제 입력 보완 (사용자 오류 보고 2026-10-19)

- 간편 모드는 `delete TX-000002`, `삭제 tx-000002`처럼 명령 뒤에 거래 번호를 바로 적는 방식을 기존 `delete --id ID`로 변환한다. `delete` 또는 `삭제`만 입력하면 기존처럼 거래 번호를 질문한다. `delete --id ID`, `--id=ID`도 계속 지원한다.
- 간편 모드의 삭제 번호는 앞뒤 공백을 제거하고 영문을 대문자로 바꾼 뒤 기존 모델·서비스로 검증한다. `Tx-000002`, `tx-000002`는 `TX-000002`가 된다. 자릿수·접두사 검증과 존재 검사는 그대로 적용한다. 번호를 추측하거나 빈 번호를 기본 선택하지 않는다.
- `delet`는 삭제를 실행하지 않고 `delete` 또는 `삭제` 사용 예시를 안내한다. `help delete`, `help 삭제`, `삭제 --help`는 짧은 삭제 예시를 보여주고 파일을 만들지 않는다. 기본 도움말과 README에도 한 줄 삭제 예시를 제공한다.
- 기존 `python -m budget_app`의 옵션 계약은 바꾸지 않는다. 회귀 검증은 임시 가계부로 실제 프로세스를 실행하며 사용자 거래는 검증 대상으로 삭제하지 않는다. 기존 과제 완료 이후의 수정으로 커밋·푸시를 한 번 수행한다.

### D47 — 삭제 거래 복구와 전체 코드 설명 (사용자 요청 2026-10-19)

- `delete`는 대상 거래가 있는지 확인한 뒤 원래 거래 전체를 `{data_dir}/backups/deleted.jsonl`에 저장하고 활성 거래 파일에서 제거한다. 기존 이력을 스트리밍 검증하면서 새 이력을 덧붙인 임시 파일을 완성하고 `flush`·`fsync`·`os.replace`로 보관 파일을 교체한다. 보관 실패 시 삭제하지 않는다. 삭제 파일 재작성 실패 시 원본 보존 규칙은 그대로 적용한다. 삭제 보관 파일은 필요할 때만 만들고, 활성 파일 4개와 기존 `backup` 복사 규칙은 유지한다.
- 삭제 이력은 기존 Transaction JSONL 형식으로 이전 기록을 계속 유지한다. `TransactionRepository.archive`가 폴더·파일 처리를 맡고 `iter_deleted`는 제너레이터로 읽는다. `TransactionService.restore(tx_id=None)`는 번호가 없으면 마지막 삭제 기록, 있으면 그 번호의 가장 최근 삭제 기록을 선택한다. 활성 거래를 스트리밍하며 복구 대상을 더한 파일도 임시 파일·동기화·교체로 완성해 저장 실패 시 기존 거래를 보호한다.
- `restore [--id ID]`는 원래 거래 번호·날짜·종류·분류·금액·메모·태그를 그대로 복구한다. 활성 거래에 동일한 번호가 있으면 중복 복구 또는 번호 재사용으로 보고 거부하며 기존 거래를 보존한다. 카테고리가 삭제되어 있으면 분류를 먼저 다시 등록하도록 기존 검증으로 안내한다. 복구 후 삭제 이력은 유지한다.
- 간편 모드에서는 `복구`, `restore`만 입력하면 최근 삭제를 복구하고 `복구 tx-000002`, `restore TX-000002` 또는 `restore --id ID`로 대상을 정한다. 삭제와 마찬가지로 번호의 앞뒤 공백과 영문 대소문자를 정리한다. 도움말은 데이터를 만들지 않는다. 복구 성공은 `[복구 완료] id=TX-000002`로 표시한다.
- 기능 추가 전에 삭제한 거래는 이력이 없으므로 자동 복구 대상이 아니다. 이번에 삭제된 예시 `TX-000002`는 사용자가 제공받은 로컬 `sample.csv`의 원본 행을 확인해 같은 번호·내용으로 한 번 복원한다. 다른 거래는 보존한다.
- 저장소의 모든 Python 파일에 모듈·클래스·함수의 역할과 주요 검증·예외·저장 흐름을 설명하는 한국어 docstring·주석을 보완한다. 설명 추가만 하는 부분은 동작을 바꾸지 않으며, 구문을 기계적으로 번역하는 반복 주석은 피한다. 신규 패키지나 모듈은 추가하지 않는다.
- 기존 테스트와 실제 프로세스 회귀 시나리오로 삭제→재실행→복구, 대상 외 거래 보존, 복구 불가 상황과 저장 실패를 검증한다. 이번 확장도 `main`에 한 번 커밋·푸시한다.

### D48 — 간편 모드에서 전체 실행 명령 재사용 (사용자 요청 2026-10-19)

- `가계부>` 안에서 `python -m budget_app list --limit 3` 같은 전체 실행 문장도 받는다. `python`, `python3`, `python3.N`과 선택적인 `.exe`, 해당 Python 실행 파일의 전체 경로를 인식한다. 실행 대상은 `-m budget_app`, `-m budget_app.easy`, `budget.py`·`./budget.py`·`.\budget.py`로 한정한다.
- `easy.normalize_invocation`이 실행 접두사를 한 번만 제거한 뒤 기존 간편 입력·파서·서비스·핸들러로 연결한다. Python 프로세스나 별도의 셸을 띄우지 않는다. 짧은 명령과 전체 실행 문장의 실행 경로를 하나로 유지해 각 입력의 처리와 결과 출력이 한 번만 일어나게 한다. 기존 명령 기능을 별도로 복사하지 않는다.
- 전체 실행 접두사만 입력해 명령이 남지 않으면 도움말을 출력한다. 명령 대기 중 `python budget.py`를 입력해도 중첩 가계부를 시작하지 않는다. 인식하지 않는 Python 실행 형식이나 중첩 접두사는 사용법 오류로 안내하고 임의 실행하지 않는다.
- 세션의 `--data-dir`·`--verbose` 기본값을 사용하며, 전체 명령에 전역 옵션을 직접 적으면 그 명령에서 우선 적용한다. 다음 입력에는 세션의 기본값을 다시 사용한다. 따옴표 안 공백·Windows 경로·빈 값 등 기존 입력 처리를 유지한다.
- 기존 `tests/test_cli.py`에서 결과의 동등성, 처리·저장 중복 없음, 데이터 폴더 선택, 도움말·오류 후 계속 사용을 실제 프로세스로 검증한다. README와 도움말에 두 입력 형태가 같은 기능으로 연결됨을 안내하고 `main`에 한 번 커밋·푸시한다.

### D49 — 0 입력 방어 확인과 전체 사용 안내 정리 (사용자 요청 2026-10-19)

- 금액 `0`은 이미 `models.parse_amount`의 `number <= 0` 검사로 차단한다(D08). 거래 추가·수정·예산·반복 규칙·CSV 가져오기가 이 검증을 재사용한다. 저장 파일과 삭제 이력도 모델 변환 시 같은 조건으로 검사한다. `--limit`·`--top`은 `cli.positive_int`, 반복 일자는 `parse_day`가 0을 차단한다. 기존 방어 로직을 중복 추가하지 않는다.
- 대화형 거래·예산·반복 입력에서 0을 받으면 원인과 힌트를 표시하고 같은 값을 다시 묻는다. 옵션형 금액 오류는 종료 코드 1, 조회 건수·순위 개수 오류는 2이며 기존 거래·예산은 보존한다. CSV의 0원 행은 저장하지 않고 건너뛴 사유와 건수를 보여주며, 행 처리를 마친 가져오기는 기존 정책대로 0으로 끝난다. 조회 결과 0건이나 계산된 합계 0원은 정상이다.
- `tests/test_cli.py`에 사용자 입력 경계의 회귀 시나리오를 추가하고 기존 모델·서비스 검증 테스트와 역할을 나눈다. 실제 사용자 데이터는 테스트에 쓰지 않는다.
- 정상 거래 5건을 담은 `samples/demo.csv`를 Git에 포함해 새 저장소에서도 README의 연습 절차를 재현할 수 있게 한다. 기존 `samples/import_sample.csv`는 오류 행을 포함한 검증 자료로 유지한다. 이 컴퓨터의 루트 `sample.csv`와 `data/`는 기존대로 Git에서 제외하고, 새 복제에서 자동으로 예시 거래를 넣지 않는다.
- README에 간편 실행·전체 명령 호환·예시 CSV·삭제/복구·0 방어·전체 코드 주석·스모크 의미와 최신 검증 결과를 정리한다. 원문 명세·기존 모듈 구조·현재 저장 정책은 유지한다. 검증 후 `main`에 한 번 커밋·푸시한다.

## 5. 계층과 모듈 책임

```text
budget_app/
  __main__.py     main() 호출, sys.exit(code)
  cli.py          argparse 트리, 대화형 프롬프트(input_fn 주입), 출력 포맷 호출. 파일 I/O 금지
  services.py     유스케이스. 검증 조합, id 발급, 집계, 재배정. 저장소만 호출
  repository.py   JsonlStore(경로 1개: iter/append/rewrite) + TransactionRepository/CategoryStore/BudgetStore/RecurringStore + ensure_initialized/backup_files
  models.py       @dataclass Transaction, Category, Budget, RecurringRule. 필드 검증 함수, to_dict/from_dict
  decorators.py   handle_errors, log_call, timed
  errors.py       AppError(message, hint, exit_code=1) 와 하위 예외, EXIT_* 상수
  formatting.py   테이블 열 정렬(전각 폭 계산, 금액 우정렬)·행 렌더링. 천 단위 구분 없음 (D42)
scripts/verify.py 게이트: unittest 실행 → 임시 data-dir로 CLI 스모크 시나리오 → 요약 출력, 실패 시 종료 1
tests/test_models.py, test_repository.py, test_services.py, test_cli.py
samples/import_sample.csv
samples/demo.csv
```

| 계층 | 책임 | 하지 않는 것 |
| --- | --- | --- |
| models | 데이터 구조, 단일 필드 검증(`parse_date`, `parse_amount`, `parse_type`, `parse_tags`), 직렬화 | 파일 접근, 카테고리 존재 검사(저장소 필요) |
| repository | JSONL 스트리밍 읽기, append, 원자적 재작성, 파일 초기화 | 비즈니스 규칙, 출력 |
| services | 유스케이스 조합, 교차 검증(카테고리 존재, 사용 중 여부), 집계, CSV 변환 | argparse, print, input |
| cli | 인자 정의, 프롬프트 루프, 서비스 호출, 결과 출력 | 파일 접근, 검증 로직 중복 구현 |

## 6. 데이터 계약

```python
@dataclass(slots=True)
class Transaction:
    id: str            # "TX-000012"
    type: str          # "income" | "expense"
    date: str          # "YYYY-MM-DD" (검증 완료 문자열로 보관)
    amount: int        # > 0
    category: str
    memo: str = ""
    tags: list[str] = field(default_factory=list)

@dataclass(slots=True)
class Category:
    name: str

@dataclass(slots=True)
class Budget:
    month: str         # "YYYY-MM"
    amount: int        # > 0
```

- JSONL 키는 필드명과 동일. 알 수 없는 키는 무시하고, 필수 키 누락·타입 불일치 줄은 `AppError("저장 파일 {n}행이 손상되었습니다", hint="해당 줄을 수정하거나 backup에서 복구하세요")`로 종료 1.
- 정렬 키: `(date, id)` 내림차순 (D06).
- 월 필터: `date[:7] == month`.

## 7. CLI 계약

전역: `python -m budget_app [--data-dir PATH] [--verbose] <command> ...`

| 명령 | 옵션 / 입력 | 성공 출력 (stdout) | 실패 → 코드 |
| --- | --- | --- | --- |
| `add` | 대화형 6항목 (날짜, 타입, 카테고리, 금액, 메모, 태그) | `[저장 완료] id=TX-000012` | 중단 130 |
| `list` | `--limit N` (기본 20) | 최신순 N줄, 0건 `[안내] 거래가 없습니다` | — |
| `search` | `--from --to --category --type --q --tag --limit` | 최신순, 0건 안내 | 날짜 형식 1 |
| `summary` | `--month YYYY-MM` (필수) `--top N` (기본 5) | 총 수입/총 지출/잔액/[예산]/빈 줄/지출 TOP N | 월 형식 1 |
| `budget set` | `--month --amount` (필수) | `[저장 완료] 2024-01 예산 500000원` | 금액 1 |
| `budget list` | — | `2024-01 \| 500000원` 월 오름차순, 0건 안내 | — |
| `category add` | `[name]` 또는 대화형 | `[저장 완료] category=food` | 중복·빈 이름 1 |
| `category list` | — | `- name` 이름 오름차순 | — |
| `category remove` | `--name` (필수) `[--replace NAME]` | `[삭제 완료] category=food` 또는 재배정 메시지 | 사용 중·없음 1 |
| `update` | `--id` (필수) + 수정 옵션 1개 이상 | `[수정 완료] id=...` | 없는 id 1, 옵션 없음 2 |
| `delete` | `--id` (필수) | `[삭제 완료] id=...` | 없는 id 1 |
| `restore` | `[--id ID]`, 생략 시 최근 삭제 기록 | `[복구 완료] id=...` | 이력 없음·번호 충돌·카테고리 없음 1 |
| `import` | `--from PATH` (필수) | `[완료] imported=N, skipped=M` + skip 사유 줄 | 파일·헤더 1 |
| `export` | `--out PATH` (필수) + `--month` 또는 `--from/--to` | `[완료] {out} ({N} records)` | 조건 없음 2 |
| `backup` | — | `[완료] data/backups/{ts} (4 files)` | — |
| `recurring add` | 대화형 6항목 (매월 일, 타입, 카테고리, 금액, 메모, 태그) | `[저장 완료] id=RC-000001` | 중단 130 |
| `recurring list` | — | `id \| 매월 N일 \| type \| category \| amount \| memo`, 0건 안내 | — |
| `recurring remove` | `--id` (필수) | `[삭제 완료] id=RC-...` | 없는 id 1 |
| `recurring apply` | `--month YYYY-MM` (필수) | `[완료] {월} 반복 내역 적용 created=N, skipped=M` + skip 사유 줄, 규칙 0건 안내 | 월 형식 1 |

출력 행 포맷(list/search): `id | date | type(7자리 좌정렬) | category | amount(우정렬) | memo`. P7에서 열 너비를 데이터에 맞춰 정렬한다.

## 8. 오류 규약

```python
class AppError(Exception):
    def __init__(self, message: str, hint: str = "", exit_code: int = 1): ...

class ValidationError(AppError): ...   # 날짜·금액·타입·태그 형식
class NotFoundError(AppError): ...     # 없는 id, 없는 카테고리
class ConflictError(AppError): ...     # 중복 카테고리, 사용 중 카테고리
class StorageError(AppError): ...      # 손상된 줄, 파일 권한, 재작성 실패
```

- 서비스와 모델은 `AppError` 하위만 던진다. 표준 예외(`ValueError`, `OSError`)는 그 자리에서 `AppError`로 감싼다.
- `handle_errors`만 `print`로 오류를 쓴다(stderr). 다른 계층에서 오류를 직접 출력하지 않는다.
- 대화형 재입력 루프는 `cli`가 `ValidationError`/`NotFoundError`를 잡아 메시지를 보여주고 다시 묻는다. 그 외 예외는 그대로 위로 올린다.

## 9. 구현 단계 — 9 Phase, 커밋·푸시 각 1회

제약: **커밋·푸시 합계 10회 이내.** 9개 Phase에 1회씩, 1회는 예비(`fix:`). 한 Phase 안에서는 커밋하지 않고, 게이트를 통과한 시점에 한 번만 커밋하고 즉시 푸시한다. 게이트가 실패하면 같은 Phase 안에서 고친다(커밋하지 않음). Phase 순서를 바꾸거나 두 Phase를 한 커밋에 합치지 않는다.

각 Phase의 "게이트"는 `python scripts/verify.py` 한 번이다. 이 스크립트는 (1) `unittest` 전체, (2) 임시 `--data-dir`에서 CLI 스모크 시나리오를 실행한다. 아직 구현되지 않은 명령의 스모크는 Phase 번호로 건너뛴다(`verify.py --phase N` 또는 스크립트 내 상수).

### P0 — 문서 (완료)

- 산출: `docs/MISSION_SPEC.md`, `README.md`, `AGENT.md`, `.gitignore`
- 게이트: 없음(문서 리뷰). 커밋 `docs: 명세 분석과 명세 주도 개발 계획 수립`

### P1 — 골격과 계약 (완료)

- 산출: `budget_app/{__init__,__main__,cli,errors,decorators,models,formatting}.py`(formatting은 단순 join), `services.py`·`repository.py`는 시그니처만(`NotImplementedError` 대신 `AppError("아직 구현되지 않은 명령입니다", hint="Phase N")`), `scripts/verify.py`, `tests/test_models.py`
- 범위: argparse 트리 **전 명령·전 옵션** 정의(D02, D23, D27), `--help` 전부 동작, 종료 코드 체계(D14), 데코레이터 3종(D22), 모델 검증 함수(D08~D11), 콘솔 인코딩(D30)
- 완료 조건: 모든 서브커맨드 `--help` 종료 0 / 잘못된 옵션 종료 2 / `test_models` 통과 / 미구현 명령은 `[오류]` 두 줄 + 종료 1 (스택트레이스 없음)
- 커밋: `feat: CLI 골격과 데이터 모델·오류 계약 구현`

### P2 — 저장 계층 (완료)

- 산출: `repository.py` 완성, `tests/test_repository.py`
- 범위: `JsonlStore.iter_records()`(yield), `append(record)`, `rewrite(records_iter)`(D21), 손상 줄 StorageError, `TransactionRepository.iter_all/next_id/append/rewrite`, `CategoryStore.names/exists/add/remove`, `BudgetStore.get/set/iter_all`, `ensure_initialized(data_dir)`(D04, D23)
- 완료 조건: 10만 줄 임시 파일을 `iter_records`로 훑는 동안 리스트를 만들지 않음(테스트는 `itertools.islice`로 앞 3개만 소비 후 종료) / `rewrite` 도중 예외 주입 시 원본 보존 / 초기화 시 기본 카테고리 5개 / `next_id` 빈 파일 `TX-000001`
- 커밋: `feat: JSONL 스트리밍 저장소와 원자적 재작성 구현`

### P3 — category + add + list (완료)

- 산출: `services.py`(CategoryService, TransactionService.add/list), `cli.py` 대화형 프롬프트, `tests/test_services.py`(시작), `verify.py` 스모크 1
- 범위: `category add/list`(D12, D26), `add` 대화형 재입력 루프(D13), 카테고리 존재 검사, `list --limit` `heapq.nlargest`(D06, D07)
- 완료 조건: 스모크 3(스모크 번호 = Phase 번호) = `category list` → `category add cafe` → `add`(input 주입 3건, 1건은 잘못된 날짜 후 재입력) → `list --limit 2` 최신순 확인
- 커밋: `feat: 카테고리 관리와 거래 추가·목록 구현`

### P4 — search + summary + budget (완료)

- 산출: `services.py` 확장, `tests/test_services.py` 확장, 스모크 2
- 범위: `search` 6조건 AND + `--limit`(D28), `summary` 집계·TOP N·데이터 없음(D16)·예산 사용률·초과 경고(D17), `budget set/list`(D25)
- 완료 조건: 스모크 4 = `budget set` → `summary --month`(예산 줄·TOP 확인) → 초과 데이터 추가 후 `[경고]` 확인 → 빈 달 `데이터 없음` → `search` 각 조건 1회
- 커밋: `feat: 검색·월별 요약·예산 경고 구현`

### P5 — update + delete + category remove (완료)

- 산출: `services.py` 확장, 테스트 확장, 스모크 3
- 범위: `update` 옵션 기반(D03), `delete`, 없는 id NotFoundError, `category remove` 차단/`--replace` 재배정(D18). 세 동작 모두 `rewrite`(D21)
- 완료 조건: 스모크 5 = `update` 금액 변경 후 `list` 반영 → 없는 id 종료 1 → `delete` 후 건수 감소 → 사용 중 카테고리 remove 종료 1 → `--replace` 후 `search --category` 로 재배정 확인
- 커밋: `feat: 거래 수정·삭제와 카테고리 재배정 구현`

### P6 — import / export (완료)

- 산출: `services.py` CSV 변환, `samples/import_sample.csv`(유효 5행 + 무효 1행), `tests/test_cli.py`(라운드트립), 스모크 4
- 범위: `import --from`(D19), `export --out` + 기간 조건 필수(D20), 열 순서·인코딩·`newline=""`
- 완료 조건: 스모크 6 = `import` 샘플 → `imported=5, skipped=1` → `export --month` → 파일 헤더·행수 확인 → 빈 data-dir에 다시 `import` 한 export 파일 → 건수 동일(라운드트립) → `export` 조건 없음 종료 2
- 커밋: `feat: CSV 가져오기·내보내기 구현`

### P7 — 보너스 (완료, B2 는 P9)

- 산출: `formatting.py` 테이블 정렬(B3), `backup` 명령(B1), (선택) 반복 내역(B2)
- 범위: list/search/budget list 열 너비 정렬, 금액 우정렬, `backup` → `data/backups/{YYYYMMDD-HHMMSS}/` 3파일 복사(`shutil.copy2`)
- 완료 조건: 스모크 전체(1, 3~6) 재통과 + 스모크 7 = `backup` 폴더에 파일 3개(P9 이후 4개) + 테이블 구분자 위치 일치
- 커밋: `feat: 테이블 출력과 백업 추가`

### P8 — 마무리 (완료)

- 산출: README 5장 예시를 **실제 출력**으로 교체, 9장 상태표 갱신, 이 문서의 어긋난 부분 수정
- 범위: 새 터미널에서 수동 대화형 `add` 1회 확인(유일한 수동 검증), 게이트 전체 통과 기록, 알려진 한계(D05 번호 재사용 등) 명시
- 완료 조건: `python scripts/verify.py` 전체 PASS, README 사양과 실제 출력 불일치 0건
- 커밋: `docs: 실행 결과 반영과 최종 검증 기록`

### 예비 1회 → P9 — 반복 내역 B2 (완료, 사용자 결정 2026-10-18)

- 원칙은 결함 수정 전용(`fix:`)이었으나 P8 까지 게이트 실패가 없어, 남은 1회를 사용자 결정으로 보너스 B2 구현에 썼다(D44, C3 개정).
- 산출: `models.RecurringRule`/`parse_day`, `repository.RecurringStore`/`recurring.jsonl`, `services.RecurringService`, `cli` 의 `recurring add/list/remove/apply`, `formatting.format_recurring_table`, 테스트 시나리오(test_services·test_repository 갱신), 스모크 9
- 완료 조건: 스모크 9 = `recurring add` 2건(1건은 잘못된 일 재입력) → `apply --month 2024-02`(created=2, 31일 → 02-29 보정) → `list` → 재 `apply`(created=0, skipped=2) → 미등록 카테고리 규칙 skip → `remove` / 스모크 7 의 backup 은 4파일
- 커밋: `feat: 반복 내역 등록과 월별 자동 생성 추가` (누계 10/10)

## 10. 검증 정책 — 최소 단위

검증 비용이 커밋 수보다 빠르게 늘어나지 않도록 아래를 지킨다.

- **게이트는 하나.** Phase 완료 판정은 `python scripts/verify.py` 결과만 본다. 별도의 수동 체크리스트를 만들지 않는다.
- **테스트 파일은 계층당 1개, 총 4개 이하.** `test_models`(검증 함수), `test_repository`(스트리밍·원자성·초기화), `test_services`(유스케이스), `test_cli`(라운드트립·종료 코드). 함수 하나마다 테스트를 만들지 않고 **시나리오 단위**로 쓴다.
- **스모크는 CLI 경계에서.** `subprocess.run([sys.executable, "-m", "budget_app", "--data-dir", tmp, ...])` 로 실제 진입점을 호출하고 stdout·종료 코드만 검사한다. 대화형 입력은 `input=` 으로 주입한다.
- **수동 검증은 P8에서 1회.** 실제 터미널 대화형 `add` 확인만 사람이 한다.
- **성능 검증은 메모리 패턴 1개.** 10만 줄 파일을 `islice`로 일부만 소비하는 테스트로 제너레이터 여부를 증명한다. 시간 측정은 `timed` 로그로 대체한다.
- **외부 도구 금지.** mypy, ruff, pytest, coverage는 설치하지 않는다. 타입 힌트는 코드 리뷰로 확인한다.
- **테스트 금지 목록.** 출력 문자열의 공백 1칸까지 비교하는 테스트, private 함수 직접 테스트, 같은 경로를 두 계층에서 중복 테스트.

## 11. Git 규칙

- 브랜치: 개인 과제이므로 `main`에 직접 커밋한다. 브랜치·PR을 만들지 않는다.
- 커밋 메시지: `<type>: <한국어 요약>` 한 줄. type은 `docs`, `feat`, `fix`. 본문에는 Phase 번호와 게이트 결과 한 줄(`verify: PASS (unittest 30, smoke 1, 3, 4, 5, 6, 7, 9)`)을 적는다. 마지막 줄에 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` 를 포함한다.
- 작성자: 로컬 git 설정(`Cerhovah`)을 그대로 쓴다. `--author`로 바꾸지 않는다.
- 푸시: 커밋 직후 `git push origin main` 1회. force push 금지. amend 금지(예비 커밋을 사용).
- 커밋 전 확인: `git status`에 `data/`, `*.csv`(samples 제외), `__pycache__`, 백업이 없을 것.
- 커밋·푸시 횟수는 README 9장 상태표에 기록해 10회 한도를 추적한다.

## 12. 완료 보고 형식

Phase를 끝낼 때 사용자에게 아래만 보고한다. 길게 쓰지 않는다.

```text
Phase N 완료 — <커밋 제목>
게이트: python scripts/verify.py → PASS (unittest N개, smoke 1-M)
커밋/푸시 누계: K / 10
결정표 변경: 없음 | D31 추가(요지)
미완·한계: 없음 | ...
```

게이트가 실패한 상태에서는 "완료"라고 쓰지 않는다. 실패 출력을 그대로 보여 주고 원인과 수정 계획을 한 줄로 적는다.

## 13. 금지 사항 요약

- 추측 구현(결정표 없이 모호한 요구를 해석하는 것)
- 문서 없이 코드만 바꾸는 커밋
- 새 마크다운·계획 파일·ADR 폴더 생성
- `pip install`, 외부 패키지, pytest
- 전체 파일 로드(`readlines`, `list(gen)` 후 처리), 원본 직접 덮어쓰기
- 스택트레이스 노출, 종료 코드 0으로 오류 종료
- 한 Phase 안의 다중 커밋, Phase 합치기, force push, amend
- 결정표에 없는 기능 추가 — D45+에 기록 후 승인 대기 (B2 는 D44 로 승인·구현됨)
