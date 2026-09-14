"""hanilsf_optimizer — 의령공장 1·2호기 부직포: 재고 수 · 유사(대체) 상품 · 재고출하/대체검토/생산의뢰 배분.

    import hanilsf_optimizer as ho
    p = {"item": "2PD2040NT1N", "width": 1070, "length": 2000, "grade": "A"}   # 상품을 특정하는 dict (등급 생략 시 A)
    ho.stock(p)                   # 모듈1: {"item", "width", "length", "grade", "rolls": 30, "kg": 2568.0, "open_rolls": 6, "avail_rolls": 24}
    ho.similar_products(p, n=10)  # 모듈2: [{"item", …, "kind": "폭+30", "rolls": 5, "avail_rolls": 5}, …]  손실 적은 순
    ho.check({**p, "rolls": 48})  # 배분: 재고출하 24 + 대체검토 14 + 생산의뢰 10 (dict; JSON 으로는 ho.jsonable(...))

근거: 프로젝트 루트 `주문접수_재고조회_절차.md` (2026-09-11). ERP(NEOE)는 hhhs_db_manager 로 읽기 전용 SELECT 만 실행한다.
한 주문이 세 경로에 동시에 걸릴 수 있다 — 예: 48롤 = 재고 24롤 + 대체(슬리팅) 5롤 + 생산 19롤.

CLI (설치 전이면 `hanilsf` 대신 `../DB조회도구/.venv/bin/python hanilsf_optimizer.py`):
    hanilsf 2PD2040NT1N -w 1070 -l 2000                 # 수량 없음 → 재고 수 + 유사 상품 (JSON)
    hanilsf 2PD2040NT1N -w 1070 -l 2000 -g A -r 48      # 수량 있음 → 배분 보고서 (--json 이면 dict)
    hanilsf 2PD2040NT1N -w 1070 -l 2000 --kg 4108.8 --partner 거래처코드

대체 기준: 기본은 "같은 품목·등급, 폭 +200mm · 길이 +20m 까지(슬리팅·재단 가정)". 거래처별 허용 범위는 `substitute_rules.json` 에
영업담당자가 적는다 — set_rule("거래처코드", width_plus=300, length_plus=500, items=["2PD2030WH1N"], grades=["A1"], note="…").
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from dataclasses import dataclass, fields
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

# hhhs_db_manager(팀 공용 hhhs-db-manager)를 찾는 순서: pip 설치본 → HHHS_DB_DIR → 이 폴더 옆의 DB조회도구/
sys.path.append(os.environ.get("HHHS_DB_DIR") or str(Path(__file__).resolve().parents[1] / "DB조회도구"))
import hhhs_db_manager as db  # noqa: E402  (.env 는 도구가 HHHS_ENV_FILE → 현재 폴더 → 자기 폴더 순으로 읽는다 — 이 저장소에는 두지 않는다)

COMPANY, PLANT, SL = "1000", "3000", "3000"          # 회사 · 의령공장 · 의령 SB창고
GRADES = ("A", "A0", "A1", "B", "C", "D", "R")
MACHINES = ("1", "2")                                # 품목코드 첫 자리: 1호기 PET/PLA · 2호기 PP
SPEC = ["item", "width", "length", "grade"]
DEFAULT_RULE = {"width_plus": 200, "length_plus": 20, "items": [], "grades": [], "note": ""}   # 폭 mm · 길이 m
# 대체 기준 파일: HANILSF_RULES → 이 모듈 옆(소스 체크아웃·editable 설치) → 현재 폴더(pip 설치본)
_local_rules = Path(__file__).with_name("substitute_rules.json")
RULES_FILE = Path(os.environ.get("HANILSF_RULES") or (_local_rules if _local_rules.exists() else Path.cwd() / "substitute_rules.json"))


@dataclass
class Product:
    """상품을 특정하는 규격. dict 로 받을 때(from_dict)는 item·width·length·grade 네 키만 보고 나머지는 무시한다."""
    item: str
    width: int            # mm
    length: int           # m
    grade: str = "A"      # 미지정 시 A 출고 (업무 규칙)

    def __post_init__(self):
        raw = self.item
        self.item = str(self.item).strip().upper()
        self.grade = (self.grade or "A").strip().upper()
        if not re.fullmatch(r"[0-9A-Z_]+", self.item):
            raise ValueError(f"품목코드에 허용되지 않는 문자가 있습니다: {raw!r} ({len(str(raw))}자). 영문·숫자·밑줄만 가능합니다.")
        if self.item[:1] not in MACHINES:
            raise ValueError(f"{self.item}: 1·2호기 품목(코드 첫 자리 1/2)만 지원합니다.")
        try:
            self.width, self.length = int(self.width), int(self.length)
        except (TypeError, ValueError):
            raise ValueError(f"폭(mm)·길이(m)는 정수여야 합니다: width={self.width!r}, length={self.length!r}") from None
        if self.width <= 0 or self.length <= 0:
            raise ValueError("폭(mm)·길이(m)는 양수여야 합니다.")
        if self.grade not in GRADES:
            raise ValueError(f"등급은 {GRADES} 중 하나여야 합니다.")

    @classmethod
    def from_dict(cls, d):
        if isinstance(d, cls):
            return d
        if isinstance(d, Product):
            d = vars(d)
        keys = [f.name for f in fields(cls)]
        missing = [k for k in keys[:3] if k not in d]
        if missing:
            raise ValueError(f"필수 키가 빠졌습니다: {missing} (필요: item, width, length)")
        return cls(**{k: d[k] for k in keys if k in d})


@dataclass
class Order(Product):
    rolls: int | None = None
    kg: float | None = None
    partner: str | None = None   # 거래처코드(CD_PARTNER) — 거래처별 대체 기준 적용

    def __post_init__(self):
        super().__post_init__()
        if not self.rolls and not self.kg:
            raise ValueError("롤수(rolls) 또는 중량(kg) 중 하나는 필요합니다.")


def roll_kg(width_mm: float, length_m: float, gsm: float) -> float:
    """kg = 폭(m) × 길이(m) × 평량(g/㎡) ÷ 1000 — ERP·생산의뢰서·스케줄 공통 식."""
    return width_mm / 1000 * length_m * gsm / 1000


def allocate(need: int, exact_avail: int, subs: list[tuple]) -> tuple[int, list[tuple], int]:
    """(재고출하 롤, [(후보키, 배정 롤)…], 생산의뢰 롤). subs 는 (키, 가용롤) 우선순위 순."""
    stock = min(max(exact_avail, 0), need)
    need -= stock
    taken = []
    for key, avail in subs:
        take = min(max(avail, 0), need)
        if take:
            taken.append((key, take))
            need -= take
    return stock, taken, need


def jsonable(v):
    """stock()/similar_products()/check() 결과를 json.dumps 가능한 값으로 — DataFrame → 행 목록, numpy·Decimal → 파이썬 수, NaN → None."""
    if isinstance(v, pd.DataFrame):
        return [jsonable(r) for r in v.to_dict("records")]
    if isinstance(v, Product):
        return jsonable(vars(v))
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, Decimal):
        v = float(v)
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


# ---------------------------------------------------------------------------
# 거래처별 대체 기준 (영업담당자 입력)
# ---------------------------------------------------------------------------
def load_rules(path: Path | str | None = None) -> dict:
    p = Path(path or RULES_FILE)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def rule_for(partner: str | None, rules: dict, override: dict | None = None) -> dict:
    """기본값 ← rules['default'] ← rules[거래처] ← override(이 호출에만 쓰는 임시 기준, 저장 안 함) 순으로 덮어쓴다.
    override 의 items/grades 는 목록이어야 한다."""
    r = {**DEFAULT_RULE, **rules.get("default", {})}
    if partner and partner in rules:
        r = {**r, **rules[partner]}
    if override:
        r = {**r, **{k: v for k, v in override.items() if k in DEFAULT_RULE and v is not None}}
    r["items"] = [i.strip().upper() for i in r["items"]]
    r["grades"] = [g.strip().upper() for g in r["grades"]]
    return r


def set_rule(partner: str, path: Path | str | None = None, **fields) -> dict:
    """영업담당자가 정해진 폼으로 적은 허용 범위를 저장한다.
    fields: width_plus(mm) · length_plus(m) · items(허용 대체 품목코드 목록) · grades(허용 대체 등급 목록) · note(코멘트)."""
    bad = set(fields) - set(DEFAULT_RULE)
    if bad:
        raise ValueError(f"알 수 없는 기준: {sorted(bad)} (허용: {sorted(DEFAULT_RULE)})")
    p = Path(path or RULES_FILE)
    rules = load_rules(p)
    rules[partner] = {**rules.get(partner, {}), **fields, "updated": date.today().isoformat()}
    p.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
    return rules[partner]


# ---------------------------------------------------------------------------
# 조회
# ---------------------------------------------------------------------------
def year_start(today: date) -> str:
    """합산 시작일. 올해 기초행(FG_IO 000, DT_IO 'YYYY0000')은 연초 결산 뒤에야 생긴다(생성일 2024-02-09 · 2025-01-27 · 2026-02-14).
    그 전에는 전년 기초부터 합산해야 이월 재고가 빠지지 않는다."""
    ys = f"{today.year}0000"
    has = db.query("SELECT TOP 1 1 AS x FROM NEOE.MM_QTIOLOT WHERE CD_COMPANY=:c AND CD_PLANT=:p AND FG_IO='000' AND DT_IO=:ys",
                   c=COMPANY, p=PLANT, ys=ys)
    return ys if not has.empty else f"{today.year - 1}0000"


def item_master(item: str) -> dict | None:
    df = db.query("""
        SELECT CD_ITEM, NM_ITEM, CLS_ITEM, NUM_USERDEF1 AS gsm, CD_USERDEF2 AS color, CD_USERDEF3 AS tp, CD_GISL
        FROM NEOE.MA_PITEM
        WHERE CD_COMPANY=:c AND CD_PLANT=:p AND CD_ITEM=:item""", c=COMPANY, p=PLANT, item=item)
    return None if df.empty else df.iloc[0].to_dict()


def _master(item: str) -> tuple[dict, float]:
    """품목 마스터 + 평량. 없거나 제품(003)이 아니면 ValueError."""
    m = item_master(item)
    if m is None:
        raise ValueError(f"{item!r}({len(item)}자): MA_PITEM(의령 3000)에 없는 품목코드입니다. 자동완성 목록에서 고르거나 코드 전체(11자)를 확인하세요.")
    if m["CLS_ITEM"] != "003":
        raise ValueError(f"{item}: 제품(003)이 아님 (CLS_ITEM={m['CLS_ITEM']})")
    return m, float(m["gsm"] or 0)


def _in(items: list[str]) -> tuple[str, dict]:
    ph = {f"i{n}": it for n, it in enumerate(items)}
    return ", ".join(":" + k for k in ph), ph


def onhand(items: list[str], ys: str) -> pd.DataFrame:
    """MM_QTIOLOT 합산 — 품목·폭·길이·등급별 잔량>0 인 LOT 수(롤)와 kg. ERP 수주화면 현재고와 같은 기준.

    MM_QTIOLOT 은 MM_QTIO 의 LOT 분해 상세이지 별도 원장이 아니다. 둘을 더하면 이중계상된다
    (2026-09-11 확인: 품목 1TD2018NT1C 2026년 입고가 양쪽 모두 361,155.1800 으로 동일).
    롤 수는 LOT 단위라 MM_QTIOLOT 로만 셀 수 있고, 금액·수량 누계만 필요하면 MM_PINVN
    (P_YR 연도별 기초+입고-출고, MM_QTIO 누계와 일치)을 쓰는 편이 가볍다.
    """
    sql_in, ph = _in(items)
    df = db.query(f"""
        WITH bal AS (
          SELECT CD_ITEM, NO_LOT, TRY_CAST(CD_MNG1 AS int) AS width, TRY_CAST(CD_MNG2 AS int) AS length,
                 CD_MNG3 AS grade, SUM(CASE WHEN FG_PS='1' THEN QT_IO ELSE -QT_IO END) AS kg
          FROM NEOE.MM_QTIOLOT
          WHERE CD_COMPANY=:c AND CD_PLANT=:p AND CD_SL=:sl AND DT_IO >= :ys AND CD_ITEM IN ({sql_in})
          GROUP BY CD_ITEM, NO_LOT, CD_MNG1, CD_MNG2, CD_MNG3
          HAVING SUM(CASE WHEN FG_PS='1' THEN QT_IO ELSE -QT_IO END) > 0.001)
        SELECT CD_ITEM AS item, width, length, grade, COUNT(*) AS rolls, SUM(kg) AS kg
        FROM bal GROUP BY CD_ITEM, width, length, grade""", c=COMPANY, p=PLANT, sl=SL, ys=ys, **ph)
    return df.astype({"rolls": int, "kg": float})


def open_so(items: list[str], since: str) -> pd.DataFrame:
    """미출하 수주 라인 (QT_SO > QT_GI, 진행상태 R). 출하의뢰(SA_GIRL)는 이중차감 방지로 빼지 않는다.

    STA_SO: 'R' 진행 · 'C' 종결(추정 — C 인데 미출하 잔량이 남은 라인이 다수 있어 취소·강제종결로 보고 제외).
    """
    sql_in, ph = _in(items)
    return db.query(f"""
        SELECT L.CD_ITEM AS item, TRY_CAST(L.NUM_USERDEF1 AS int) AS width, TRY_CAST(L.NUM_USERDEF2 AS int) AS length,
               L.TXT_USERDEF1 AS grade, L.NO_SO, L.SEQ_SO, H.DT_SO, H.CD_PARTNER,
               L.QT_SO, L.QT_GI, L.QT_SO-L.QT_GI AS open_kg, L.NUM_USERDEF3 AS rolls
        FROM NEOE.SA_SOL L JOIN NEOE.SA_SOH H ON H.CD_COMPANY=L.CD_COMPANY AND H.NO_SO=L.NO_SO
        WHERE L.CD_COMPANY=:c AND L.CD_PLANT=:p AND L.CD_ITEM IN ({sql_in})
          AND L.QT_SO > L.QT_GI AND L.STA_SO='R' AND H.DT_SO >= :since
        ORDER BY H.DT_SO""", c=COMPANY, p=PLANT, since=since, **ph)


def open_prq(item: str, since: str) -> pd.DataFrame:
    """최근 생산요청 라인 (규격 컬럼이 비어 있어 품목 단위로만 본다). 이미 요청돼 있으면 중복 의뢰를 피한다.

    PR_PRQL.NO_SO 는 조회하지 않는다 — 2020년 이후 채움 0건이라 수주 역추적에 쓸 수 없다
    (2026-09-11 확인: 2018년 225/557, 2019년 603/3750, 2020년 2/4556, 2021~2026년 0).
    PR_WO.NO_SO · PR_PRQ_WO_LINK.NO_SO 도 같은 기간 전부 0건이라 대체 경로가 아니다.
    """
    return db.query("""
        SELECT NO_PRQ, DT_DLV, QT_PRQ, QT_ITEM AS qt_wo, QT_WORK
        FROM NEOE.PR_PRQL
        WHERE CD_COMPANY=:c AND CD_PLANT=:p AND CD_ITEM=:item AND DT_DLV >= :since
        ORDER BY DT_DLV DESC""", c=COMPANY, p=PLANT, item=item, since=since)


def availability(items: list[str], gsm: float, today: date) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """규격(품목·폭·길이·등급)별 현재고 − 미출하 수주 = 가용. (재고표[rolls·kg·open_rolls·avail], 미출하 수주 라인, 합산 시작일)"""
    ys = year_start(today)
    st = onhand(items, ys)
    so = open_so(items, f"{today.year}0101")
    # 미출하 롤수 = 라인 롤수 × 미출하 비율 (롤수 없으면 kg ÷ 그 규격의 롤당 kg) → 규격별 합산 후 현재고에서 차감
    so["open_rolls"] = [
        (r.rolls * r.open_kg / r.QT_SO) if pd.notna(r.rolls) and r.QT_SO
        else (r.open_kg / roll_kg(r.width, r.length, gsm) if r.width and r.length and gsm else 0)
        for r in so.itertuples()]
    opened = so.groupby(SPEC, as_index=False)["open_rolls"].sum()
    st = st.merge(opened, on=SPEC, how="left").fillna({"open_rolls": 0})
    st["open_rolls"] = st.open_rolls.apply(math.ceil)
    st["avail"] = (st.rolls - st.open_rolls).clip(lower=0)
    return st, so, ys


def _items(p: Product, rule: dict) -> list[str]:
    return [p.item] + [i for i in rule["items"] if i != p.item]


def _candidates(p: Product, rule: dict, st: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(동일규격 행, 대체 후보 행). 후보 풀: 허용 품목·등급, 폭 [주문, 주문+width_plus] · 길이 [주문, 주문+length_plus]
    (넓은 폭은 슬리팅, 긴 길이는 재단 가정). 후보는 손실 적은 순: 같은 품목 → 같은 등급 → 좁은 폭 → 짧은 길이."""
    grades = [p.grade] + [g for g in rule["grades"] if g != p.grade]
    pool = st[st.item.isin(_items(p, rule)) & st.grade.isin(grades)
              & (st.width >= p.width) & (st.width <= p.width + rule["width_plus"])
              & (st.length >= p.length) & (st.length <= p.length + rule["length_plus"])]
    is_exact = (pool.item == p.item) & (pool.width == p.width) & (pool.length == p.length) & (pool.grade == p.grade)
    exact = pool[is_exact]
    subs = pool[~is_exact].copy()
    subs["kind"] = ["·".join(k for k, on in (("품목", r.item != p.item), ("등급", r.grade != p.grade),
                                              (f"폭+{r.width - p.width}", r.width > p.width),
                                              (f"길이+{r.length - p.length}", r.length > p.length)) if on)
                    for r in subs.itertuples()]
    subs = subs.assign(_i=subs.item != p.item, _g=subs.grade != p.grade).sort_values(["_i", "_g", "width", "length"]).drop(columns=["_i", "_g"])
    return exact, subs


