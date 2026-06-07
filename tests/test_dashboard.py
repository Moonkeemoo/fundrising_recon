"""Тести веб-кокпіта: сервер віддає HTML на / і JSON на /cases.json."""
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from fundrec import dashboard


def _start_server(tmp_path, payload):
    cases_json = tmp_path / "cases.json"
    cases_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    handler = dashboard.make_handler(cases_json)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, t, port


def _get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read()


def test_index_returns_html(tmp_path):
    srv, t, port = _start_server(tmp_path, {"count": 0, "cases": []})
    try:
        status, ctype, body = _get(port, "/")
        assert status == 200
        assert "text/html" in ctype
        # маркер з index.html
        assert b"FUNDREC" in body
        assert b"echarts" in body
        assert b"cases.json" in body
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)


def test_cases_json_served(tmp_path):
    payload = {"count": 1, "cases": [{"id": "x", "goal": "military",
                                      "verification_status": "verified"}]}
    srv, t, port = _start_server(tmp_path, payload)
    try:
        status, ctype, body = _get(port, "/cases.json")
        assert status == 200
        assert "application/json" in ctype
        data = json.loads(body)
        assert data["count"] == 1
        assert data["cases"][0]["id"] == "x"
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)


def test_unknown_path_404(tmp_path):
    srv, t, port = _start_server(tmp_path, {"count": 0, "cases": []})
    try:
        try:
            _get(port, "/nope")
            raise AssertionError("очікували 404")
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)
