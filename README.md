# budget_app — 나만의 용돈 기입장 (Codyssey Mission B2-1)

> Python 표준 라이브러리만으로 만드는 파일 기반 콘솔 가계부.
> 제너레이터 스트리밍 · 데코레이터 · 타입 힌트 · 계층 분리 · 원자적 저장을 갖춘 "작은 서비스".
> 이 저장소는 **명세 주도 개발(Spec-Driven Development)** 로 진행한다. 코드보다 문서가 먼저이고, 변경은 문서에서 시작한다.

| 문서 | 역할 |
| --- | --- |
| [docs/MISSION_SPEC.md](docs/MISSION_SPEC.md) | 과제 명세 **원문 보존** (수정 금지) |
| `README.md` (이 문서) | 명세 심층 분석, 사용자 관점 사양(실행·저장·명령·CSV), 진행 현황 |
| [AGENT.md](AGENT.md) | 개발 헌장, 모호성 결정표 D01~D37, 계층·계약, 9단계 커밋 계획, 검증 정책 |

진행 상태: **Phase 3 (카테고리·거래 추가·목록) 완료 — 검색·요약·예산(P4) 구현 전**. 아래 "명령 예시"는 구현 목표 사양이며, Phase 8에서 실제 출력으로 갱신한다.

---

## 1. 미션 심층 분석

### 1.1 한 줄 정의

`python -m budget_app <command> [--options]` 로 동작하는 가계부 CLI. 거래(수입/지출)를 **JSONL 파일 3개**(transactions / categories / budgets)에 영구 저장하고, 10개 명령(add · list · search · summary · budget · category · update · delete · import · export)을 제공한다.

### 1.2 명세가 실제로 평가하는 것

명세 1장의 첫 문장이 평가 기준의 핵심이다. "'작은 서비스'란 기능이 많은 게 아니라 **예외 상황에서도 데이터가 안전한 것**". 따라서 기능 개수보다 다음 네 가지 구조 품질이 점수를 가른다.

| 평가 축 | 명세 근거 | 이 프로젝트의 대응 |
| --- | --- | --- |
| 데이터 안전성 | 1장, 4장 6항 "임시 파일/원자적 교체(권장)", 보너스 4 | 모든 재작성은 임시 파일 + `os.replace`. 추가는 append 1줄. 저장 실패 시 원본 유지 |
| 스트리밍 | 4장 5항·7항 "파일 전체를 한 번에 로드하지 않고" | 저장소 읽기는 전부 `yield` 제너레이터. list는 `heapq.nlargest(limit)`로 메모리 O(limit) |
| 관심사 분리 | 4장 12항 데코레이터, 14항 모듈화, 3장 "각 계층의 책임" | `cli / services / repository / models / decorators / errors / formatting` 7모듈, 의존 방향 단방향 |
| 계약 명확성 | 3장 "타입 힌트로 입출력 계약", 4장 13항 exit code | 전 함수 타입 힌트, `AppError(원인, 힌트)` 단일 오류 계약, exit code 0/1/2/130 고정 |

### 1.3 요구사항 매트릭스

명세의 모든 요구를 ID로 고정하고, 어느 명령·모듈·개발 단계(Phase, [AGENT.md](AGENT.md) 9장)가 책임지는지 추적한다. 이 표가 "완료"의 정의다.

