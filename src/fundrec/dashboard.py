"""P4 — веб-кокпіт ("морда A"): локальний сервер без залежностей.

Подає `web/index.html` на `/` і свіжочитаний `data/cases.json` на `/cases.json`.
Кокпіт сам тягне cases.json з того ж походження й рендерить через ECharts (CDN).

Запуск:
    python -m fundrec.dashboard                  # http://127.0.0.1:8770
    python -m fundrec.dashboard --port 9000
    python -m fundrec.dashboard --host 0.0.0.0   # доступ із LAN
"""
from __future__ import annotations

import argparse
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config

_WEB_DIR = config.ROOT / "web"
_INDEX_HTML = _WEB_DIR / "index.html"

_EMPTY_PAYLOAD = b'{"count": 0, "cases": [], "analytics": null}'


def _read_index() -> bytes:
    """Читає web/index.html (свіжо, щоб правки підхоплювались без рестарту)."""
    if _INDEX_HTML.exists():
        return _INDEX_HTML.read_text(encoding="utf-8").encode("utf-8")
    return (
        "<!doctype html><meta charset=utf-8><body style='background:#0a0c10;color:#ff6b6b;"
        "font-family:monospace;padding:40px'>web/index.html не знайдено.</body>"
    ).encode("utf-8")


def _read_cases_json(path: Path | str = config.CASES_JSON) -> bytes:
    """Читає cases.json свіжо на кожен запит; повертає порожній payload якщо файлу нема."""
    p = Path(path)
    if p.exists():
        return p.read_bytes()
    return _EMPTY_PAYLOAD


def make_handler(cases_json_path: Path | str = config.CASES_JSON):
    """Фабрика хендлера — дозволяє підмінити шлях до cases.json (тести)."""

    class _Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/" or path.startswith("/index"):
                self._send(200, _read_index(), "text/html; charset=utf-8")
            elif path == "/cases.json":
                self._send(200, _read_cases_json(cases_json_path),
                           "application/json; charset=utf-8")
            else:
                self._send(404, b"not found", "text/plain; charset=utf-8")

        def log_message(self, *a):  # тиша в консолі
            return

    return _Handler


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        rc = getattr(stream, "reconfigure", None)
        if rc is not None:
            rc(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="fundrec-dashboard")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--host", default="127.0.0.1",
                    help="0.0.0.0 — доступ із LAN")
    args = ap.parse_args(argv)

    handler = make_handler()
    srv = ThreadingHTTPServer((args.host, args.port), handler)
    exists = Path(config.CASES_JSON).exists()
    hint = "" if exists else "  (cases.json відсутній — запусти 'python -m fundrec.make_sample')"
    print(f"📊  Кокпіт фандрайзингу: http://{args.host}:{args.port}/{hint}")
    print("    Ctrl+C — стоп")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nспинено.")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
