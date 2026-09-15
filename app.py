"""hanilsf_optimizer 의 로컬 웹앱 — 이 맥에서만 (127.0.0.1). 표준 라이브러리 http.server, 의존성 추가 없음.

    ../DB조회도구/.venv/bin/python app.py        →  http://127.0.0.1:8765

API (JSON):  GET /api/check?item&width&length&grade&rolls|kg&partner[&temp=1&width_plus&length_plus&items&grades&note]   GET /api/items?q=   GET /api/partners?q=   GET|POST /api/rules
             POST /api/optimize {requests:[{item,width,length,grade,rolls,gsm,partner,order_id}], t0, machine_state:{color_code,gsm,agri}, time_limit}  → {plan, schedule}  (장바구니 생산분 → 세트 계획 → 순서)
             GET /api/examples  → cart_examples.json (② 탭 예시 생산 집합 5개)
"""
from __future__ import annotations

import json
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd

import hanilsf_optimizer as oc
from hanilsf_optimizer import jsonable
import hanilsf_plan as hp
import hanilsf_schedule as hs

HERE = Path(__file__).resolve().parent
HOST, PORT = "127.0.0.1", 8765


def search_items(q: str) -> pd.DataFrame:
    q = q.strip().upper()
    return oc.db.query("""
        SELECT TOP 20 CD_ITEM, NM_ITEM, NUM_USERDEF1 AS gsm, CD_USERDEF2 AS color, CD_USERDEF3 AS tp
        FROM NEOE.MA_PITEM
        WHERE CD_COMPANY=:c AND CD_PLANT=:p AND CLS_ITEM='003' AND LEFT(CD_ITEM,1) IN ('1','2')
          AND (CD_ITEM LIKE :pre OR NM_ITEM LIKE :any)
        ORDER BY CD_ITEM""", c=oc.COMPANY, p=oc.PLANT, pre=q + "%", any="%" + q + "%")


def search_partners(q: str) -> pd.DataFrame:
    q = q.strip()
    return oc.db.query("""
        SELECT TOP 20 CD_PARTNER, LN_PARTNER FROM NEOE.MA_PARTNER
        WHERE CD_COMPANY=:c AND (CD_PARTNER LIKE :pre OR LN_PARTNER LIKE :any)
        ORDER BY LN_PARTNER""", c=oc.COMPANY, pre=q + "%", any="%" + q + "%")


def _list(v) -> list[str]:
    if isinstance(v, str):
        v = v.split(",")
    return [str(x).strip() for x in (v or []) if str(x).strip()]


def parse_rule_fields(src: dict) -> dict:
    """폼/쿼리에서 온 대체 기준을 검증해 {width_plus, items, grades, note} 로 만든다."""
    fields = {}
    for key, label in (("width_plus", "폭 허용(width_plus)"), ("length_plus", "길이 허용(length_plus)")):
        if src.get(key) not in (None, ""):
            fields[key] = int(src[key])
            if fields[key] < 0:
                raise ValueError(f"{label}은 0 이상이어야 합니다.")
    if "items" in src:
        fields["items"] = [i.upper() for i in _list(src["items"])]
    if "grades" in src:
        fields["grades"] = [g.upper() for g in _list(src["grades"])]
        bad = set(fields["grades"]) - set(oc.GRADES)
        if bad:
            raise ValueError(f"등급 {sorted(bad)} 은 허용 목록 {oc.GRADES} 에 없습니다.")
    if "note" in src:
        fields["note"] = str(src["note"]).strip()
    return fields


def examples() -> list:
    """② 생산 정의 탭의 예시 생산 집합(cart_examples.json). 규격만 있고 거래처·납기는 없다."""
    path = HERE / "cart_examples.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    for e in data:
        for r in e["rows"]:
            for k in ("item", "width", "length", "rolls", "gsm"):
                if k not in r:
                    raise ValueError(f"예시 {e.get('id')} 행에 {k} 가 없습니다.")
    return data


def optimize(body: dict) -> dict:
    """장바구니 생산분(요청 dict 목록) → 1단 plan() → 2단 schedule(). ERP 를 읽지 않는다.
    plan 이 미해결이면 schedule 은 None. 계수는 추정값(결과 warnings 참고)."""
    from datetime import date, datetime, time, timedelta
    requests = body.get("requests")
    if not isinstance(requests, list) or not requests:
        raise ValueError("장바구니가 비어 있습니다. 주문 판단 탭에서 생산의뢰분을 담으세요.")
    raw = body.get("time_limit")
    try:
        limit = float(120 if raw in (None, "") else raw)
    except (TypeError, ValueError):
        raise ValueError("시간 제한은 숫자여야 합니다.") from None
    if not 0 < limit <= 600:
        raise ValueError("시간 제한은 0 초과 600 이하여야 합니다.")
    state = body.get("machine_state") or {}
    machine_state = dict(color_code=str(state.get("color_code") or "WH1N").strip().upper(),
                         gsm=float(state.get("gsm") or 40), agri=bool(state.get("agri", False)))
    t0 = body.get("t0") or datetime.combine(date.today() + timedelta(days=1), time()).isoformat()
    plan_result = hp.plan(requests, time_limit=limit)
    schedule = hs.schedule(plan_result, t0=t0, machine_state=machine_state, time_limit=limit) if plan_result["complete"] else None
    return {"plan": plan_result, "schedule": schedule}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/":
                return self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
            if u.path == "/api/check":
                o = oc.Order(q["item"], int(q["width"]), int(q["length"]), q.get("grade") or "A",
                             int(q["rolls"]) if q.get("rolls") else None, float(q["kg"]) if q.get("kg") else None,
                             q.get("partner", "").strip() or None)
                override = parse_rule_fields(q) if q.get("temp") == "1" else None   # 이 주문에만 쓰는 임시 기준
                return self._send(200, jsonable(oc.check(o, override=override)))
            if u.path == "/api/items":
                return self._send(200, jsonable(search_items(q.get("q", ""))) if q.get("q") else [])
            if u.path == "/api/partners":
                return self._send(200, jsonable(search_partners(q.get("q", ""))) if q.get("q") else [])
            if u.path == "/api/rules":
                return self._send(200, oc.load_rules())
            if u.path == "/api/examples":
                return self._send(200, examples())
            self._send(404, {"error": "not found"})
        except (ValueError, KeyError) as e:
            self._send(400, {"error": str(e) or "입력값을 확인하세요."})
        except Exception as e:
            traceback.print_exc()
            self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ("/api/rules", "/api/optimize"):
            return self._send(404, {"error": "not found"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
            if path == "/api/optimize":
                return self._send(200, jsonable(optimize(body)))
            partner = str(body.get("partner", "")).strip()
            if not partner:
                raise ValueError("거래처코드가 필요합니다.")
            self._send(200, oc.set_rule(partner, **parse_rule_fields(body)))
        except (ValueError, KeyError, TypeError) as e:
            self._send(400, {"error": str(e)})
        except Exception as e:
            traceback.print_exc()
            self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def log_message(self, fmt, *args):  # 조용히: 경로만
        print(self.address_string(), fmt % args, flush=True)


if __name__ == "__main__":
    print(f"http://{HOST}:{PORT}  (Ctrl+C 로 종료)", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