| ID | 요구사항 (명세 위치) | 명령 / 모듈 | Phase |
| --- | --- | --- | --- |
| R01 | `python -m budget_app <cmd>` 실행 (4-1) | `__main__.py`, `cli.py` | P1 |
| R02 | 모든 명령 `--help` (4-1) | argparse 서브커맨드 전부 | P1 |
| R03 | 옵션 표기 `--` 통일 (4-1, 7장) | `cli.py` 롱 옵션만 | P1 |
| R04 | Transaction 필드 id/type/date/amount/category/memo/tags, dataclass (4-2) | `models.py` | P1 |
| R05 | 클래스 2개 이상 (4-2) | `Transaction`, `Budget`, `JsonlStore`, `TransactionRepository`, `CategoryStore`, `BudgetStore`, `BudgetService` | P1~P2 |
| R06 | 입력 검증: 날짜/금액/type/category (4-2) | `models.py` 검증 함수, `services.py` | P1, P3 |
| R07 | JSONL 또는 CSV 1개 선택 (4-3) | JSONL (D01) | P2 |
| R08 | 저장 파일 3개 이상 분리 (2-10, 4-3) | `transactions.jsonl`, `categories.jsonl`, `budgets.jsonl` | P2 |
| R09 | 기본 `./data`, `--data-dir`로 변경 (4-3) | 전역 옵션 `--data-dir` | P1~P2 |
| R10 | 초기 실행 시 자동 생성 + 안내 / 빈 카테고리 처리 (4-3) | 안 A 기본 카테고리 자동 생성 (D04) | P2 |
| R11 | add 대화형, category 존재 검사, id 출력 (4-4) | `add` | P3 |
| R12 | list 최신순, `--limit` 기본값, 스트리밍 (4-5) | `list` | P3 |
| R13 | delete `--id`, 없는 id 메시지 (4-6) | `delete` | P5 |
| R14 | update 방식 문서 고정 (4-6) | 옵션 기반 안 A (D03) | P5 |
| R15 | update/delete 저장 안정성 (4-6, 보너스 4) | 임시 파일 + `os.replace` | P2, P5 |
| R16 | search `--from/--to/--category/--type/--q/--tag`, 최신순, 스트리밍 (4-7) | `search` | P4 |
| R17 | summary `--month`, 총수입/총지출/잔액, TOP N `--top`, 데이터 없음 (4-8) | `summary` | P4 |
| R18 | budget set 영구 저장, summary에 사용률/초과 경고 (4-9) | `budget set/list`, `summary` | P4 |
| R19 | category add/list/remove, 사용 중 카테고리 처리 (4-10) | `category`, `--replace` (D18) | P3, P5 |
| R20 | import `--from`, export `--out` + 기간 조건 필수, CSV 스키마 고정 (4-11) | `import`, `export` | P6 |
| R21 | 데코레이터 1개 이상 실제 적용 (4-12) | `handle_errors`, `log_call`, `timed` | P1 |
| R22 | 스택트레이스 금지, 원인+힌트, exit code (4-13, 7장) | `errors.py`, `decorators.py` | P1 |
| R23 | 모듈 3개 이상 분리 (4-14) | 7개 모듈 | P1 |
| R24 | README: 실행 방법, 저장 위치/형식, 명령 예시, CSV 스키마 (2-10) | 이 문서 3~6장 | P0, P8 |
| R25 | 표준 라이브러리만 (7장) | 테스트 러너도 `unittest` (D24) | 전체 |
| B1 | (보너스) backup 타임스탬프 백업 | `backup` | P7 |
| B2 | (보너스) 반복 내역 | 선택, 시간 여유 시 | P7 (선택) |
| B3 | (보너스) 테이블 정렬 출력 | `formatting.py` | P7 |
| B4 | (보너스) 저장 원자성 | R15와 동일 구현으로 자동 충족 | P2 |

### 1.4 숨은 요구와 모순 — 반드시 결정해야 했던 지점

명세를 읽는 것만으로는 구현이 갈라지는 지점이 11곳 있었다. 명세 주도 개발에서는 이런 지점을 추측하지 않고 **결정표로 고정**한다. 전체 결정은 [AGENT.md 4장](AGENT.md) D01~D37에 있고, 여기서는 왜 그 결정인지 핵심만 적는다.

