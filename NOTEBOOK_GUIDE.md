# 노트북 두 개로 재고 스펙 조회·검증하기 — 설치부터 따라하는 테스트 가이드

의령공장 1·2호기 상품의 **재고 수 · 유사(대체) 상품 · 재고출하/대체검토/생산의뢰 배분**을 노트북에서 조회하고, 그 숫자가 ERP 원본과 맞는지 다른 노트북으로 대조하는 절차다. 두 저장소를 받는 것부터 시작한다.

| 노트북 | 저장소 | 역할 |
| --- | --- | --- |
| `hanilsf_optimizer.ipynb` | [hanil-order-check](https://github.com/koreaben777/hanil-order-check) | **조회** — 상품 dict 를 넣고 모듈1 `stock()` · 모듈2 `similar_products()` · 배분 `check()` 실행 |
| `hhhs_db_manager.ipynb` | [hhhs-db-manager](https://github.com/koreaben777/hhhs-db-manager) | **검증** — 같은 ERP 테이블을 SQL 로 직접 읽어 위 숫자와 대조 |

두 노트북은 **가상환경 하나**(hhhs-db-manager 의 `.venv`)로 실행한다. 모든 조회는 읽기 전용 SELECT 다.

## 0. 준비물

- macOS 또는 Linux 터미널 (Windows 는 경로의 `.venv/bin/` 을 `.venv\Scripts\` 로 읽는다)
- Python 3.10 이상, git, 그리고 [uv](https://docs.astral.sh/uv/) (없으면 `pip` 로도 된다 — 1-2 참고)
- ERP 읽기 전용 계정의 접속정보(담당자에게 받는다) 와 DB 에 닿는 네트워크
- VS Code(Python·Jupyter 확장) 또는 JupyterLab

## 1. 설치 (처음 한 번, 5분)

### 1-1. 두 저장소를 나란히 받는다

폴더 이름은 자유이며 아래는 예시다. 두 저장소가 **같은 상위 폴더** 아래에 있으면 된다.

```bash
mkdir -p ~/hanil && cd ~/hanil
git clone https://github.com/koreaben777/hhhs-db-manager
git clone https://github.com/koreaben777/hanil-order-check
```

### 1-2. 가상환경을 만들고 도구를 설치한다

hhhs-db-manager 폴더에서 실행한다. 노트북 실행에 필요한 `ipykernel`·`jupyterlab` 과 DB 드라이버(`pymssql`)가 함께 들어온다.

```bash
cd ~/hanil/hhhs-db-manager
uv venv --python 3.13
uv pip install -e ".[notebook]"
```

uv 가 없으면:

```bash
cd ~/hanil/hhhs-db-manager
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[notebook]"
```

`hanilsf_optimizer.ipynb` 는 자기 폴더의 `hanilsf_optimizer.py` 를 바로 읽으므로 **따로 설치할 것이 없다.** (다른 파이썬 코드에서 `import hanilsf_optimizer` 로 쓰고 싶을 때만 `uv pip install --no-deps -e ../hanil-order-check`.)

### 1-3. 접속정보 `.env` 를 만든다

hhhs-db-manager 폴더의 `.env.example` 을 복사해 `.env` 를 만들고, 담당자에게 받은 값을 채운다. 값은 노트북 셀이나 채팅에 적지 않는다.

```bash
cd ~/hanil/hhhs-db-manager
cp .env.example .env
open -e .env        # macOS 텍스트 편집기. 다른 편집기를 써도 된다
```

`.env` 는 두 저장소 모두 `.gitignore` 로 막혀 있어 커밋되지 않는다. 그래도 `git status` 에 `.env` 가 보이면 커밋하지 말고 담당자에게 알린다.

### 1-4. 접속을 확인한다

```bash
cd ~/hanil/hhhs-db-manager && .venv/bin/hhhs-db check
```

`쓰기 권한 : NEOE 스키마에서 0개 테이블  ✅ 읽기 전용` 줄이 보이면 정상이다. 실패하면 hhhs-db-manager README 의 "오류가 나면" 표를 본다(대부분 `.env` 값·네트워크 문제).

## 2. 노트북 열기와 커널 선택

### VS Code

1. **파일 → 폴더 열기** 로 `~/hanil` (두 저장소의 상위 폴더)을 연다.
2. 노트북 파일을 더블클릭한다. 오른쪽 위 **커널 선택 → Python 환경** 에서 `hhhs-db-manager/.venv` 의 파이썬을 고른다. 두 노트북 모두 이 커널이다.
3. 셀은 클릭 후 `Shift+Enter` 로 실행한다.

### JupyterLab

```bash
cd ~/hanil/hhhs-db-manager && .venv/bin/jupyter lab ..
```

브라우저에서 왼쪽 파일 탐색기로 두 저장소 폴더를 오가며 노트북을 연다. 커널은 `Python 3 (ipykernel)` 를 고른다(이 venv 의 `jupyter` 로 띄웠으므로 그 파이썬이다). `uv run jupyter lab` 은 쓰지 않는다 — 잠금 파일 기준으로 환경을 다시 맞추면서 노트북용 패키지를 지울 수 있다.

다른 파이썬(anaconda 등)을 커널로 고르면 `ModuleNotFoundError: No module named 'pymssql'` 이 난다. 커널을 다시 고르면 된다.

## 3. 테스트 A — 조회: `hanil-order-check/hanilsf_optimizer.ipynb`

저장된 출력은 2026-09-14 실행 결과다. 재고는 매일 바뀌므로 숫자는 달라지고 **모양**만 같으면 된다.

| 순서 | 셀 | 하는 일 | 정상이면 |
| --- | --- | --- | --- |
| A1 | 0절 import | 모듈 로드, 접속정보 확인 | `준비 완료 · 기본 대체 기준: {...}` 한 줄 |
| A2 | 1절 `p = {...}` | 조회할 상품 지정. 처음엔 그대로 둔다 | dict 가 그대로 표시 |
| A3 | 2절 `stock(p)` | **모듈1 재고 수** | `rolls`(현재고) · `open_rolls`(앞선 수주 선점) · `avail_rolls`(= rolls − open, 지금 출하 가능) 네 숫자 |
| A4 | 3절 `similar_products(p, n=10)` | **모듈2 유사 상품** — 같은 품목·등급, 폭 +200mm · 길이 +20m 안의 후보를 손실 적은 순으로 | 목록의 `kind` 가 `폭+50` 처럼 무엇이 다른지 보여준다. `[]` 면 기준 안에 후보 없음 |
| A5 | 3-1절 `rule=` | 임시로 폭 +300 · 길이 +500 · 등급 A1 까지 넓혀서 | 후보가 늘거나 같다. 파일에 저장되지 않는다 |
| A6 | 4절 `check({**p, "rolls": 60})` | 60롤 주문의 **배분** | 재고출하 + 대체검토 + 생산의뢰 롤수 합 = 60, 보고서에 후보별 배정 롤수 |
| A7 | 4절 요약 dict | 같은 결과의 숫자만 | `stock_rolls + sub_rolls + prod_rolls == need_rolls` |
| A8 | 5절 오류 예 | 잘못된 입력 | `ValueError: … 1·2호기 품목 …`, `필수 키가 빠졌습니다: ['length']` 두 줄 |

A3~A7 의 숫자를 **4절 검증표에 적어 둔다.**

다른 상품으로 해보려면 A2 의 `p` 를 바꾸고 A3~A7 을 다시 실행한다.

```python
p = {"item": "2PD2040NT1N", "width": 1070, "length": 2000, "grade": "A"}   # 품목코드 · 폭 mm · 길이 m · 등급(생략 시 A)
```

품목코드는 첫 자리 1(1호기 PET/PLA) 또는 2(2호기 PP) 만 된다. 코드를 모르면 `hhhs_db_manager.ipynb` 4절 "값으로 찾기"에서 `MA_PITEM` 의 `NM_ITEM` 으로 검색한다.

## 4. 테스트 B — 검증: `hhhs-db-manager/hhhs_db_manager.ipynb` 6절 자유 SQL

목표: 테스트 A 가 보여준 숫자가 ERP 원장·수주 테이블에서 그대로 나오는지 확인한다.

### B1. 0절을 실행한다

`import hhhs_db_manager as db` 와 도우미 함수가 준비된다. 입력창(`ask`)이 뜨는 절은 이번 검증에 쓰지 않는다.

### B2. 6절 셀의 내용을 아래로 바꿔 실행한다 — 현재고

`item` 과 폭·길이 범위를 테스트 A 의 `p` 에 맞춘다. 범위는 기본 대체 기준(폭 +200, 길이 +20)이다.

```python
df = None
sql = """
WITH bal AS (
  SELECT CD_ITEM, NO_LOT, TRY_CAST(CD_MNG1 AS int) AS width, TRY_CAST(CD_MNG2 AS int) AS length, CD_MNG3 AS grade,
         SUM(CASE WHEN FG_PS='1' THEN QT_IO ELSE -QT_IO END) AS kg
  FROM NEOE.MM_QTIOLOT
  WHERE CD_COMPANY='1000' AND CD_PLANT='3000' AND CD_SL='3000' AND DT_IO >= :ys AND CD_ITEM = :item
  GROUP BY CD_ITEM, NO_LOT, CD_MNG1, CD_MNG2, CD_MNG3
  HAVING SUM(CASE WHEN FG_PS='1' THEN QT_IO ELSE -QT_IO END) > 0.001)
SELECT CD_ITEM AS item, width, length, grade, COUNT(*) AS rolls, SUM(kg) AS kg
FROM bal
WHERE width BETWEEN :w AND :w + 200 AND length BETWEEN :l AND :l + 20
GROUP BY CD_ITEM, width, length, grade
ORDER BY grade, width, length
"""
df = show(db.query(sql, item="2PD2030WH2N", w=1000, l=1000, ys="20260000"))
```

- `ys` 는 재고 합산 시작(올해 기초행). 1~2월에 올해 기초행이 아직 없으면 `"20250000"` 처럼 전년으로 바꾼다(테스트 A 보고서의 `[원장 YYYY0000 이후]` 값을 그대로 쓰면 된다).
- 읽는 법: 폭·길이·등급이 `p` 와 정확히 같은 행의 `rolls` = 테스트 A 의 `rolls`. 나머지 행 = 테스트 A 후보 목록의 `rolls`.

### B3. 같은 셀을 아래로 바꿔 실행한다 — 동일규격 미출하 수주

```python
df = None
sql = """
SELECT L.NO_SO, L.SEQ_SO, H.DT_SO, L.QT_SO, L.QT_GI, L.QT_SO - L.QT_GI AS open_kg, L.NUM_USERDEF3 AS rolls
FROM NEOE.SA_SOL L
JOIN NEOE.SA_SOH H ON H.CD_COMPANY = L.CD_COMPANY AND H.NO_SO = L.NO_SO
WHERE L.CD_COMPANY='1000' AND L.CD_PLANT='3000' AND L.CD_ITEM = :item
  AND L.QT_SO > L.QT_GI AND L.STA_SO='R' AND H.DT_SO >= :since
  AND TRY_CAST(L.NUM_USERDEF1 AS int) = :w AND TRY_CAST(L.NUM_USERDEF2 AS int) = :l AND L.TXT_USERDEF1 = :g
ORDER BY H.DT_SO
"""
df = show(db.query(sql, item="2PD2030WH2N", w=1000, l=1000, g="A", since="20260101"))
```

- 읽는 법: 행 수 = 테스트 A 보고서의 `미출하수주 N롤 (K건)` 의 K. `rolls` 합(올림) = `open_rolls`. `rolls` 가 비어 있는 행은 `open_kg ÷ 롤당 kg`(보고서 첫 줄의 `롤당 … kg`)로 환산한다.
- 여기 나오는 수주번호(`NO_SO`)는 사내 자료다. 화면 캡처나 메신저로 밖에 보내지 않는다.

### B4. 손으로 셈해 배분을 맞춰 본다

1. 가용 = B2 의 동일규격 `rolls` − B3 의 미출하 롤 → 테스트 A 의 `avail_rolls`
2. 재고출하 = min(가용, 주문롤) → `stock_rolls`
3. 남은 롤을 B2 의 다른 행(같은 품목 → 같은 등급 → 좁은 폭 → 짧은 길이 순)에 가용만큼 차례로 배정 → `sub_rolls`
4. 그래도 남으면 생산의뢰 → `prod_rolls`

### B5. 검증표

| 항목 | 테스트 A 값 | 테스트 B 값 | 일치 |
| --- | --- | --- | --- |
| 동일규격 현재고 롤 (`rolls`) | | B2 동일규격 행 `rolls` | |
| 미출하 롤 (`open_rolls`) | | B3 `rolls` 합 | |
| 가용 롤 (`avail_rolls`) | | B4-1 | |
| 후보 규격과 롤수 (`similar_products`) | | B2 나머지 행 | |
| 재고출하 / 대체검토 / 생산의뢰 | | B4-2 ~ B4-4 | |

전부 일치하면 검증 끝. 다르면 먼저 `ys`(합산 시작)와 `since`(수주 조회 시작) 가 테스트 A 와 같은지 확인하고, 그래도 다르면 두 노트북의 출력을 저장해 담당자에게 전달한다.

### B6. (선택) 결과 저장

8절 "결과 저장"으로 마지막 `df` 를 `.csv` 로 남길 수 있다. 저장 파일도 사내 자료이며 저장소에는 올리지 않는다(`*.csv` 는 `.gitignore` 로 막혀 있다).

## 5. 자주 나는 오류

| 메시지 | 원인 | 조치 |
| --- | --- | --- |
| `ModuleNotFoundError: No module named 'pymssql'` 또는 `'hhhs_db_manager'` | 커널이 다른 파이썬 | 2절대로 `hhhs-db-manager/.venv` 커널을 다시 고른다 |
| `ModuleNotFoundError: No module named 'hanilsf_optimizer'` | 노트북을 다른 폴더로 옮겨 열었다 | `hanil-order-check` 폴더 안에서 연다 |
| `ConfigError` / 접속 실패 | `.env` 값·네트워크 | 1-3, 1-4 를 다시 한다. hhhs-db-manager README "오류가 나면" 표 |
| `ValueError: … MA_PITEM(의령 3000)에 없는 품목코드` | 코드 오타 또는 붙여넣기에 섞인 보이지 않는 문자 | 코드를 다시 친다. 메시지에 받은 값과 글자 수가 찍힌다 |
| `ValueError: … 1·2호기 품목 … 만 지원` | 3·4호기 코드 | 첫 자리 1 또는 2 인 코드만 |
| `QueryTimeout` | 조회가 60초를 넘음 | 기간·범위를 좁힌다. 큰 조회는 담당자와 상의 |

## 6. 지켜야 할 것

- 모든 조회는 읽기 전용이다. 6절에 SELECT 외의 문장을 넣지 않는다.
- `.env`, 조회 결과(csv·xlsx), 캡처는 저장소에 올리거나 외부로 보내지 않는다. 노트북을 다시 실행해 출력을 저장한 채 커밋하려면 담당자와 공유 범위를 먼저 정한다.
- 거래처별 대체 기준(`hanil-order-check/substitute_rules.json`)은 팀이 함께 쓰는 값이다. 시험 삼아 넣은 거래처 항목은 지운 뒤 커밋한다.
- 브랜치 규칙: `main` 에 직접 커밋하지 않고 `feat/<작업명>` → `dev` → `main` 순서로 합친다. 커밋 메시지는 `feat: …` / `fix: …` / `docs: …` 형식.
