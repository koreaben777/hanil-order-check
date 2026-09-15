# hanilsf-optimizer — 의령공장 1·2호기 주문: 재고 수 · 유사 상품 · 재고출하/대체검토/생산의뢰 배분

의령공장 1·2호기 부직포 상품을 특정하는 dict(품목·폭·길이·등급)를 받아 ERP(NEOE, **읽기 전용 SELECT**)에서

1. **모듈1 `stock()`** — 그 규격의 재고 수(롤·kg, 미출하 수주 차감 후 가용 롤)
2. **모듈2 `similar_products()`** — 대체 출고 후보(유사 상품) 목록 n개, 손실 적은 순
3. **`check()`** — 주문 수량을 **재고출하 / 대체검토 / 생산의뢰** 세 경로에 나눠 배정 (한 주문이 세 경로에 동시에 걸릴 수 있다. 예: 48롤 = 재고 6 + 대체 16 + 생산 26)

를 돌려준다. `import hanilsf_optimizer` 로 쓰는 파이썬 모듈이 본체이고, 같은 기능을 CLI(`hanilsf`)와 로컬 웹앱으로도 쓴다.

| 파일 | 역할 |
| --- | --- |
| `hanilsf_optimizer.py` | 모듈 본체 + CLI. `stock()` · `similar_products()` · `check()` |
| `pyproject.toml` | 패키지 정의 — `pip install` 한 줄로 설치, 의존성(hhhs-db-manager·pandas) 자동 |
| `app.py` · `index.html` | 로컬 웹앱 (표준 라이브러리 `http.server`, 127.0.0.1 전용) |
| `substitute_rules.json` | 대체 기준. 기본값 + 거래처별 허용 범위(영업담당자 입력) |
| `test_hanilsf_optimizer.py` | DB 없이 도는 자가 점검 |
| `hanilsf_optimizer.ipynb` | 노트북 — 모듈1·모듈2·배분을 예시 상품으로 한 번씩 실행한 출력 포함 (VS Code·JupyterLab 에서 `DB조회도구/.venv` 커널로 열기) |
| `TESTING.md` | 실행 방법과 기능 테스트용 입력값 (복사해서 바로 실행) |
| `NOTEBOOK_GUIDE.md` | 팀원용 — 두 저장소 설치부터 노트북 두 개로 재고 스펙 조회·검증까지 따라하는 테스트 가이드 |

## 설치

