#!/usr/bin/env python
"""Servidor local da Looky. Só biblioteca padrão.

    python server.py                  # http://localhost:8780
    python server.py --demo           # carrega os dados de demonstração se o banco estiver vazio
    python server.py --port 9000 --db outro.db

API (JSON):
    GET    /api/changes?since=N        tudo que mudou depois da revisão N (a página consulta a cada 2 s)
    GET    /api/<coleção>              documentos da coleção
    GET    /api/<coleção>/<id>
    PUT    /api/<coleção>/<id>         substitui
    PATCH  /api/<coleção>/<id>         mescla campos
    DELETE /api/<coleção>/<id>

Escuta só em 127.0.0.1. A página só escreve na coleção "decisions"; o resto vem do agente pela CLI.
"""
import argparse
import json
import mimetypes
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from looky import embed  # noqa: E402
from looky.store import Store, valid  # noqa: E402

PAGE = os.path.join(HERE, "page")
MAX_BODY = 1 << 20
WRITABLE_FROM_PAGE = {"decisions"}


class Handler(BaseHTTPRequestHandler):
    store = None
    server_version = "Looky/1.0"

    def log_message(self, fmt, *args):
        if "--verbose" in sys.argv:
            super().log_message(fmt, *args)

    # respostas ----------------------------------------------------------
    def send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, body, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def route(self):
        """(coleção, id) para /api/..., ou None para arquivo estático."""
        parts = [unquote(p) for p in urlparse(self.path).path.split("/") if p]
        if not parts or parts[0] != "api":
            return None
        coll = parts[1] if len(parts) > 1 else ""
        doc_id = parts[2] if len(parts) > 2 else None
        if len(parts) > 3 or not valid(coll) or (doc_id is not None and not valid(doc_id)):
            return False
        return coll, doc_id

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("corpo grande demais")
        data = json.loads(self.rfile.read(n) or b"{}")
        if not isinstance(data, dict):
            raise ValueError("o corpo precisa ser um objeto JSON")
        return data

    # páginas ------------------------------------------------------------
    def serve_static(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            html = open(os.path.join(PAGE, "index.html"), encoding="utf-8").read()
            buttons, panels, scripts = embed.build(os.path.join(PAGE, "embeds"))
            html = (html.replace("<!--EMBED-TABS-->", buttons)
                        .replace("<!--EMBED-PANELS-->", panels)
                        .replace("<!--EMBED-SCRIPTS-->", scripts))
            return self.send_bytes(html.encode("utf-8"), "text/html; charset=utf-8")
        full = os.path.normpath(os.path.join(PAGE, unquote(path).lstrip("/")))
        if not full.startswith(PAGE + os.sep) or not os.path.isfile(full):
            return self.send_json(404, {"error": "não encontrado"})
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as f:
            return self.send_bytes(f.read(), ctype)

    # verbos -------------------------------------------------------------
    def do_GET(self):
        r = self.route()
        if r is None:
            return self.serve_static()
        if r is False:
            return self.send_json(404, {"error": "não encontrado"})
        coll, doc_id = r
        if coll == "changes" and doc_id is None:
            since = int((parse_qs(urlparse(self.path).query).get("since") or ["0"])[0] or 0)
            rev, docs = self.store.changes(since)
            return self.send_json(200, {"rev": rev, "docs": docs})
        if doc_id:
            doc = self.store.get(coll, doc_id)
            return self.send_json(200, doc) if doc is not None else self.send_json(404, {})
        return self.send_json(200, self.store.list(coll))

    def write(self, method):
        r = self.route()
        if not r or not r[1]:
            return self.send_json(404, {"error": "não encontrado"})
        coll, doc_id = r
        if coll not in WRITABLE_FROM_PAGE:
            return self.send_json(403, {"error": "a página só grava decisões"})
        try:
            if method == "DELETE":
                self.store.delete(coll, doc_id)
                return self.send_json(200, {"id": doc_id})
            data = self.body()
            doc = self.store.put(coll, doc_id, data) if method == "PUT" else self.store.patch(coll, doc_id, data)
            return self.send_json(200, dict(doc, id=doc_id))
        except ValueError as e:
            return self.send_json(400, {"error": str(e)})

    def do_PUT(self):
        self.write("PUT")

    def do_PATCH(self):
        self.write("PATCH")

    def do_DELETE(self):
        self.write("DELETE")


def main():
    ap = argparse.ArgumentParser(description="Servidor local da Looky")
    ap.add_argument("--port", type=int, default=8780)
    ap.add_argument("--db", default=None, help="arquivo SQLite (padrão: looky.db na raiz)")
    ap.add_argument("--demo", action="store_true", help="carrega demo/seed.json se o banco estiver vazio")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    store = Store(a.db)
    if a.demo and store.changes(0)[0] == 0:
        from looky.cli import seed
        print("banco vazio: carregando a demonstração (%d documentos)" % seed(store, os.path.join(HERE, "demo", "seed.json")))
    Handler.store = store
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print("Looky em http://localhost:%d/  (banco: %s)  Ctrl+C para parar" % (a.port, store.path))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
