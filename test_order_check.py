"""DB 없이 도는 자가 점검:  ../DB조회도구/.venv/bin/python test_order_check.py"""
import json
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd

import order_check as oc


def test_roll_kg():
    assert abs(oc.roll_kg(1070, 2000, 40) - 85.6) < 1e-9          # 절차서 §3 예시
    assert abs(oc.roll_kg(1070, 2000, 40) * 48 - 4108.8) < 1e-9


def test_allocate():
    assert oc.allocate(48, 54, []) == (48, [], 0)                              # 전량 재고
    assert oc.allocate(48, 6, []) == (6, [], 42)                               # 재고 + 생산
    assert oc.allocate(12, 0, [("a", 5), ("b", 20)]) == (0, [("a", 5), ("b", 7)], 0)   # 대체만, 순서대로
    assert oc.allocate(48, 24, [("a", 5), ("b", 0)]) == (24, [("a", 5)], 19)  # 50% 재고 · 10% 대체 · 40% 생산
    assert oc.allocate(10, -3, [("a", -1)]) == (0, [], 10)                     # 음수 가용은 0 취급


def test_order_validation():
    for bad in (dict(item="3PD2040NT1N", width=1, length=1, rolls=1),   # 3호기 범위 밖
                dict(item="2PD2040NT1N", width=0, length=1, rolls=1),
                dict(item="2PD2040NT1N", width=1, length=1, grade="Z", rolls=1),
                dict(item="2PD2040NT1N", width=1, length=1)):           # 롤수·kg 둘 다 없음
        try:
            oc.Order(**bad)
        except ValueError:
            continue
        raise AssertionError(bad)
    assert oc.Order(" 2pd2040nt1n ", 1070, 2000, "", kg=100).grade == "A"


def test_rules_file():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "rules.json"
        assert oc.rule_for("P1", oc.load_rules(p)) == {**oc.DEFAULT_RULE}                     # 파일 없음 → 기본
        oc.set_rule("P1", p, width_plus=300, length_plus=500, items=[" 2pd2040nt2n "], grades=["a1"], note="엠보 무관")
        r = oc.rule_for("P1", oc.load_rules(p))
        assert (r["width_plus"], r["length_plus"], r["items"], r["grades"], r["note"]) == (300, 500, ["2PD2040NT2N"], ["A1"], "엠보 무관")
        assert (oc.rule_for("P2", oc.load_rules(p))["width_plus"], oc.rule_for("P2", oc.load_rules(p))["length_plus"]) == (200, 200)   # 다른 거래처는 기본
        oc.set_rule("P1", p, note="폭만")                                                      # 부분 갱신, 나머지 유지
        assert oc.rule_for("P1", oc.load_rules(p))["width_plus"] == 300
        assert "updated" in json.loads(p.read_text())["P1"]
        try:
            oc.set_rule("P1", p, thickness=1)
        except ValueError:
            pass
        else:
            raise AssertionError("알 수 없는 기준은 거부해야 함")


def test_check_with_fake_db():
    """조회 함수를 가짜로 바꿔 배분 흐름만 검증."""
    cols = ["item", "width", "length", "grade", "rolls", "kg"]
    stock = pd.DataFrame([("2PD2040NT1N", 1070, 2000, "A", 30, 2568.0),   # 동일규격 30, 미출하 6 → 가용 24
                          ("2PD2040NT1N", 1100, 2000, "A", 5, 440.0),     # 폭+30 → 기본 후보
                          ("2PD2040NT1N", 1250, 2000, "A", 9, 900.0),     # 폭+180 → 기본(+200) 후보
                          ("2PD2040NT1N", 1300, 2000, "A", 6, 624.0),     # 폭+230 → width_plus≥230 일 때만
                          ("2PD2040NT1N", 1070, 2150, "A", 2, 184.0),     # 길이+150 → 기본(+200) 후보
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
                 year_start=lambda today: "20260000", onhand=lambda items, ys: stock.copy(),
                 open_so=lambda items, s: so.copy(), open_prq=lambda i, s: prq)
    saved = {k: getattr(oc, k) for k in fakes}
    try:
        for k, f in fakes.items():
            setattr(oc, k, f)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "rules.json"
            # 기본 기준(폭 +200 · 길이 +200): 재고 24 + 대체(길이+150 2, 폭+30 5, 폭+180 9 = 16) + 생산 8
            r = oc.check(oc.Order("2PD2040NT1N", 1070, 2000, "A", rolls=48, partner="P1"), today=date(2026, 9, 10), rules_file=p)
            assert (r["onhand_rolls"], r["open_rolls"], r["avail_rolls"]) == (30, 6, 24)
            assert (r["stock_rolls"], r["sub_rolls"], r["prod_rolls"]) == (24, 16, 8)
            assert r["decisions"] == ["재고출하", "대체검토", "생산의뢰"]
            assert list(r["subs"].kind) == ["길이+150", "폭+30", "폭+180"] and list(r["subs"].alloc) == [2, 5, 9]   # 같은 폭(재단만) 먼저
            assert "재고출하 24롤 (50%)" in oc.report(r) and "생산의뢰 8롤 (17%)" in oc.report(r)
            # 거래처 기준 추가(폭 +300 · 품목 NT2N · 등급 A1): 폭+230 6 추가, 등급 4, 품목 0(미출하) → 생산 0 (24+2+5+9+6+4=50≥48)
            oc.set_rule("P1", p, width_plus=300, items=["2PD2040NT2N"], grades=["A1"], note="엠보 무관")
            r = oc.check(oc.Order("2PD2040NT1N", 1070, 2000, "A", rolls=48, partner="P1"), today=date(2026, 9, 10), rules_file=p)
            assert list(r["subs"].kind) == ["길이+150", "폭+30", "폭+180", "폭+230", "등급", "품목"]
            assert list(r["subs"].alloc) == [2, 5, 9, 6, 2, 0] and (r["sub_rolls"], r["prod_rolls"]) == (24, 0)
            assert r["decisions"] == ["재고출하", "대체검토"]
            assert "거래처 기준" in oc.report(r) and "엠보 무관" in oc.report(r)
            # 다른 거래처는 기본 기준 그대로
            r = oc.check(oc.Order("2PD2040NT1N", 1070, 2000, "A", rolls=48, partner="P2"), today=date(2026, 9, 10), rules_file=p)
            assert (r["sub_rolls"], r["prod_rolls"]) == (16, 8) and r["rule_source"] == "기본"
            # 임시 기준(저장 안 함): 길이 +300 → 길이+300 7롤 추가, 파일은 그대로
            r = oc.check(oc.Order("2PD2040NT1N", 1070, 2000, "A", rolls=48), today=date(2026, 9, 10), rules_file=p,
                         override={"length_plus": 300, "items": None})
            assert r["rule_source"] == "임시" and list(r["subs"].kind) == ["길이+150", "길이+300", "폭+30", "폭+180"]
            assert list(r["subs"].alloc) == [2, 7, 5, 9] and (r["stock_rolls"], r["sub_rolls"], r["prod_rolls"]) == (24, 23, 1)
            assert "P2" not in json.loads(p.read_text()) and json.loads(p.read_text())["P1"]["width_plus"] == 300
            assert "임시 기준" in oc.report(r)
        r = oc.check(oc.Order("2PD2040NT1N", 1070, 2000, "A", rolls=20), today=date(2026, 9, 10), rules_file=Path(d) / "none.json")
        assert r["decisions"] == ["재고출하"] and r["prod_rolls"] == 0
    finally:
        for k, f in saved.items():
            setattr(oc, k, f)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
