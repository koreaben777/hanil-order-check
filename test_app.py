"""DB 없이 도는 웹앱 자가 점검(/api/optimize 의 함수 부분):  ../DB조회도구/.venv/bin/python test_app.py"""
import app


def test_optimize_cart():
    cart = [dict(order_id="C1", item="2TESTWH1N", width=1030, length=1000, rolls=18, gsm=40, grade="A"),
            dict(order_id="C2", item="2TESTWH1N", width=530, length=1000, rolls=18, gsm=40, grade="A"),
            dict(order_id="C3", item="2TESTBK1N", width=1600, length=500, rolls=4, gsm=60, grade="A")]
    r = app.optimize({"requests": cart, "time_limit": 10, "t0": "2026-01-01T00:00:00",
                      "machine_state": {"color_code": "WH1N", "gsm": 40, "agri": False}})
    plan, sched = r["plan"], r["schedule"]
    assert plan["complete"] and sum(g["sets_used"] for g in plan["groups"] if g["item"] == "2TESTWH1N") == 9
    assert sched["complete"] and len(sched["jobs"]) == sum(len(g["sets"]) for g in plan["groups"])
    assert [j["color_code"] for j in sched["jobs"]][:1] == ["WH1N"]          # 연한색(설비 상태 WH1N) 먼저
    assert sched["jobs"][0]["start"] >= "2026-01-01T00:00:00"
    for bad in ({}, {"requests": []}, {"requests": cart, "time_limit": 0}, {"requests": cart, "time_limit": "x"}):
        try:
            app.optimize(bad)
        except ValueError:
            continue
        raise AssertionError(f"ValueError 필요: {bad}")
    print("  optimize: WH1N 9세트 + BK1N, 순서 WH→BK, 잘못된 입력 거부")


def test_examples():
    ex = app.examples()
    assert len(ex) == 5 and [e["id"] for e in ex] == [f"ex{i}" for i in range(1, 6)]
    for e in ex:
        assert e["name"] and e["rows"] and all(set(r) >= {"item", "width", "length", "rolls", "gsm", "grade"} for r in e["rows"])
        assert not any(k in r for r in e["rows"] for k in ("partner", "partner_name", "use", "due", "note"))   # 공개 저장소: 거래처 없음
    small = min(ex, key=lambda e: len(e["rows"]))
    r = app.hp.plan([dict(row, order_id=f"E{i}") for i, row in enumerate(small["rows"], 1)], time_limit=10)
    assert r["complete"]
    print(f"  examples: 5개, 최소 예시 {small['id']} {len(small['rows'])}행 1단 완료")


if __name__ == "__main__":
    test_optimize_cart()
    print("ok test_optimize_cart")
    test_examples()
    print("ok test_examples")
