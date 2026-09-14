"""DB 없이 도는 자가 점검:  ../DB조회도구/.venv/bin/python test_hanilsf_optimizer.py"""
import json
import tempfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pandas as pd

import hanilsf_optimizer as ho

TODAY = date(2026, 9, 10)
P = {"item": "2PD2040NT1N", "width": 1070, "length": 2000}


def test_roll_kg():
    assert abs(ho.roll_kg(1070, 2000, 40) - 85.6) < 1e-9          # 절차서 §3 예시
    assert abs(ho.roll_kg(1070, 2000, 40) * 48 - 4108.8) < 1e-9


def test_allocate():
    assert ho.allocate(48, 54, []) == (48, [], 0)                              # 전량 재고
    assert ho.allocate(48, 6, []) == (6, [], 42)                               # 재고 + 생산
    assert ho.allocate(12, 0, [("a", 5), ("b", 20)]) == (0, [("a", 5), ("b", 7)], 0)   # 대체만, 순서대로
    assert ho.allocate(48, 24, [("a", 5), ("b", 0)]) == (24, [("a", 5)], 19)  # 50% 재고 · 10% 대체 · 40% 생산
    assert ho.allocate(10, -3, [("a", -1)]) == (0, [], 10)                     # 음수 가용은 0 취급


def test_product_and_order_validation():
    for bad in (dict(item="3PD2040NT1N", width=1, length=1),          # 3호기 범위 밖
                dict(item="2PD2040NT1N", width=0, length=1),
                dict(item="2PD2040NT1N", width="넓게", length=1),      # 정수 아님
                dict(item="2PD2040NT1N", width=1, length=1, grade="Z"),
                dict(item="2PD2040NT1N", width=1)):                    # length 빠짐
        try:
            ho.Product.from_dict(bad)
        except ValueError:
            continue
        raise AssertionError(bad)
    p = ho.Product.from_dict({"item": " 2pd2040nt1n ", "width": "1070", "length": 2000.0, "grade": "", "name": "무시되는 키"})
    assert (p.item, p.width, p.length, p.grade) == ("2PD2040NT1N", 1070, 2000, "A")
    assert ho.Product.from_dict(p) is p
    try:
        ho.Order.from_dict(P)                                          # 롤수·kg 둘 다 없음
    except ValueError:
        pass
    else:
        raise AssertionError("Order 는 rolls 또는 kg 가 필요")
    o = ho.Order.from_dict({**P, "kg": 100, "partner": "P1"})
    assert (o.grade, o.kg, o.partner) == ("A", 100, "P1")
    assert ho.Order(" 2pd2040nt1n ", 1070, 2000, "", kg=100).grade == "A"   # 위치 인자 순서 유지 (app.py)
    assert ho.jsonable({"o": o, "n": pd.Series([1.5])[0], "x": float("nan")}) == {"o": {**vars(o)}, "n": 1.5, "x": None}


def test_rules_file():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "rules.json"
        assert ho.rule_for("P1", ho.load_rules(p)) == {**ho.DEFAULT_RULE}                     # 파일 없음 → 기본
        ho.set_rule("P1", p, width_plus=300, length_plus=500, items=[" 2pd2040nt2n "], grades=["a1"], note="엠보 무관")
        r = ho.rule_for("P1", ho.load_rules(p))
        assert (r["width_plus"], r["length_plus"], r["items"], r["grades"], r["note"]) == (300, 500, ["2PD2040NT2N"], ["A1"], "엠보 무관")
        assert (ho.rule_for("P2", ho.load_rules(p))["width_plus"], ho.rule_for("P2", ho.load_rules(p))["length_plus"]) == (200, 20)   # 다른 거래처는 기본
        ho.set_rule("P1", p, note="폭만")                                                      # 부분 갱신, 나머지 유지
        assert ho.rule_for("P1", ho.load_rules(p))["width_plus"] == 300
        assert "updated" in json.loads(p.read_text())["P1"]
        try:
            ho.set_rule("P1", p, thickness=1)
        except ValueError:
            pass
        else:
            raise AssertionError("알 수 없는 기준은 거부해야 함")