# ---------------------------------------------------------------------------
# 공개 API — 모듈1 stock() · 모듈2 similar_products() · 배분 check()
# ---------------------------------------------------------------------------
def stock(product: dict | Product, today: date | None = None) -> dict:
    """모듈1 — 입력 규격(품목·폭·길이·등급)의 재고 수.

    rolls·kg: 현재고(ERP 수주화면과 같은 기준, 의령 SB창고 잔량>0 LOT). open_rolls: 미출하 수주에 잡힌 롤.
    avail_rolls = rolls − open_rolls (0 이상) = 지금 출하에 쓸 수 있는 롤.
    """
    p = Product.from_dict(product)
    _, gsm = _master(p.item)
    st, _, _ = availability([p.item], gsm, today or date.today())
    ex = st[(st.item == p.item) & (st.width == p.width) & (st.length == p.length) & (st.grade == p.grade)]
    return {**vars(p), "rolls": int(ex.rolls.sum()), "kg": round(float(ex.kg.sum()), 1),
            "open_rolls": int(ex.open_rolls.sum()), "avail_rolls": int(ex.avail.sum())}


def similar_products(product: dict | Product, n: int = 10, *, partner: str | None = None, rule: dict | None = None,
                     rules_file: Path | str | None = None, today: date | None = None) -> list[dict]:
    """모듈2 — 대체 출고 후보 최대 n개, 손실 적은 순(같은 품목 → 같은 등급 → 좁은 폭 → 짧은 길이). 동일규격과 가용 0 인 규격은 뺀다.

    후보 범위(substitute_rules.json): default ← partner(거래처별 기준) ← rule(이 호출에만 쓰는 임시 dict
    {width_plus, length_plus, items, grades}). 기본은 같은 품목·등급, 폭 +200mm · 길이 +20m.
    각 항목: item·width·length·grade·kind("폭+30"·"길이+150"·"등급"·"품목" 조합)·rolls·kg·open_rolls·avail_rolls.
    """
    p = Product.from_dict(product)
    _, gsm = _master(p.item)
    r = rule_for(partner, load_rules(rules_file), rule)
    st, _, _ = availability(_items(p, r), gsm, today or date.today())
    _, subs = _candidates(p, r, st)
    return [dict(item=x.item, width=int(x.width), length=int(x.length), grade=x.grade, kind=x.kind,
                 rolls=int(x.rolls), kg=round(float(x.kg), 1), open_rolls=int(x.open_rolls), avail_rolls=int(x.avail))
            for x in subs[subs.avail > 0].head(n).itertuples()]