**요구사항: [hhhs-db-manager](https://github.com/koreaben777/hhhs-db-manager)** — ERP 조회는 이 팀 공용 도구(`hhhs_db_manager` + `.env` 접속정보)에 맡긴다.
DB 드라이버(**pymssql**)·SQLAlchemy·pandas·python-dotenv 는 그 도구의 의존성으로 함께 들어온다. `.env` 는 그 도구 README 대로 만든다.

### 방법 1 — 패키지로 설치 (팀장·다른 프로젝트에서 `import` 해 쓸 때)

```bash
pip install "git+https://github.com/koreaben777/hanil-order-check"
```

`uv` 를 쓰면 `uv pip install "git+https://github.com/koreaben777/hanil-order-check"`. hhhs-db-manager 가 없으면 GitHub 에서 같이 설치된다.
설치 뒤 접속정보 파일 위치만 알려주면 된다 — 아래 둘 중 하나:

```bash
export HHHS_ENV_FILE="$HOME/Documents/Eugene_Group/한일합섬/DB조회도구/.env"   # 권장: 환경변수로 지정
```

또는 파이썬을 실행하는 **현재 폴더**에 `.env` 를 둔다(hhhs-db-manager 는 `HHHS_ENV_FILE` → 현재 폴더 → 자기 설치 폴더 순으로 `.env` 를 찾는다).
접속 자가점검: `hhhs-db check` → "쓰기 권한 0개 · 읽기 전용" 이면 정상.

### 방법 2 — 소스 체크아웃으로 실행 (웹앱·CLI, 이 저장소를 `DB조회도구/` 옆에 `dev/` 로 둔 경우)

설치 없이 hhhs-db-manager 작업 사본의 가상환경 파이썬으로 바로 실행한다. 맥 기본 파이썬(anaconda·시스템)에는 pymssql 이 없어
서버는 뜨지만 첫 조회에서 `ModuleNotFoundError: No module named 'pymssql'` 가 나므로, **반드시 아래 파이썬**을 쓴다.

| 상황 | 실행 파이썬 |
| --- | --- |
| A. `DB조회도구/`(hhhs-db-manager 작업 사본) 옆에 이 저장소가 `dev/` 로 있음 (권장) | `../DB조회도구/.venv/bin/python` |
| B. hhhs-db-manager 를 다른 위치에 클론함 | 그 도구의 venv 파이썬 + `HHHS_DB_DIR=<hhhs_db_manager.py 폴더>` |
| C. 내 파이썬(anaconda 등)으로 띄우고 싶음 | `pip install -e <hhhs-db-manager 폴더>` 후 그 `python` (또는 방법 1) |

- `.env`(접속정보)는 hhhs-db-manager 폴더에만 둔다. **이 저장소에는 절대 커밋하지 않는다** (`.gitignore` 로 막아 둠).
- 파이썬 3.10+. 재고 조회는 pandas(hhhs-db-manager 에 포함), 생산 배치는 ortools·openpyxl을 사용한다. 방법 2에서는 `uv pip install --python ../DB조회도구/.venv/bin/python ortools openpyxl`로 설치한다.

## 파이썬 모듈 API

```python
import hanilsf_optimizer as ho

p = {"item": "2PD2040NT1N", "width": 1070, "length": 2000, "grade": "A"}   # 상품을 특정하는 dict

ho.stock(p)
# {'item': '2PD2040NT1N', 'width': 1070, 'length': 2000, 'grade': 'A', 'rolls': 6, 'kg': 513.6, 'open_rolls': 0, 'avail_rolls': 6}

ho.similar_products(p, n=10)
# [{'item': '2PD2040NT1N', 'width': 1100, 'length': 2000, 'grade': 'A', 'kind': '폭+30', 'rolls': 16, 'kg': 1408.0, 'open_rolls': 0, 'avail_rolls': 16}]

r = ho.check({**p, "rolls": 48})            # 또는 "kg": 4108.8, 선택 "partner": "거래처코드"
r["stock_rolls"], r["sub_rolls"], r["prod_rolls"], r["decisions"]
# (6, 16, 26, ['재고출하', '대체검토', '생산의뢰'])
ho.jsonable(r)                              # json.dumps 가능한 dict (DataFrame → 행 목록)
```

숫자는 2026-09-14 실측 예시이며 재고는 매일 바뀐다. 세 함수 모두 ERP 를 읽기만 하고, 한 번 호출에 SELECT 3~5회(2~3초)가 나간다.

### 웹앱 탭 — ① 주문 입력·판단 → ② 생산 정의 → ③ 생산 계획

`app.py` 웹앱에 탭이 하나 더 있다. ① 탭에서 주문을 여러 번 판단하고 결과의 **생산 필요분 담기**를 누르면 ② 생산 정의(장바구니, 브라우저 localStorage 에 보관, 같은 규격은 롤수 합산)에 쌓인다. ③ 에서 적용 시작 시각·직전 설비 상태·시간 제한(기본 120초, 단계별)을 넣고 **최적화 실행**을 누르면 `POST /api/optimize` 가 `plan()`(1단 세트 계획) → `schedule()`(2단 순서)를 차례로 풀어 세트표·순서표·경고를 보여준다. ERP 는 읽지 않으며 계수는 추정값이다. ② 카드의 드롭다운에서 **예시 생산 집합 5개**(`cart_examples.json`, 2026-07 의뢰서 규격만 무작위 추출·거래처 없음: 흰색 계열 27행 · 혼합 40행 · 진한 색 위주 54행 · 무작위 73행 · 대량 99행)를 골라 **예시 담기**로 바로 채울 수 있다(`GET /api/examples`). DB 없이 도는 자가 점검: `../DB조회도구/.venv/bin/python test_app.py`.

### 생산 배치·순서 — `hanilsf_plan.plan()` → `hanilsf_schedule.schedule()` (DB 연결 없음)

이미 취득한 `check()` 결과(`order` 객체/dict + `prod_rolls` + `master.gsm`) 또는 직접 생산요구 dict를 받는다. 직접 입력 필수값은 `item`, `width`, `length`, `rolls`, `gsm`이다. ERP/접속정보를 읽지 않으며 `translate()`는 `NotImplementedError`다. 아래는 **합성 입력만 사용하는 2단 예시**다.

```python
from hanilsf_plan import plan, to_xlsx
from hanilsf_schedule import schedule

checked = [
    {"order": {"item": "2TESTWH1N", "grade": "A", "width": 1030, "length": 1000},
     "prod_rolls": 18, "master": {"gsm": 40}, "order_id": "DEMO-1", "mb_ratio": 0.01},
    {"order": {"item": "2TESTWH1N", "grade": "B", "width": 530, "length": 1000},
     "prod_rolls": 18, "master": {"gsm": 40}, "order_id": "DEMO-2", "mb_ratio": 0.01},
]
result = plan(checked,
              base_width_by_machine={"1": 3400, "2": 3600},
              eff_width_by_machine={"1": 3200, "2": 3400},
              eff_width_by_color={"UV": 3500, "UB": 3500},
              max_lanes=30, max_length=None, constraints=[], time_limit=30)
assert result["complete"]
print(result["groups"][0]["sets_used"])  # 9세트, 9,000m, 초과 0
sequence = schedule(result, t0="2026-01-01T08:00:00",
                    machine_state={"color_code": "WH1N", "gsm": 40, "agri": False},
                    frozen=[], blocked=[], time_limit=30)
# 원본·기존 출력을 덮어쓰지 않는 별도 로컬 사본:
# to_xlsx(result, "../Process 3-4. PP 생산의뢰서 20260703.xlsx",
#         "../생산계획_사본.xlsx", sheet_name="생산계획_검토", schedule=sequence)
```

**종단 CLI — 과거 의뢰서 전체에서 재현 가능한 표본 추출**

`dev/`에서 실행한다. `--template` 생략 시 `--requests` 파일을 양식으로 사용하고, `--t0` 생략 시 내일 00:00으로 시작한다. 실제 날짜 납기는 그대로 보존하므로 과거 파일을 현재 시점으로 계획하면 큰 지연값이 나올 수 있다. 미해결이면 XLSX 없이 종료 코드 1이다.

```bash
../DB조회도구/.venv/bin/python hanilsf_demo.py --requests "../Process 3-4. PP 생산의뢰서 20260703.xlsx" --n 30 --seed 20260915 --out "../생산계획_사본.xlsx" --state WH1N,40,0 --time-limit 30
```

`load_requests(xlsx, sheets=None)`는 모든 시트(또는 지정 시트)의 9행부터 합계 전까지 유효 요청만 읽는다. D-01로 `2PD` + 중량대(59g 이하 2, 60g 이상 3) + 평량 3자리 + 색상코드를 만든다. 날짜는 ISO `due`, ASAP은 `urgent=True`, 기타 출고일 텍스트는 그대로 `note`다. `sample_requests(pool,n,seed)`는 지역 난수 생성기로 중복 없이 표본을 뽑는다. 원본은 읽기 전용이며 거래선 값은 요약 로그에 출력하지 않는다.

**1단: 같은 품목·같은 길이의 슬리팅 세트**
- 그룹은 **품목코드만**, 부분문제는 **(품목코드, 길이)**다. `grade`는 표시용으로 그대로 통과하며 혼합을 막지 않는다. 품목코드가 11자가 아니어도 거부하지 않고 `item {code} is not 11 chars; color_code may be wrong` 경고를 반환한다. 세트 안의 롤은 같은 길이이며 긴 롤 재단은 하지 않는다. `[미확인] K-01/K-06/K-08` 세트 구조는 현장 구두 확인 전이다.
- 모든 비어 있지 않은 폭 패턴을 열거하고 CP-SAT 정수계획으로 **총 생산 길이 → 사용 패턴 종류 수 → 초과 롤 수**를 최소화한다. 같은 폭의 여러 주문은 수요를 합산하고 주문별 수량·초과 상한을 지켜 배분한다. 50,000조합 초과 시 큰 폭 우선 탐욕 후보로 제한하고 `approximate=true`와 경고를 반환한다. 이때 `OPTIMAL`은 제한 후보 안의 최적성이다.
- **초과 기본 0**. `{"type":"allow_extra","order_id":"DEMO-1","rolls":2}`일 때만 주문별 2롤까지 허용한다. 초과가 있으면 `extra>0`, `suggest_upsell=true`다. 사용 패턴 수 감소를 위해 초과가 선택될 수 있지만 여유폭을 무조건 채우지는 않는다.
- 제약: `priority(order_id,rank)`는 세트 출력 순서만, `exclusive_roll(order_id)`는 해당 폭만 있는 패턴, `no_edge(order_id)`는 해당 폭을 내부 레인에만 배치한다. `together(order_ids)`는 두 폭이 항상 같은 패턴에 있도록 하며 길이가 다르면 미지원으로 보고한다. 이 세 필터는 **주문이 가리키는 폭 기준**이므로 같은 폭의 다른 주문에도 적용된다.
- `max_lanes(group,n)`, `max_length(group,m)`, `eff_width(group,mm)`의 `group`은 품목코드다. 길이 상한을 넘으면 `INFEASIBLE`이다. `trim(partner,mm)`는 호기 기본 트림보다 큰 경우만 그룹 유효폭을 줄인다. 유효폭은 호기 → 색상 전체코드/접두사 예외 → 직접 지정 → 추가 트림 순으로 결정한다. UV/UB 3,500mm는 `[추정][미확인] W-03`이며 `eff_width_by_color={}`로 끌 수 있다.
- 그룹 출력: `sets`, `sets_used`(반복수 합), `total_length`, `lower_bound_sets`, `gap`, `status`, `approximate`. 세트 블록은 `pattern`, 순서 있는 `lanes`, `length`, `count`, `rolls`(초과 포함 주문별 총수량), `extra`, `note`를 가진다. `set_no`는 품목 내부 번호다. 어느 길이 부분문제라도 미해결이면 해당 품목 전체를 미배치로 보고하고 XLSX를 거부한다.
- `[추정] F-02/F-03` M/R중량은 `총길이 × mr_width_factor × gsm / 1000`, 시간은 `중량 / divisor / k(gsm)`이다. 기본 `mr_width_factor=3.654`, `time_divisors=(27, {30~90:26, 15:21, 18:21, 100:21, 140:19})`. 표에 없는 gsm은 가장 가까운 표의 gsm에 해당하는 k를 사용하며, 동률이면 작은 gsm을 선택한다. `[추정] F-03: gsm {g} uses k of {nearest}` 경고를 남긴다. 빈 계수표는 거부한다. `mb_ratio`는 0~1 비율이며 같은 품목에서 일관되어야 한다. 없으면 MB량은 `None`이다. 결과는 `coefficients_estimated=true`다.

**2단: 세트 블록을 바꾸지 않는 단일 설비 일정**
- 공개 함수: `schedule(plan_result, *, t0, machine_state, frozen=(), blocked=(), rules_file=None, time_limit=30)`. 한 호출에 한 호기만 허용하며 1호기 현장 검증은 별도다. 색상은 품목 뒤 4자리, 평량은 그룹 gsm, 농업용은 UV/UB다. 작업 납기는 주문 `due` 최솟값, 착수 가능 시각은 `available_from` 최댓값, `urgent`는 하나라도 참이면 적용한다.
- 시각은 ISO-8601이며 시간대 유무를 통일한다. 날짜만 주면 그 날짜 **00:00**로 해석한다. `ASAP` 같은 자연어 납기는 거부한다. `frozen=[{"job_id":"2TESTWH1N:1","start":"2026-01-01T08:00:00"}]`는 지정 순서의 **고정 prefix**다. 선택 `end`가 있으면 생산시간과 일치해야 한다. `blocked=[{"start":...,"end":...}]`에는 생산 작업이 겹치지 않는다. 정식화대로 전환은 시간차 제약이므로 **정대 중 전환까지 금지하는 모델은 아니다**.
- CP-SAT 회로·작업 인터벌·NoOverlap. 정수 가중치 사전식 **긴급 가중 납기 지연 → 전환시간+CR 환산손실 → 완료 시각 → 평량 상승 횟수** 최소화. 색상 묶음은 연성 선호이며 긴급 납기로 깨질 수 있다. 솔버 설정은 시간 제한뿐이다(1단 부분문제별, 2단 전체).
- 전환값은 명시한 `rules_file` → 모듈 옆 `transition_rules.json` → 내장 기본값 순으로 선택한다. 명시한 파일이 없거나 잘못된 경우는 오류이며 조용히 기본값으로 대체하지 않는다. JSON은 편집용으로 유지한다. 기본 명도 순서는 `WH NT UV UB AW CP IV LA LB LG BE YL PK OR GD MA BR RD DA DG DB UG BK`이며, 관측 계열의 추정 순서라 기준표 수령 시 교체한다. `[추정] S-05` 평량 차 Δ가 양수면 `0.0375 × max(0, Δ−30)`시간, 상승 계수는 기본 0, 농업용 조건 변경은 1h다. 같은 색·직전 100g에서 **100→60→30: 0.375h**, 직행 **100→30: 1.5h**. C-02 블랙→화이트는 5.5h·CR 6롤이다. 다른 진→연은 5.5h 추정, CR은 BK→WH에만 붙인다. 어느 쪽이든 명도표에 없는 색상 계열이면 같은 코드라도 보수적으로 `dark_to_light_h`(기본 5.5h)를 적용한다. 실제 미지 계열 목록과 `lightness_order 보완 필요` 경고를 남기며 CR은 여전히 BK→WH에만 붙인다.
- 문서에 미지정된 목적 계수는 `[추정]`으로 `objective.urgent_weight=10`, `objective.cr_minutes_per_roll=60`을 둔다. CR 중량은 `cr_roll_kg=100` 임시값이다. 모두 현장 기준으로 교체해야 한다. 전환 출력 `delta_h`는 원계수 시간, 일정은 안전하게 **정수 분 올림**(`scheduled_minutes`)이므로 0.375h는 23분이다.
- 출력은 순서·시작·종료·납기 지연이 있는 `jobs`, `transitions`, 전환시간/CR/지연 합계, `makespan_end`, 색상별 MB량과 경고다. MB 투입률이 없는 작업은 합계에서 제외하고 경고한다. `UNKNOWN`/`INFEASIBLE`이면 빈 일정·`complete=false`·합계 `None`이며 출력하지 않는다.

**XLSX 및 검증**
- `to_xlsx(result, template, out_path, sheet_name=None, schedule=None)`는 PP 구조 일치 시트를 복제하고 주문·재고 칸을 비운 뒤 색상 블록별 세트 순으로 채운다. 같은 세트 주문은 인접하며 세트 사이 한 행을 비운다. 없는 색상은 합계 앞에 마지막 블록 서식을 복사해 추가하고 결과 `warnings`에 `template has no block for {색상}; appended`를 남긴다. 블록 후보가 여러 개면 오류다. S열은 `(1300+950*2)*300 ×80세트 #세트1`, 초과 행에는 `초과 n롤 · 추가구매 권유`를 추가한다. `no_edge`의 내부 레인 순서는 표기에도 유지한다.
- **세트표**는 반복 1회당이 아닌 **세트 블록당 한 행**이다. 열: 세트번호·품목코드·패턴·폭 합·로스(mm)·길이(m)·세트 수·주문별 롤수·M/R 길이·M/R 중량·생산시간(추정)·MB 소요량. `schedule=`을 주면 **스케줄표**(순번·품목코드·색상·gsm·패턴·길이·세트 수·롤수·M/R 길이·M/R 중량·생산시간·시작·종료·전환(h)·CR 롤·납기·지연(h))도 추가한다. 좌표 배열표는 만들지 않는다.
- 원본/기존 출력/예약 시트는 덮어쓰지 않는다. 행 삽입 시 합계·색상 집계·병합 참조를 옮기고 Excel 재계산을 요청한다. **openpyxl은 수식을 실행하지 않는다.** `total_kg`는 제품 총중량이며 M/R중량과 구별한다.
- 소스 체크아웃에서 실행: `../DB조회도구/.venv/bin/python test_hanilsf_plan.py`, `../DB조회도구/.venv/bin/python test_hanilsf_schedule.py`, `../DB조회도구/.venv/bin/python test_hanilsf_demo.py`. 합성 사례와 임시 사본으로 검증하며, 선택적 과거 스케줄 대조는 파일이 있고 보안 태그가 허용할 때만 수행한다. 스케줄 M열 저장값 대조와 지시서 연결·실제 생산시각 검증은 별개다.

### 입력 — 상품을 특정하는 dict

| 키 | 필수 | 형식 | 뜻 |
| --- | --- | --- | --- |
| `item` | ○ | 문자열 | 품목코드(MA_PITEM, 의령 3000). 첫 자리 `1`=1호기 PET/PLA, `2`=2호기 PP 만 허용. 앞뒤 공백·소문자는 정리한다 |
| `width` | ○ | 정수 | 폭 mm (`"1070"` 같은 문자열 숫자도 됨) |
| `length` | ○ | 정수 | 길이 m |
| `grade` | | 문자열 | 등급 `A`·`A0`·`A1`·`B`·`C`·`D`·`R`. 생략·빈 값이면 `A`(업무 규칙) |

이 네 키 외의 키(품명·구매자 등)는 무시한다. `check()` 는 여기에 `rolls`(정수) 또는 `kg`(실수) 중 하나가 **필수**, `partner`(거래처코드)는 선택이다.
dict 대신 `ho.Product(...)` / `ho.Order(...)` 객체를 넣어도 된다.

### 모듈1 — `stock(product, today=None) -> dict`

입력 규격과 **정확히 같은** 품목·폭·길이·등급의 재고 수.

| 키 | 뜻 |
| --- | --- |
| `item` `width` `length` `grade` | 입력을 정리한 값 (대문자·정수) |
| `rolls` | 현재고 롤 수 — 의령 SB창고(3000) 잔량>0 인 LOT 수. ERP 수주화면 "현재고"와 같은 기준 |
| `kg` | 현재고 중량 (소수 1자리) |
| `open_rolls` | 미출하 수주에 이미 잡힌 롤 수 (진행상태 R, 올해 수주, 규격 동일). 앞선 주문이 선점한 재고 |
| `avail_rolls` | `rolls − open_rolls` (0 이상) — **지금 출하에 쓸 수 있는 롤**. 재고 유무를 한 값으로 보려면 이 값을 쓴다 |

재고가 전혀 없는 규격이면 모두 0. 품목코드가 마스터에 없거나 제품(003)이 아니면 `ValueError`.

### 모듈2 — `similar_products(product, n=10, *, partner=None, rule=None, rules_file=None, today=None) -> list[dict]`

동일규격 대신 내보낼 수 있는 **대체 후보(유사 상품)** 를 최대 `n`개, 손실 적은 순으로 돌려준다.

- 후보 범위: 허용 품목·등급 안에서 **폭 [주문, 주문+width_plus] · 길이 [주문, 주문+length_plus]** — 넓은 폭은 슬리팅, 긴 길이는 재단해 쓴다고 가정. 좁거나 짧은 롤은 후보가 아니다.
- 기본 기준: 같은 품목·같은 등급, 폭 +200mm · 길이 +20m (`substitute_rules.json` 의 `default`).
- `partner="거래처코드"` 를 주면 그 거래처에 저장된 기준(허용 품목·등급·폭·길이)이 덮어쓴다. `rule={...}` 은 이 호출에만 쓰는 임시 기준(저장 안 함), 키는 `width_plus`·`length_plus`·`items`·`grades`.
- 정렬: 같은 품목 → 같은 등급 → 좁은 폭 → 짧은 길이. 동일규격과 가용 0 인 규격은 뺀다.

| 키 | 뜻 |
| --- | --- |
| `item` `width` `length` `grade` | 후보 규격 |
| `kind` | 무엇이 다른지 — `폭+30`, `길이+150`, `등급`, `품목` 를 `·` 로 이어 붙임 (예 `등급·폭+30`) |
| `rolls` `kg` `open_rolls` `avail_rolls` | 모듈1 과 같은 뜻의 후보 재고 |

빈 리스트면 기준 안에 대체 가능한 재고가 없다는 뜻이다. 기능(항균 등)이 다른 품목은 `items` 에 명시했을 때만 후보가 된다.

### 배분 — `check(order, today=None, rules_file=None, override=None) -> dict`

주문 롤수(`rolls`, 없으면 `kg ÷ 롤당 kg` 올림)를 재고출하 → 대체검토 → 생산의뢰 순으로 배정한다. 주요 키:

| 키 | 뜻 |
| --- | --- |
| `need_rolls` `need_kg` `roll_kg` | 주문 롤수·kg, 롤당 kg = 폭(m)×길이(m)×평량(g/㎡)÷1000 |
| `onhand_rolls` `open_rolls` `avail_rolls` | 동일규격 현재고 − 미출하 = 가용 (모듈1 과 동일) |
| `stock_rolls` `sub_rolls` `prod_rolls` | 재고출하 · 대체검토 · 생산의뢰 롤수 (합 = `need_rolls`) |
| `decisions` | 배정이 0 보다 큰 경로 이름 목록 |
| `subs` | 대체 후보 표(DataFrame). `alloc` 열이 배정 롤수, `kind` 는 모듈2 와 동일 |
| `rule` `rule_source` | 적용한 대체 기준과 출처(`기본`·`거래처`·`임시`) |
| `open_so` `prq` | 동일규격 미출하 수주 라인, 최근 14일 생산요청(품목 단위) |

`override={...}` 는 이 주문에만 쓰는 임시 기준. 사람이 읽는 요약은 `ho.report(r)`, JSON 은 `ho.jsonable(r)`.

### 오류

| 예외 | 언제 |
| --- | --- |
| `ValueError` | 필수 키 누락, 허용되지 않는 문자·3·4호기 코드, 0 이하 폭·길이, 등급 밖 값, 마스터에 없는 품목, `check()` 에 rolls·kg 둘 다 없음. 메시지는 한국어로 원인을 적는다 |
| `hhhs_db_manager.DBError` (`ConfigError`·`QueryTimeout` 등) | 접속정보·권한·제한시간 문제. `hhhs-db check` 로 자가점검 |

### 환경변수

| 변수 | 뜻 |
| --- | --- |
| `HHHS_ENV_FILE` | ERP 접속정보 `.env` 경로 (패키지로 설치했을 때 권장) |
| `HHHS_DB_DIR` | `hhhs_db_manager.py` 가 있는 폴더 — pip 설치본이 없고 `../DB조회도구/` 도 아닐 때 |
| `HANILSF_RULES` | 대체 기준 파일 경로. 없으면 소스 체크아웃의 `substitute_rules.json`, 그것도 없으면(설치본) **현재 폴더**의 `substitute_rules.json` |

## CLI

설치했으면 `hanilsf`, 소스 체크아웃이면 `../DB조회도구/.venv/bin/python hanilsf_optimizer.py`.

```bash
hanilsf 2PD2040NT1N -w 1070 -l 2000              # 수량 없음 → {"stock": 모듈1, "similar_products": 모듈2} JSON
hanilsf 2PD2040NT1N -w 1070 -l 2000 -g A -r 48   # 수량 있음 → 배분 보고서
hanilsf 2PD2040NT1N -w 1070 -l 2000 --kg 4108.8 --partner 거래처코드 --json   # 배분 결과를 JSON 으로
hanilsf -h
```

## 웹앱

```bash
cd ~/Documents/Eugene_Group/한일합섬/dev
../DB조회도구/.venv/bin/python app.py               # → http://127.0.0.1:8765  (Ctrl+C 종료)
../DB조회도구/.venv/bin/python test_hanilsf_optimizer.py   # 자가 점검 (DB 불필요)
```

복사해서 바로 쓸 수 있는 명령 모음과 테스트 입력값은 `TESTING.md`. Claude 앱의 브라우저 패널에서는 프로젝트 루트 `.claude/launch.json` 의 `order-check` 설정으로 띄운다.

- 왼쪽 **주문 입력**: 품목코드(코드·품명 자동완성) · 폭 · 길이 · 등급 · 롤수·kg(한쪽 입력 시 자동 계산) · 거래처(코드·거래처명 자동완성, 선택). "예시 채우기" 버튼으로 예시 주문이 들어간다
- 오른쪽 **결과**: 재고출하/대체검토/생산의뢰 배분 막대와 수량·비율, 현재고−미출하=가용, 대체 후보 표(배정 행 강조), 동일규격 미출하 수주, 최근 생산요청
- 왼쪽 아래 **거래처 대체 기준**: 폭 허용·길이 허용·허용 품목·허용 등급·코멘트를 적고 **이 주문에만 적용**(저장 없이 임시) 또는 **저장 후 다시 판단**(거래처코드 필요, 파일에 남음)

API(JSON): `GET /api/check?item&width&length&grade&rolls|kg&partner[&temp=1&width_plus&length_plus&items&grades&note]` · `GET /api/items?q=` · `GET /api/partners?q=` · `GET|POST /api/rules`

디자인은 [awesome-design-md](https://github.com/VoltAgent/awesome-design-md) 의 Composio DESIGN.md 를 따랐다.

## 배분 규칙

| 단계 | 테이블 | 내용 |
| --- | --- | --- |
| 품목 | `MA_PITEM` | 제품(003)만. 평량·색상·기능(`CD_USERDEF3`)으로 롤당 kg = 폭(m)×길이(m)×평량÷1000 |
| 현재고 | `MM_QTIOLOT` | 의령(3000)·SB창고(3000)·올해 기초+수불 합산, 품목·폭·길이·등급별 잔량>0 LOT 수 = 롤수 |
| 가용 | `SA_SOL`+`SA_SOH` | 규격별 미출하 수주(QT_SO>QT_GI, STA_SO='R', 올해) 롤수를 차감. 대체 후보 규격에도 같은 차감 적용 |
| 대체 후보 | 위 재고 | 폭 [주문, 주문+width_plus] · 길이 [주문, 주문+length_plus] (넓은 폭은 슬리팅, 긴 길이는 재단 가정). 기본은 같은 품목·등급, 폭 +200mm · 길이 +20m. 거래처 기준으로 허용 범위·품목·등급을 넓힌다. 같은 품목 → 같은 등급 → 좁은 폭 → 짧은 길이 순으로 배정 |
| 생산 | `PR_PRQL` | 최근 14일 생산요청(품목 단위 — 규격 컬럼이 비어 있음) 참고 표시 |

```
재고출하 = min(동일규격 가용롤, 주문롤)
대체검토 = 남은 롤을 대체 후보(가용롤)에서 손실 적은 순(같은 품목 → 같은 등급 → 좁은 폭 → 짧은 길이)으로 배정
생산의뢰 = 그래도 남는 롤
판단 = 배정 수량이 0 보다 큰 경로만 나열
```

두께 등 기타 스펙 조건은 보류(동일규격 = 품목·폭·길이·등급 정확 일치). 기능(항균 등)이 다른 품목은 자동 후보에 넣지 않는다 — 거래처 기준의 `items` 에 명시했을 때만.

## 거래처별 대체 기준 — `substitute_rules.json`

정확한 규격 재고가 없어 대체가 필요할 때, 영업담당자가 그 구매자에 대해 허용 범위를 정해진 폼(웹앱 왼쪽 아래 카드)으로 적으면 다음 조회부터 반영된다.

```json
{
  "default": {"width_plus": 200, "length_plus": 20},
  "P0001": {"width_plus": 300, "length_plus": 500, "items": ["2PD2030WH1N"], "grades": ["A1"], "note": "엠보 1 무관, 폭 +300까지 슬리팅 OK (담당자, 날짜)"}
}
```

| 키 | 뜻 |
| --- | --- |
| `width_plus` | 주문 폭보다 몇 mm 까지 넓은 롤을 슬리팅 후보로 볼지 (기본 200) |
| `length_plus` | 주문 길이보다 몇 m 까지 긴 롤을 재단 후보로 볼지 (기본 20) |
| `items` | 대체 출고를 허용한 다른 품목코드 (예: 엠보만 다른 코드) |
| `grades` | 주문 등급 대신 허용한 등급 (예: A 주문에 A1) |
| `note` | 담당자 코멘트 — 화면에 그대로 표시 |

코드에서는 `ho.set_rule("거래처코드", width_plus=300, length_plus=500, grades=["A1"], note="…")`, 조회 때는 `similar_products(p, partner="거래처코드")` / `check({..., "partner": "거래처코드"})`, CLI 는 `--partner 거래처코드`. `default` 를 바꾸면 전 거래처 기본값이 바뀐다.
거래처 기준 파일은 팀이 함께 쓰는 값이므로 바꾸면 커밋해서 공유한다(개인 실험은 `rules_file=` / `--rules 다른파일.json`).

## 연초 처리

재고 합산은 올해 기초행(`FG_IO='000'`, `DT_IO='YYYY0000'`)부터 시작한다. 이 기초행은 ERP 연말 결산 뒤(보통 1월 말~2월 중순)에야 생긴다.
그 전에 올해 기준으로 합산하면 이월 재고가 통째로 빠지므로, `year_start()` 가 올해 기초행 유무를 확인해 없으면 전년 기초부터 합산한다.

## 한계 (실무 확정 필요)

- `STA_SO='R'`=진행, `'C'`=종결은 데이터 분포로 추정한 값. 오래된 소량 잔량 라인도 차감된다.
- 대체 후보는 자동 출고가 아니라 후보 표시(영업 판단). 과거 기록으로 거래처별 허용 수준을 자동 학습하지는 않는다 — 거래처 기준을 사람이 적는다.
- 양품/불량 구분 없음(ERP 화면과 동일). 3·4호기(MB·합지) 품목은 거부한다.
- 유사 상품 목록에 품명(NM_ITEM)은 넣지 않았다(품목코드만). 필요하면 `ho.item_master(code)["NM_ITEM"]`.
- 웹앱은 인증 없는 로컬 전용(127.0.0.1). 다른 기기에서 쓰려면 바인딩 주소와 접근 통제를 따로 정해야 한다.