@contextmanager
def fake_db():
    """조회 함수를 가짜로 바꿔 배분 흐름만 검증."""
    cols = ["item", "width", "length", "grade", "rolls", "kg"]
    stock = pd.DataFrame([("2PD2040NT1N", 1070, 2000, "A", 30, 2568.0),   # 동일규격 30, 미출하 6 → 가용 24
                          ("2PD2040NT1N", 1100, 2000, "A", 5, 440.0),     # 폭+30 → 기본 후보
                          ("2PD2040NT1N", 1250, 2000, "A", 9, 900.0),     # 폭+180 → 기본(+200) 후보
                          ("2PD2040NT1N", 1300, 2000, "A", 6, 624.0),     # 폭+230 → width_plus≥230 일 때만
                          ("2PD2040NT1N", 1070, 2150, "A", 2, 184.0),     # 길이+150 → length_plus≥150 일 때만 (기본 +20 밖)
                          ("2PD2040NT1N", 1070, 2300, "A", 7, 688.6),     # 길이+300 → length_plus≥300 일 때만
                          ("2PD2040NT1N", 1070, 2000, "A1", 4, 342.4),    # 등급대체 → grades 에 A1 있을 때만
                          ("2PD2040NT2N", 1070, 2000, "A", 3, 256.8),     # 품목대체 → items 에 있을 때만, 미출하 3 → 가용 0
                          ("2PD2040NT1N", 1100, 1000, "A", 9, 396.0)],    # 길이 짧음 → 항상 제외
                         columns=cols)
    so_cols = ["item", "width", "length", "grade", "NO_SO", "SEQ_SO", "DT_SO", "CD_PARTNER", "QT_SO", "QT_GI", "open_kg", "rolls"]
    so = pd.DataFrame([("2PD2040NT1N", 1070, 2000, "A", "SOZ1", 1, "20260901", "X", 856.0, 342.4, 513.6, 10),   # 10롤 중 6롤 미출하
                       ("2PD2040NT2N", 1070, 2000, "A", "SOZ2", 1, "20260902", "Y", 256.8, 0.0, 256.8, None)],  # 롤수 없음 → kg 환산 3롤
                      columns=so_cols)
    prq = pd.DataFrame(columns=["NO_PRQ", "DT_DLV", "QT_PRQ", "qt_wo", "QT_WORK"])
    fakes = dict(item_master=lambda i: dict(CD_ITEM=i, NM_ITEM="PP NATURAL", CLS_ITEM="003", gsm=40, color="NT", tp="N"),
                 year_start=lambda today: "20260000", onhand=lambda items, ys: stock[stock.item.isin(items)].copy(),
                 open_so=lambda items, s: so[so.item.isin(items)].copy(), open_prq=lambda i, s: prq)
    saved = {k: getattr(ho, k) for k in fakes}
    try:
        for k, f in fakes.items():
            setattr(ho, k, f)
        yield
    finally:
        for k, f in saved.items():
            setattr(ho, k, f)


def test_stock_and_similar_with_fake_db():
    with fake_db(), tempfile.TemporaryDirectory() as d:
        p = Path(d) / "rules.json"
        # 모듈1: 재고 수 = 현재고 30 − 미출하 6 = 가용 24. 입력 dict 의 다른 키는 무시, 등급 생략은 A
        s = ho.stock({**P, "buyer": "무시"}, today=TODAY)
        assert s == {"item": "2PD2040NT1N", "width": 1070, "length": 2000, "grade": "A", "rolls": 30, "kg": 2568.0, "open_rolls": 6, "avail_rolls": 24}
        assert ho.stock({**P, "grade": "A1"}, today=TODAY)["rolls"] == 4          # 등급은 다른 재고
        assert ho.stock({**P, "width": 999}, today=TODAY)["rolls"] == 0            # 없는 규격 → 0
        assert json.dumps(s)                                                        # 그대로 JSON 가능
        # 모듈2: 기본 기준(폭 +200 · 길이 +20) → 폭+30, 폭+180 두 개. 동일규격·길이 짧은 것·+200 밖은 제외
        sim = ho.similar_products(P, today=TODAY, rules_file=p)
        assert [(x["kind"], x["width"], x["avail_rolls"]) for x in sim] == [("폭+30", 1100, 5), ("폭+180", 1250, 9)]
        assert set(sim[0]) == {"item", "width", "length", "grade", "kind", "rolls", "kg", "open_rolls", "avail_rolls"}
        assert len(ho.similar_products(P, 1, today=TODAY, rules_file=p)) == 1     # n 제한
        # 임시 기준 rule= : 길이+150, 폭+230, 등급 A1 추가. 품목 NT2N 은 가용 0 이라 제외
        sim = ho.similar_products(P, rule={"width_plus": 300, "length_plus": 200, "items": ["2PD2040NT2N"], "grades": ["A1"]}, today=TODAY, rules_file=p)
        assert [x["kind"] for x in sim] == ["길이+150", "폭+30", "폭+180", "폭+230", "등급"]
        # 거래처 기준 partner= : 파일에 저장된 기준 적용
        ho.set_rule("P1", p, length_plus=300)
        assert [x["kind"] for x in ho.similar_products(P, partner="P1", today=TODAY, rules_file=p)] == ["길이+150", "길이+300", "폭+30", "폭+180"]
        assert json.dumps(sim)