1. **"최신순"과 "스트리밍"은 서로 당긴다.** 최신순 정렬은 원칙적으로 전체를 봐야 하지만, 명세는 전체 로드를 금지한다. 해법은 `heapq.nlargest(limit, 제너레이터)`. 파일은 한 줄씩 흐르고 메모리는 limit개만 유지한다. search는 필터를 통과한 부분집합만 정렬한다 (D07).
2. **옵션 표기가 명세 안에서 흔들린다.** 본문에 `-limit`, `-from`, `-top`, `-data-dir`가 섞여 있지만 4장 1항이 `--` 통일을 명시한다. 마크다운 변환 손실로 판단하고 **롱 옵션만** 제공한다 (D02).
3. **update는 옵션 방식(안 A)으로 고정.** 대화형보다 스크립트·테스트가 쉽고 검증 단위가 줄어든다. 사용자가 고정 방식을 문서에서 확인할 수 있어야 한다는 명세 요구는 이 문서 5장이 충족한다 (D03).
4. **빈 카테고리는 기본 카테고리 자동 생성(안 A).** 첫 실행에서 바로 `add`가 되어야 "작은 서비스"답고, 예시 화면의 `salary`도 포함해 `food, transport, rent, salary, etc` 5개를 만든다 (D04).
5. **JSONL을 선택.** `tags`가 리스트이고 `memo`에 쉼표가 들어가므로 CSV는 이스케이프 부담이 크다. JSONL은 1줄 append와 제너레이터 읽기가 자연스럽다. CSV는 import/export 교환 포맷으로만 쓴다 (D01).
6. **id는 `TX-` + 6자리 순번.** 다음 번호는 파일을 스트리밍하며 구한 최대값 + 1. 별도 카운터 파일을 두지 않아 저장 파일을 3개로 유지한다. 유일성은 항상 보장된다 (D05).
7. **금액은 양의 정수만.** CSV 스키마가 "양수 정수"로 못 박았으므로 입력도 동일하게 맞춘다. `15000.5`, `1,000` 은 거부한다 (D08).
8. **"없는 id"는 오류다.** 메시지를 내고 exit code 1로 끝낸다. 명세 4장 13항 "오류 종료는 0이 아닌 값"과 일관된다 (D13, D14).
9. **대화형과 옵션형은 실패 처리가 다르다.** 대화형은 `[오류]`+`[힌트]` 후 재입력, 옵션형은 즉시 종료 코드 1. Ctrl+C는 130 (D13).
10. **카테고리 삭제는 기본 차단, `--replace`로 재배정.** 명세의 두 선택지("막거나" / "대체 요구")를 하나의 명령으로 모두 만족시킨다 (D18).
11. **테스트도 표준 라이브러리.** `pytest`는 `pip install`이 필요하므로 제약 위반이다. `unittest` + 단일 검증 스크립트를 쓴다 (D24).

### 1.5 위험 요소

| 위험 | 영향 | 완화 |
| --- | --- | --- |
| Windows 콘솔 인코딩 (cp949) | 한글 출력·입력 깨짐 | 시작 시 `sys.stdout/stdin.reconfigure(encoding="utf-8")` 시도, 파일 I/O는 항상 `encoding="utf-8"` (D30) |
| 대화형 `input()` 테스트 불가 | 검증 비용 급증 | 서비스가 `input_fn: Callable[[str], str]` 를 주입받음. 테스트는 큐에서 꺼냄 |
| 재작성 도중 중단 | 데이터 손실 | 임시 파일에 완전히 쓴 뒤 `os.replace`. 원본은 마지막 순간까지 건드리지 않음 |
| 명세 과잉 해석 | 범위 폭발, 커밋 수 초과 | 결정표에 없는 기능은 만들지 않음. 보너스는 P7 한 단계로 제한 |

---

## 2. 명세 주도 개발 적용 방식

Spec Kit, Kiro, Tessl을 비교한 Birgitta Böckeler의 에세이는 명세의 역할을 세 단계로 나눈다. **spec-first**(명세가 이번 작업을 이끈다), **spec-anchored**(명세를 코드와 함께 유지·갱신한다), **spec-as-source**(사람은 명세만 고친다). 이 프로젝트는 **spec-first로 시작해 spec-anchored로 유지**한다. 코드만 고치고 문서를 방치하는 순간 문서는 거짓이 되므로, 동작 변경은 반드시 결정표(AGENT.md) 또는 이 문서의 사양을 먼저 고친 뒤 코드에 반영한다.