def check(order: dict | Order, today: date | None = None, rules_file: Path | str | None = None, override: dict | None = None) -> dict:
    """주문(규격 + rolls 또는 kg, 선택 partner)을 재고출하 / 대체검토 / 생산의뢰 롤수로 배분한다.
    override: 이 주문에만 적용하는 임시 대체 기준 {width_plus, length_plus, items, grades, note} — 파일에 저장하지 않는다.
    반환 dict 에는 DataFrame(subs·open_so·prq)이 들어 있다 — JSON 으로는 jsonable(check(...))."""
    o = Order.from_dict(order)
    today = today or date.today()
    rules = load_rules(rules_file)
    rule = rule_for(o.partner, rules, override)
    rule_source = "임시" if override else ("거래처" if o.partner and o.partner in rules else "기본")

    m, gsm = _master(o.item)
    rk = roll_kg(o.width, o.length, gsm)
    need_rolls = o.rolls or math.ceil(o.kg / rk)
    need_kg = o.kg or need_rolls * rk

    st, so, ys = availability(_items(o, rule), gsm, today)
    exact, subs = _candidates(o, rule, st)
    exact_avail = int(exact.avail.sum())
    stock_rolls, taken, prod_rolls = allocate(need_rolls, exact_avail, [(r.Index, int(r.avail)) for r in subs.itertuples()])
    subs["alloc"] = pd.Series(dict(taken)).reindex(subs.index).fillna(0).astype(int)
    sub_rolls = int(subs["alloc"].sum())

    return dict(
        order=o, master=m, rule=rule, rule_source=rule_source, roll_kg=rk, need_rolls=need_rolls, need_kg=need_kg, year_start=ys,
        onhand_rolls=int(exact.rolls.sum()), onhand_kg=float(exact.kg.sum()), open_rolls=int(exact.open_rolls.sum()),
        avail_rolls=exact_avail, open_so=so[(so.item == o.item) & (so.width == o.width) & (so.length == o.length) & (so.grade == o.grade)],
        stock_rolls=stock_rolls, sub_rolls=sub_rolls, prod_rolls=prod_rolls,
        decisions=[d for d, n in (("재고출하", stock_rolls), ("대체검토", sub_rolls), ("생산의뢰", prod_rolls)) if n > 0],
        subs=subs, prq=open_prq(o.item, (today - timedelta(days=14)).strftime("%Y%m%d")),
    )


