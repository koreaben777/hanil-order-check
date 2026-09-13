# hanil-order-check — 주문 접수 시 재고 출하 · 대체 검토 · 생산 의뢰 배분

의령공장 1·2호기 부직포 주문(품목·폭·길이·등급·롤수 또는 kg)을 받아 ERP(NEOE, **읽기 전용 SELECT**)에서
주문 롤수를 **재고출하 / 대체검토 / 생산의뢰** 세 경로에 나눠 배정한다. 한 주문이 세 경로에 동시에 걸릴 수 있다
(예: 48롤 = 재고 6 + 대체 16 + 생산 26). 로컬 웹앱과 CLI, 파이썬 함수 세 가지로 쓴다.

| 파일 | 역할 |
| --- | --- |
| `order_check.py` | 판단 모듈 + CLI. `check(Order(...))` 가 배분 결과 dict 를 돌려준다 |
| `app.py` · `index.html` | 로컬 웹앱 (표준 라이브러리 `http.server`, 127.0.0.1 전용) |
| `substitute_rules.json` | 대체 기준. 기본값 + 거래처별 허용 범위(영업담당자 입력) |
| `test_order_check.py` | DB 없이 도는 자가 점검 |
| `TESTING.md` | 실행 방법과 기능 테스트용 입력값 |

## 준비 — 반드시 hhhs-db-manager 가 설치된 파이썬으로 실행한다

**요구사항: [hhhs-db-manager](https://github.com/koreaben777/hhhs-db-manager)** — 이 앱은 ERP 조회를 그 팀 공용 도구(`hhhs_db_manager.py` + `.env`)에 맡긴다.
없으면 먼저 `git clone https://github.com/koreaben777/hhhs-db-manager` 한 뒤 그 README 대로 `.venv` 와 `.env` 를 준비한다.
그 도구의 의존성(**pymssql**, SQLAlchemy, pandas, python-dotenv)이 들어 있는 파이썬으로 띄워야 한다. 터미널에서 그냥 `python app.py` 를 치면 맥 기본 파이썬(anaconda·시스템)이 잡히는데, 거기에는 보통 pymssql 이 없다.
그러면 **서버는 정상으로 뜨고 화면도 열리지만, "판단하기"를 누르는 첫 조회에서 `ModuleNotFoundError: No module named 'pymssql'` 가 난다.**

| 방법 | 언제 | 실행 파이썬 |
| --- | --- | --- |
| A. 팀 작업 사본의 가상환경 사용 (권장) | `DB조회도구/`(hhhs-db-manager 작업 사본) 옆에 이 저장소를 `dev/` 로 둔 경우 | `../DB조회도구/.venv/bin/python` |
| B. 다른 위치의 [hhhs-db-manager](https://github.com/koreaben777/hhhs-db-manager) 사용 | 저장소를 아무 곳에나 클론한 경우 | 그 도구의 venv 파이썬 + `HHHS_DB_DIR=<hhhs_db_manager.py 폴더>` |
| C. 내 파이썬에 도구를 설치 | anaconda 등 평소 쓰는 파이썬으로 띄우고 싶을 때 | `pip install -e <hhhs-db-manager 폴더>` 후 그 `python` |

- `.env`(접속정보)는 hhhs-db-manager 폴더에만 둔다. **이 저장소에는 절대 커밋하지 않는다** (`.gitignore` 로 막아 둠).
- 파이썬 3.10+. 이 저장소 자체는 의존성을 추가하지 않는다.
- 접속·권한 자가점검: `<venv>/bin/hhhs-db check`

## 실행

경로는 자기 환경에 맞게 바꾼다(아래는 방법 A, 저장소가 `~/Documents/Eugene_Group/한일합섬/dev` 에 있을 때).

```bash
cd ~/Documents/Eugene_Group/한일합섬/dev
../DB조회도구/.venv/bin/python app.py                                                   # 웹앱 → http://127.0.0.1:8765  (Ctrl+C 종료)
../DB조회도구/.venv/bin/python order_check.py 2PD2040NT1N -w 1070 -l 2000 -g A -r 48    # CLI
../DB조회도구/.venv/bin/python order_check.py 2PD2040NT1N -w 1070 -l 2000 --kg 4108.8 --partner 거래처코드
../DB조회도구/.venv/bin/python test_order_check.py                                      # 자가 점검 (DB 불필요)
```

복사해서 바로 쓸 수 있는 명령 모음과 테스트 입력값은 `TESTING.md`.
Claude 앱의 브라우저 패널에서는 프로젝트 루트 `.claude/launch.json` 의 `order-check` 설정으로 띄운다.

### 웹앱 화면

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

코드에서는 `set_rule("거래처코드", width_plus=300, length_plus=500, grades=["A1"], note="…")`, CLI 는 `--partner 거래처코드`. `default` 를 바꾸면 전 거래처 기본값이 바뀐다.
거래처 기준 파일은 팀이 함께 쓰는 값이므로 바꾸면 커밋해서 공유한다(개인 실험은 `--rules 다른파일.json`).

## 연초 처리

재고 합산은 올해 기초행(`FG_IO='000'`, `DT_IO='YYYY0000'`)부터 시작한다. 이 기초행은 ERP 연말 결산 뒤(보통 1월 말~2월 중순)에야 생긴다.
그 전에 올해 기준으로 합산하면 이월 재고가 통째로 빠지므로, `year_start()` 가 올해 기초행 유무를 확인해 없으면 전년 기초부터 합산한다.

## 한계 (실무 확정 필요)

- `STA_SO='R'`=진행, `'C'`=종결은 데이터 분포로 추정한 값. 오래된 소량 잔량 라인도 차감된다.
- 대체 후보는 자동 출고가 아니라 후보 표시(영업 판단). 과거 기록으로 거래처별 허용 수준을 자동 학습하지는 않는다 — 거래처 기준을 사람이 적는다.
- 양품/불량 구분 없음(ERP 화면과 동일). 3·4호기(MB·합지) 품목은 거부한다.
- 인증 없는 로컬 전용(127.0.0.1). 다른 기기에서 쓰려면 바인딩 주소와 접근 통제를 따로 정해야 한다.