같은 에세이와 Thoughtworks 팟캐스트가 경고한 함정도 그대로 받아들인다. 작은 과제에 수십 개의 마크다운을 만드는 "sledgehammer to crack a nut", 사람이 읽지 않는 산출물, 큰 사전 계획이 작은 반복을 밀어내는 문제다. 그래서 문서는 **세 개**로 고정하고(원문 / README / AGENT), 작업은 9개 Phase로 크게 묶되 각 Phase는 **검증 게이트 하나**로 끝낸다.

GitHub Spec Kit의 네 단계(Specify → Plan → Tasks → Implement)는 이 저장소에서 다음과 같이 대응한다.

| Spec Kit 단계 | 이 저장소 |
| --- | --- |
| Constitution (불변 원칙) | AGENT.md 3장 "헌장" |
| Specify (무엇을, 왜) | docs/MISSION_SPEC.md + README 1장 분석 + `[NEEDS CLARIFICATION]` 대신 결정표 D01~D37 |
| Plan (어떻게) | AGENT.md 5~8장 계층·데이터 계약·CLI 계약·오류 규약 |
| Tasks (작게 나눠 검증) | AGENT.md 9장 Phase 0~8, 각 1커밋 1푸시 1게이트 |
| Implement | Phase 순서대로, 게이트 통과 후에만 다음 단계 |

참고한 원문:

- Birgitta Böckeler, [Understanding Spec-Driven-Development: Kiro, spec-kit, and Tessl](https://www.martinfowler.com/articles/exploring-gen-ai/sdd-3-tools.html) (martinfowler.com, 2025-10)
- GitHub, [spec-kit / spec-driven.md](https://github.com/github/spec-kit/blob/main/spec-driven.md) — "Specifications don't serve code—code serves specifications"
- Den Delimarsky, [Spec-driven development with AI: Get started with a new open source toolkit](https://github.blog/ai-and-ml/generative-ai/spec-driven-development-with-ai-get-started-with-a-new-open-source-toolkit/) (GitHub Blog, 2025-09)
- Thoughtworks Technology Podcast, [What is spec-driven development?](https://www.thoughtworks.com/insights/podcasts/technology-podcasts/what-is-spec-driven-development)
- Atlassian, [Spec-driven development with Rovo Dev](https://www.atlassian.com/blog/developer/spec-driven-development-with-rovo-dev) — "Break large requests into small, verifiable steps and present a plan"
- PyTorch Korea, [[Deep Research] GitHub의 Spec Kit으로 알아보는 SDD](https://discuss.pytorch.kr/t/deep-research-github-spec-kit-spec-driven-development-sdd-feat-vibe-coding/7689) — TDD/BDD/SDD 비교, 과도한 명세화 경고

---

## 3. 실행 방법

요구 사항: **Python 3.10 이상**, 외부 패키지 없음 (`pip install` 불필요).

```bash
git clone https://github.com/Cerhovah/Codyssey_Mission_B2-1.git
cd Codyssey_Mission_B2-1
python -m budget_app --help
```

저장 폴더는 기본 `./data` 이며 첫 실행 시 자동 생성된다. 다른 위치를 쓰려면 전역 옵션을 **서브커맨드 앞에** 둔다.

```bash
python -m budget_app --data-dir ./my_data list
```

상세 로그가 필요하면 `--verbose` 를 함께 준다 (stderr로 DEBUG 로그, 실행 시간 포함).

검증(개발자용) — 표준 라이브러리만 사용:

```bash
python scripts/verify.py
```

---

## 4. 저장 파일 위치와 형식

| 파일 | 내용 | 1줄 = 1레코드 예시 |
| --- | --- | --- |
| `data/transactions.jsonl` | 거래 내역 | `{"id":"TX-000012","type":"expense","date":"2024-01-15","amount":15000,"category":"food","memo":"점심","tags":["meal"]}` |
| `data/categories.jsonl` | 카테고리 | `{"name":"food"}` |
| `data/budgets.jsonl` | 월 예산 | `{"month":"2024-01","amount":500000}` |

- 포맷: **JSONL** (JSON Lines). UTF-8, LF, 한 줄에 JSON 객체 하나. `ensure_ascii=False`로 한글을 그대로 저장한다.
- 읽기: 항상 제너레이터로 한 줄씩. 빈 줄은 건너뛴다.
- 추가: 파일 끝에 1줄 append.
- 수정·삭제·재배정: 같은 폴더의 임시 파일에 전체를 다시 쓴 뒤 `os.replace`로 교체한다 (원자적 교체).
- 첫 실행: 폴더와 파일 3개를 만들고 `[안내] 저장 폴더를 초기화했습니다: ./data` 를 출력한다. 카테고리 파일이 비어 있으면 기본 카테고리 `food, transport, rent, salary, etc` 를 자동 등록한다.
- 백업(보너스): `backup` 실행 시 `data/backups/YYYYMMDD-HHMMSS/` 아래에 3개 파일을 복사한다.

`data/` 는 `.gitignore` 대상이다. 저장소에는 샘플 CSV만 `samples/` 에 둔다.

---

## 5. 명령 예시

모든 명령은 `--help`를 지원한다. 옵션은 전부 `--` 롱 옵션이다. 아래 출력은 목표 사양이며 Phase 8에서 실제 출력으로 교체한다.

### 5.1 add — 거래 추가 (대화형)

```text
$ python -m budget_app add
날짜(YYYY-MM-DD): 2024-01-15
타입(income/expense): expense
카테고리: food
금액(양수 정수): 15000
메모(선택): 점심
태그(쉼표로 구분, 없으면 엔터): meal
[저장 완료] id=TX-000012
```

잘못 입력하면 `[오류]`와 `[힌트]`를 보여주고 같은 항목을 다시 묻는다. 없는 카테고리를 입력하면 등록된 목록을 보여주고 재입력을 요구한다. Ctrl+C로 중단하면 저장하지 않고 종료 코드 130으로 끝난다.

### 5.2 list — 최신순 목록

```text
$ python -m budget_app list --limit 3
TX-000012 | 2024-01-15 | expense | food      |   15000 | 점심
TX-000011 | 2024-01-14 | income  | salary    | 3000000 |
TX-000010 | 2024-01-12 | expense | transport |   20000 |
```

`--limit` 기본값 20. 정렬은 날짜 내림차순, 같은 날짜는 id 내림차순.

### 5.3 search — 조건 검색 (모든 조건은 AND)

```bash
python -m budget_app search --from 2024-01-01 --to 2024-01-31 --type expense
python -m budget_app search --category food --q 점심
python -m budget_app search --tag meal --limit 10
```

`--q`는 메모 부분 일치(대소문자 무시), `--tag`는 태그 정확 일치. 결과 0건이면 `[안내] 조건에 맞는 거래가 없습니다`.

### 5.4 summary — 월별 요약

```text
$ python -m budget_app summary --month 2024-01 --top 3
총 수입: 3000000원
총 지출: 215000원
잔액: 2785000원
예산: 500000원 (사용률 43.0%)

지출 TOP 3
1) rent 150000원
2) food 45000원
3) transport 20000원
```

- `--top` 기본값 5.
- 예산 초과 시 `예산: 500000원 (사용률 112.0%)` 다음 줄에 `[경고] 예산 초과: +60000원`.
- 해당 월 거래가 0건이면 `[안내] 2024-02 데이터 없음` 을 출력하고 0으로 종료한다 (예산이 있으면 예산 줄만 추가로 보여 준다).

### 5.5 budget — 월 예산

```text
$ python -m budget_app budget set --month 2024-01 --amount 500000
[저장 완료] 2024-01 예산 500000원

$ python -m budget_app budget list
2024-01 | 500000원
```

같은 달에 다시 `set` 하면 덮어쓴다.

### 5.6 category — 카테고리 관리

```text
$ python -m budget_app category add
카테고리명: cafe
[저장 완료] category=cafe

$ python -m budget_app category add book        # 위치 인자도 허용
[저장 완료] category=book

$ python -m budget_app category list
- etc
- food
- rent
- salary
- transport

$ python -m budget_app category remove --name food
[오류] 'food'를 사용하는 거래가 3건 있어 삭제할 수 없습니다.
[힌트] --replace <대체카테고리> 를 지정하면 해당 거래를 옮긴 뒤 삭제합니다.

$ python -m budget_app category remove --name food --replace etc
[완료] 거래 3건을 'etc'로 이동하고 category=food 를 삭제했습니다.
```

### 5.7 update — 옵션 기반 수정 (안 A로 고정)

```text
$ python -m budget_app update --id TX-000012 --amount 18000 --memo "점심+커피"
[수정 완료] id=TX-000012

$ python -m budget_app update --id TX-999999 --amount 1
[오류] 거래를 찾을 수 없습니다: TX-999999
[힌트] python -m budget_app list 로 id를 확인하세요.
```

수정 가능 옵션: `--date --type --category --amount --memo --tags`. 최소 하나는 필요하며, 각 값은 add와 같은 검증을 거친다. `--tags ""` 로 태그를 비울 수 있다.

### 5.8 delete — 삭제

```text
$ python -m budget_app delete --id TX-000012
[삭제 완료] id=TX-000012
```

없는 id는 update와 동일한 오류 + 종료 코드 1.

### 5.9 export / import — CSV

```text
$ python -m budget_app export --out export.csv --month 2024-01
[완료] export.csv (12 records)

$ python -m budget_app export --out q1.csv --from 2024-01-01 --to 2024-03-31
[완료] q1.csv (37 records)

$ python -m budget_app import --from samples/import_sample.csv
[완료] imported=5, skipped=1
  - 3행: 금액은 양의 정수여야 합니다 (입력: -500)
```

export는 `--month` 또는 `--from/--to` 중 하나 이상이 **필수**다. 조건이 없으면 사용법 오류(종료 코드 2).

### 5.10 backup (보너스)

```text
$ python -m budget_app backup
[완료] data/backups/20240131-093000 (3 files)
```

---

## 6. import / export CSV 스키마

| column | required | 형식 | 비고 |
| --- | --- | --- | --- |
| `date` | Y | `YYYY-MM-DD` | 존재하는 날짜만 허용 |
| `type` | Y | `income` 또는 `expense` | 소문자. 앞뒤 공백 제거 |
| `category` | Y | 등록된 카테고리 이름 | 미등록이면 그 행은 skip (자동 생성하지 않음) |
| `amount` | Y | 양의 정수 | `0`, 음수, 소수, 천 단위 쉼표 불가 |
| `memo` | N | 문자열 | 비어 있어도 됨 |
| `tags` | N | 쉼표 구분 문자열 `a,b,c` | 공백 제거, 빈 항목 제거, 중복 제거 |

공통 규칙:

- 인코딩 UTF-8(BOM 없음), 첫 줄은 헤더, 열 순서는 위 표와 동일: `date,type,category,amount,memo,tags`.
- `id`는 CSV에 포함하지 않는다. import 시 새 id를 발급한다.
- import는 행 단위로 검증한다. 유효한 행은 저장하고, 실패한 행은 번호와 사유를 출력한다. 요약은 `imported=N, skipped=M`. 파일이 없거나 헤더가 다르면 아무것도 저장하지 않고 종료 코드 1.
- export는 `csv.writer(..., newline="")` 로 작성해 Windows에서도 빈 줄이 생기지 않는다.

예시 (`samples/import_sample.csv`):

```csv
date,type,category,amount,memo,tags
2024-01-15,expense,food,15000,점심,meal
2024-01-14,income,salary,3000000,,
2024-01-12,expense,transport,20000,버스,"commute,daily"
```

---

## 7. 오류 메시지와 종료 코드

모든 오류는 두 줄 형식이다. 스택트레이스는 출력하지 않는다.

```text
[오류] 원인
[힌트] 해결 방법 또는 예시
```

| 종료 코드 | 의미 | 예 |
| --- | --- | --- |
| 0 | 정상 | 저장 완료, 데이터 없음 안내, 검색 0건 |
| 1 | 입력·도메인·파일 오류 | 없는 id, 미등록 카테고리, 손상된 JSONL 줄, import 파일 없음 |
| 2 | 사용법 오류 (argparse) | 필수 옵션 누락, export 기간 조건 없음, 알 수 없는 옵션 |
| 130 | 사용자 중단 (Ctrl+C) | 대화형 입력 도중 중단 |

예기치 않은 예외도 CLI 진입점의 `handle_errors` 데코레이터가 잡아 `[오류] 예기치 않은 오류: <type>` 과 `[힌트] --verbose 로 다시 실행하면 상세 로그를 볼 수 있습니다` 를 출력하고 1로 종료한다.

---

## 8. 구조 요약

```text
budget_app/
  __main__.py     진입점: python -m budget_app
  cli.py          argparse 정의, 대화형 프롬프트, 출력. 서비스만 호출
  services.py     유스케이스(추가/검색/요약/예산/카테고리/입출력). 검증과 규칙
  repository.py   JSONL 스트리밍 읽기(yield), append, 원자적 재작성. 3개 Store
  models.py       dataclass Transaction/Budget/Category + 필드 검증·직렬화
  decorators.py   handle_errors / log_call / timed
  errors.py       AppError(원인, 힌트) 계층, 종료 코드 상수
  formatting.py   테이블 정렬·금액 포맷 (보너스 3)
scripts/verify.py 단일 검증 게이트 (unittest + CLI 스모크)
tests/            계층당 1개: test_models, test_repository, test_services, test_cli
samples/          import 예시 CSV
docs/MISSION_SPEC.md  명세 원문
```

의존 방향은 `cli → services → repository → models` 한 방향이며, `errors`와 `decorators`는 어디서나 쓴다. 계층별 책임과 계약은 [AGENT.md](AGENT.md) 5~8장에 있다.

---

## 9. 개발 진행 계획과 현황

커밋·푸시는 **최대 10회**로 제한하고, 큰 단위 9개 Phase에 1개씩 배정한다(1회는 예비). 각 Phase는 `python scripts/verify.py` 한 번으로 통과 여부를 판정한다. 세부 범위와 완료 조건은 [AGENT.md 9장](AGENT.md).

| Phase | 범위 | 커밋 | 상태 |
| --- | --- | --- | --- |
| P0 | 문서: 명세 원문, README 분석·사양, AGENT 헌장·계획 | `docs: 명세 분석과 명세 주도 개발 계획 수립` | ✅ 완료 |
| P1 | 골격과 계약: 패키지, errors, decorators, models 검증, argparse 전 명령 `--help`, 종료 코드 | `feat: CLI 골격과 데이터 모델·오류 계약 구현` | ✅ 완료 |
| P2 | 저장 계층: JSONL 제너레이터 읽기, append, 원자적 재작성, 3개 Store, 초기화·기본 카테고리 | `feat: JSONL 스트리밍 저장소와 원자적 재작성 구현` | ✅ 완료 |
| P3 | category add/list, add(대화형), list(heapq) | `feat: 카테고리 관리와 거래 추가·목록 구현` | ✅ 완료 |
| P4 | search, summary, budget set/list | `feat: 검색·월별 요약·예산 경고 구현` | ⬜ |
| P5 | update(옵션), delete, category remove(--replace) | `feat: 거래 수정·삭제와 카테고리 재배정 구현` | ⬜ |
| P6 | import/export CSV, 샘플 파일 | `feat: CSV 가져오기·내보내기 구현` | ⬜ |
| P7 | 보너스: 테이블 정렬, backup (반복 내역은 선택) | `feat: 테이블 출력과 백업 추가` | ⬜ |
| P8 | 마무리: README 실제 출력 반영, 전체 회귀, 상태 보고 | `docs: 실행 결과 반영과 최종 검증 기록` | ⬜ |
| 예비 | 게이트 실패 수정 1회 | `fix: ...` | — |

커밋·푸시 누계: **4 / 10** (P0, P1, P2, P3).
