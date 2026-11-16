"""Banco da Looky: documentos JSON por coleção num arquivo SQLite, com número de revisão.

Toda escrita ganha uma revisão nova (crescente no arquivo inteiro). A página pede
"o que mudou desde a revisão N" e recebe só os documentos alterados, inclusive os apagados
(que ficam como lápide, com data NULL). O servidor e a CLI abrem o mesmo arquivo, então um
cartão criado pelo agente na linha de comando aparece na página aberta em segundos.

Só biblioteca padrão.
"""
import json
import os
import re
import sqlite3
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.environ.get("LOOKY_DB") or os.path.join(ROOT, "looky.db")
NAME = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    coll TEXT NOT NULL,
    id   TEXT NOT NULL,
    data TEXT,               -- NULL = apagado (lápide para o feed de mudanças)
    rev  INTEGER NOT NULL,
    PRIMARY KEY (coll, id)
);
CREATE INDEX IF NOT EXISTS docs_rev ON docs (rev);
"""


def valid(name):
    return bool(name and NAME.match(name))


class Store:
    def __init__(self, path=None):
        self.path = path or DEFAULT_DB
        self.db = sqlite3.connect(self.path, timeout=15, isolation_level=None, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.lock = threading.Lock()

    # leitura -----------------------------------------------------------
    def get(self, coll, doc_id):
        with self.lock:
            row = self.db.execute("SELECT data FROM docs WHERE coll=? AND id=?", (coll, doc_id)).fetchone()
        return json.loads(row[0]) if row and row[0] is not None else None

    def list(self, coll):
        with self.lock:
            rows = self.db.execute("SELECT id, data FROM docs WHERE coll=? AND data IS NOT NULL ORDER BY id", (coll,)).fetchall()
        return {i: json.loads(d) for i, d in rows}

    def changes(self, since=0):
        """(revisão atual, [{coll, id, rev, data|None}]) com tudo que mudou depois de `since`."""
        with self.lock:
            rows = self.db.execute("SELECT coll, id, data, rev FROM docs WHERE rev > ? ORDER BY rev", (since,)).fetchall()
            rev = self.db.execute("SELECT COALESCE(MAX(rev), 0) FROM docs").fetchone()[0]
        return rev, [{"coll": c, "id": i, "rev": r, "data": json.loads(d) if d is not None else None} for c, i, d, r in rows]

    # escrita -----------------------------------------------------------
    def _write(self, coll, doc_id, fn):
        if not (valid(coll) and valid(doc_id)):
            raise ValueError("nome inválido: %s/%s" % (coll, doc_id))
        with self.lock:
            cur = self.db.cursor()
            cur.execute("BEGIN IMMEDIATE")  # trava o arquivo: a revisão é única mesmo com a CLI escrevendo junto
            try:
                row = cur.execute("SELECT data FROM docs WHERE coll=? AND id=?", (coll, doc_id)).fetchone()
                old = json.loads(row[0]) if row and row[0] is not None else None
                new = fn(old)
                rev = cur.execute("SELECT COALESCE(MAX(rev), 0) + 1 FROM docs").fetchone()[0]
                cur.execute("INSERT OR REPLACE INTO docs (coll, id, data, rev) VALUES (?, ?, ?, ?)",
                            (coll, doc_id, None if new is None else json.dumps(new, ensure_ascii=False), rev))
                cur.execute("COMMIT")
            except BaseException:
                cur.execute("ROLLBACK")
                raise
        return new

    def put(self, coll, doc_id, data):
        return self._write(coll, doc_id, lambda old: dict(data))

    def patch(self, coll, doc_id, data):
        return self._write(coll, doc_id, lambda old: dict(old or {}, **data))

    def delete(self, coll, doc_id):
        return self._write(coll, doc_id, lambda old: None)

    def close(self):
        self.db.close()
