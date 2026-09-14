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
- 파이썬 3.10+. 이 저장소가 더하는 의존성은 pandas 뿐(hhhs-db-manager 에 이미 포함).

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