def test_check_with_fake_db():
    with fake_db(), tempfile.TemporaryDirectory() as d:
        p = Path(d) / "rules.json"
        # 기본 기준(폭 +200 · 길이 +20): 재고 24 + 대체(폭+30 5, 폭+180 9 = 14) + 생산 10. 길이+150 은 +20 밖이라 제외
        r = ho.check({**P, "grade": "A", "rolls": 48, "partner": "P1"}, today=TODAY, rules_file=p)   # dict 입력
        assert (r["onhand_rolls"], r["open_rolls"], r["avail_rolls"]) == (30, 6, 24)
        assert (r["stock_rolls"], r["sub_rolls"], r["prod_rolls"]) == (24, 14, 10)
        assert r["decisions"] == ["재고출하", "대체검토", "생산의뢰"]
        assert list(r["subs"].kind) == ["폭+30", "폭+180"] and list(r["subs"].alloc) == [5, 9]
        assert "재고출하 24롤 (50%)" in ho.report(r) and "생산의뢰 10롤 (21%)" in ho.report(r)
        j = ho.jsonable(r)
        assert j["order"]["partner"] == "P1" and j["subs"][0]["alloc"] == 5 and json.dumps(j)
        # 거래처 기준 추가(폭 +300 · 길이 +200 · 품목 NT2N · 등급 A1): 길이+150 2, 폭+230 6 추가, 등급 2, 품목 0 → 생산 0
        ho.set_rule("P1", p, width_plus=300, length_plus=200, items=["2PD2040NT2N"], grades=["A1"], note="엠보 무관")
        r = ho.check(ho.Order("2PD2040NT1N", 1070, 2000, "A", rolls=48, partner="P1"), today=TODAY, rules_file=p)   # Order 입력
        assert list(r["subs"].kind) == ["길이+150", "폭+30", "폭+180", "폭+230", "등급", "품목"]   # 같은 폭(재단만) 먼저
        assert list(r["subs"].alloc) == [2, 5, 9, 6, 2, 0] and (r["sub_rolls"], r["prod_rolls"]) == (24, 0)
        assert r["decisions"] == ["재고출하", "대체검토"]
        assert "거래처 기준" in ho.report(r) and "엠보 무관" in ho.report(r)
        # 다른 거래처는 기본 기준 그대로
        r = ho.check({**P, "rolls": 48, "partner": "P2"}, today=TODAY, rules_file=p)
        assert (r["sub_rolls"], r["prod_rolls"]) == (14, 10) and r["rule_source"] == "기본"
        # 임시 기준(저장 안 함): 길이 +300 → 길이+300 7롤 추가, 파일은 그대로
        r = ho.check({**P, "rolls": 48}, today=TODAY, rules_file=p, override={"length_plus": 300, "items": None})
        assert r["rule_source"] == "임시" and list(r["subs"].kind) == ["길이+150", "길이+300", "폭+30", "폭+180"]
        assert list(r["subs"].alloc) == [2, 7, 5, 9] and (r["stock_rolls"], r["sub_rolls"], r["prod_rolls"]) == (24, 23, 1)
        assert "P2" not in json.loads(p.read_text()) and json.loads(p.read_text())["P1"]["width_plus"] == 300
        assert "임시 기준" in ho.report(r)
        r = ho.check({**P, "rolls": 20}, today=TODAY, rules_file=Path(d) / "none.json")
        assert r["decisions"] == ["재고출하"] and r["prod_rolls"] == 0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
