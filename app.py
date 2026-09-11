"""order_check 의 로컬 웹앱 — 이 맥에서만 (127.0.0.1). 표준 라이브러리 http.server, 의존성 추가 없음.

    ../DB조회도구/.venv/bin/python app.py        →  http://127.0.0.1:8765

API (JSON):  GET /api/check?item&width&length&grade&rolls|kg&partner[&temp=1&width_plus&items&grades&note]   GET /api/items?q=   GET /api/partners?q=   GET|POST /api/rules
"""
from __future__ import annotations

import json
import math
import traceback
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

import order_check as oc

HERE = Path(__file__).resolve().parent
HOST, PORT = "127.0.0.1", 8765


def jsonable(v):
    if isinstance(v, pd.DataFrame):
        return [jsonable(r) for r in v.to_dict("records")]
    if isinstance(v, oc.Order):
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
    if src.get("width_plus") not in (None, ""):
        fields["width_plus"] = int(src["width_plus"])
        if fields["width_plus"] < 0:
            raise ValueError("폭 허용(width_plus)은 0 이상이어야 합니다.")
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
            self._send(404, {"error": "not found"})
        except (ValueError, KeyError) as e:
            self._send(400, {"error": str(e) or "입력값을 확인하세요."})
        except Exception as e:
            traceback.print_exc()
            self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def do_POST(self):
        if urlparse(self.path).path != "/api/rules":
            return self._send(404, {"error": "not found"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
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
        print(self.address_string(), fmt % args)


if __name__ == "__main__":
    print(f"http://{HOST}:{PORT}  (Ctrl+C 로 종료)")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