def report(r: dict) -> str:
    o, m, need, rule = r["order"], r["master"], r["need_rolls"], r["rule"]
    pct = lambda n: f"{n}롤 ({n / need:.0%})"
    rule_txt = f"폭 +{rule['width_plus']}mm · 길이 +{rule['length_plus']}m" + (f" · 품목 {','.join(rule['items'])}" if rule["items"] else "") \
        + (f" · 등급 {','.join(rule['grades'])}" if rule["grades"] else "") + (f" · 비고 {rule['note']}" if rule["note"] else "")
    L = [f"주문   {o.item} {m['NM_ITEM']} {float(m['gsm']):g}g {m['color']}/{m['tp']} | {o.width}mm × {o.length}m | {o.grade} | "
         f"{need}롤 = {r['need_kg']:,.1f} kg (롤당 {r['roll_kg']:.1f} kg)" + (f" | 거래처 {o.partner}" if o.partner else ""),
         f"현재고 동일규격 {r['onhand_rolls']}롤 / {r['onhand_kg']:,.1f} kg  −  미출하수주 {r['open_rolls']}롤 ({len(r['open_so'])}건)"
         f"  =  가용 {r['avail_rolls']}롤   [원장 {r['year_start']} 이후, 창고 {SL}]",
         f"판단   ▶ {' + '.join(r['decisions'])}",
         f"       재고출하 {pct(r['stock_rolls'])} · 대체검토 {pct(r['sub_rolls'])} · 생산의뢰 {pct(r['prod_rolls'])}"
         + (f" = {r['prod_rolls'] * r['roll_kg']:,.1f} kg" if r["prod_rolls"] else "")]
    s = r["subs"]
    L.append(f"\n대체 후보 [{r['rule_source']} 기준: {rule_txt}] 넓은 폭은 슬리팅·긴 길이는 재단 가정:"
             + (" 없음" if s.empty else ""))
    L += [f"  [{x.kind}] {x.item} {x.width}×{x.length} {x.grade}  현재고 {x.rolls} − 미출하 {x.open_rolls} = 가용 {x.avail}롤"
          + (f"  → 배정 {x.alloc}롤" if x.alloc else "") for x in s.itertuples()]
    if not r["open_so"].empty:
        L.append("\n동일규격 미출하 수주:")
        L += [f"  {x.NO_SO}-{x.SEQ_SO} {x.DT_SO} 잔량 {x.open_kg:,.1f} kg" for x in r["open_so"].itertuples()]
    p = r["prq"]
    L.append(f"\n최근 14일 생산요청(품목 단위): {'없음' if p.empty else f'{len(p)}건 / 요청 {p.QT_PRQ.sum():,.1f} kg, 작업 {p.QT_WORK.sum():,.1f} kg'}")
    L += [f"  {x.NO_PRQ} 납기 {x.DT_DLV} 요청 {x.QT_PRQ:,.1f} 작업 {x.QT_WORK:,.1f}" for x in p.head(5).itertuples()]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 epilog="수량(-r/--kg)이 없으면 재고 수 + 유사 상품을 JSON 으로, 있으면 배분 보고서를 출력한다.")
    ap.add_argument("item", help="품목코드 (예 2PD2040NT1N)")
    ap.add_argument("-w", "--width", type=int, required=True, help="폭 mm")
    ap.add_argument("-l", "--length", type=int, required=True, help="길이 m")
    ap.add_argument("-g", "--grade", default="A")
    ap.add_argument("-r", "--rolls", type=int)
    ap.add_argument("--kg", type=float)
    ap.add_argument("--partner", help="거래처코드 — substitute_rules.json 의 거래처별 대체 기준 적용")
    ap.add_argument("--rules", help=f"대체 기준 파일 (기본 {RULES_FILE})")
    ap.add_argument("-n", type=int, default=10, help="유사 상품 최대 개수 (기본 10)")
    ap.add_argument("--json", action="store_true", help="배분 결과를 보고서 대신 JSON 으로")
    a = ap.parse_args(argv)
    p = dict(item=a.item, width=a.width, length=a.length, grade=a.grade)
    if not a.rolls and not a.kg:
        out = {"stock": stock(p), "similar_products": similar_products(p, a.n, partner=a.partner, rules_file=a.rules)}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    r = check({**p, "rolls": a.rolls, "kg": a.kg, "partner": a.partner}, rules_file=a.rules)
    print(json.dumps(jsonable(r), ensure_ascii=False, indent=2) if a.json else report(r))


if __name__ == "__main__":
    main()
