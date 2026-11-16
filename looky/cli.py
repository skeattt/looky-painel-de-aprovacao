"""Linha de comando da Looky: é por aqui que o agente (ou você) conversa com o painel.

    python looky.py card add ID --title "Nome: frase" --detail "..." --from "Motion" [--kind option --option "A=..." ...]
    python looky.py card rm ID
    python looky.py queue                 # cliques na fila, para a rotina executar
    python looky.py done ID "resultado"   # marca o clique como executado e tira o cartão
    python looky.py stream set ID --name ... --area ... --state motion --now ... --next ...
    python looky.py wait add ID --area ... --item ...   |   wait rm ID
    python looky.py brief [--out brief.md]
    python looky.py seed demo/seed.json [--reset]

Tudo grava direto no banco; a página aberta mostra a mudança em até 2 segundos.
"""
import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta

from .store import Store

STATES = {"live": "No ar", "motion": "Em andamento", "waiting": "Esperando", "parked": "Parado"}
DESIGN_KINDS = {"motion", "option"}


def today():
    return date.today().isoformat()


def now():
    return datetime.now().replace(microsecond=0).isoformat()


def days_since(iso, ref=None):
    try:
        return ((ref or date.today()) - date.fromisoformat(iso[:10])).days
    except (TypeError, ValueError):
        return None


def ago(n):
    if n is None:
        return "data desconhecida"
    return "desde hoje" if n <= 0 else "há 1 dia" if n == 1 else "há %d dias" % n


# dados de demonstração ---------------------------------------------------
REL = re.compile(r"^@(-?\d+)$")


def resolve_dates(v):
    """"@-3" vira a data de 3 dias atrás, para a demonstração nunca envelhecer."""
    if isinstance(v, dict):
        return {k: resolve_dates(x) for k, x in v.items()}
    if isinstance(v, list):
        return [resolve_dates(x) for x in v]
    if isinstance(v, str) and REL.match(v):
        return (date.today() + timedelta(days=int(REL.match(v).group(1)))).isoformat()
    return v


def seed(store, path, reset=False):
    data = resolve_dates(json.load(open(path, encoding="utf-8")))
    if reset:
        for coll in data:
            for doc_id in store.list(coll):
                store.delete(coll, doc_id)
    n = 0
    for coll, docs in data.items():
        for doc_id, doc in docs.items():
            store.put(coll, doc_id, doc)
            n += 1
    return n


# leitura do estado ----------------------------------------------------------
def pending_cards(store):
    """Cartões ainda sem clique, ou com clique na fila."""
    decisions = store.list("decisions")
    out = []
    for cid, c in store.list("cards").items():
        if c.get("removed") or c.get("resolved"):
            continue
        out.append((cid, c, decisions.get(cid)))
    return sorted(out, key=lambda x: x[1].get("when", ""))


def queued(store):
    cards = store.list("cards")
    return [(cid, d, cards.get(cid, {})) for cid, d in sorted(store.list("decisions").items())
            if d.get("status") == "queued"]


def describe(d):
    s = {"approve": "aprovado", "pass": "passou", "notes": "só nota"}.get(d.get("decision"), d.get("decision", "?"))
    if d.get("option"):
        s += " (opção %s)" % d["option"]
    if d.get("note"):
        s += ' com a nota "%s"' % d["note"]
    return s


def brief(store):
    page = store.get("meta", "page") or {}
    lines = ["# %s: resumo para o agente (%s)" % (page.get("name", "Looky"), today()), "",
             "Trabalhe a partir deste resumo. Busque conversas antigas só para um fato específico que falte.", "",
             "## Regras",
             "- Precisa de um sim do produtor? Crie um cartão: `python looky.py card add <id> --title \"Nome: frase\" --detail \"...\" --from \"<este chat>\"`. Não pergunte só no texto.",
             "- Escolha entre direções: `--kind option --option \"A=...\" --option \"B=...\"`. Prévia: `--image <url ou caminho em page/media>`.",
             "- Antes de qualquer outra coisa, execute os cliques da seção abaixo e marque cada um com `python looky.py done <id> \"resultado em uma linha\"`.",
             ""]
    q = queued(store)
    lines.append("## Decidido na Looky, falta executar")
    lines += ["- %s: %s, %s" % (cid, c.get("title", cid), describe(d)) for cid, d, c in q] or ["- nada"]
    lines += ["", "## Esperando o produtor responder"]
    lines += ["- %s: %s" % (c.get("title", cid), (c.get("detail") or "")[:110]) for cid, c, d in pending_cards(store) if not d] or ["- nada"]
    w = sorted(store.list("waiting").values(), key=lambda x: x.get("since", ""))
    lines += ["", "## Esperando o produtor fazer"]
    lines += ["- [%s] %s (%s)" % (x.get("area", ""), x.get("item", ""), ago(days_since(x.get("since")))) for x in w if not x.get("removed")] or ["- nada"]
    streams = store.list("streams")
    for area in sorted({s.get("area", "Outros") for s in streams.values()}):
        lines += ["", "## " + area]
        for s in sorted((s for s in streams.values() if s.get("area", "Outros") == area), key=lambda s: s.get("name", "")):
            lines.append("- %s [%s, mexido em %s]: %s Próximo: %s" % (
                s.get("name"), STATES.get(s.get("state"), s.get("state")), s.get("touched", "?"), s.get("now", ""), s.get("next", "")))
    return "\n".join(lines) + "\n"


# comandos -------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(prog="looky.py", description="Linha de comando da Looky")
    ap.add_argument("--db", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)

    card = sub.add_parser("card").add_subparsers(dest="action", required=True)
    ca = card.add_parser("add")
    ca.add_argument("id")
    ca.add_argument("--title", required=True)
    ca.add_argument("--detail", default="")
    ca.add_argument("--from", dest="origin", default="")
    ca.add_argument("--kind", default="content", choices=["content", "option", "motion"])
    ca.add_argument("--image", default="")
    ca.add_argument("--option", action="append", default=[], help='"A=rótulo"; repita para cada opção')
    ca.add_argument("--ref", default="", help="o que fazer quando aprovado, em uma linha")
    card.add_parser("rm").add_argument("id")

    sub.add_parser("queue").add_argument("--json", action="store_true")
    dn = sub.add_parser("done")
    dn.add_argument("id")
    dn.add_argument("result")

    st = sub.add_parser("stream").add_subparsers(dest="action", required=True)
    ss = st.add_parser("set")
    ss.add_argument("id")
    for f in ("name", "area", "owner", "now", "next"):
        ss.add_argument("--" + f)
    ss.add_argument("--state", choices=list(STATES))

    wt = sub.add_parser("wait").add_subparsers(dest="action", required=True)
    wa = wt.add_parser("add")
    wa.add_argument("id")
    wa.add_argument("--area", required=True)
    wa.add_argument("--item", required=True)
    wt.add_parser("rm").add_argument("id")

    sub.add_parser("brief").add_argument("--out")
    sd = sub.add_parser("seed")
    sd.add_argument("file")
    sd.add_argument("--reset", action="store_true")

    a = ap.parse_args(argv)
    store = Store(a.db)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    if a.cmd == "card" and a.action == "add":
        options = []
        for o in a.option:
            key, _, label = o.partition("=")
            options.append({"key": key.strip(), "label": label.strip()})
        if options and a.kind == "content":
            a.kind = "option"
        doc = {"kind": a.kind, "title": a.title, "detail": a.detail, "from": a.origin, "when": today()}
        doc.update({k: v for k, v in (("image", a.image), ("options", options), ("ref", a.ref)) if v})
        store.put("cards", a.id, doc)
        # um cartão recriado com o mesmo id volta a pedir decisão
        old = store.get("decisions", a.id)
        if old and old.get("status") == "done":
            store.delete("decisions", a.id)
        print("cartão", a.id)
    elif a.cmd == "card" and a.action == "rm":
        store.patch("cards", a.id, {"removed": True})
        print("removido", a.id)
    elif a.cmd == "queue":
        q = queued(store)
        if a.json:
            print(json.dumps([dict(d, id=cid, card=c) for cid, d, c in q], ensure_ascii=False, indent=1))
        else:
            for cid, d, c in q:
                print("%s\t%s\t%s%s" % (cid, c.get("title", ""), describe(d), ("\n\tref: " + c["ref"]) if c.get("ref") else ""))
            print("%d na fila" % len(q))
    elif a.cmd == "done":
        d = store.get("decisions", a.id)
        if not d:
            sys.exit("sem clique para %s" % a.id)
        store.patch("decisions", a.id, {"status": "done", "result": a.result, "done_at": now()})
        if d.get("decision") != "notes":
            store.patch("cards", a.id, {"resolved": True})
        print("feito", a.id)
    elif a.cmd == "stream":
        fields = {k: getattr(a, k) for k in ("name", "area", "owner", "now", "next", "state") if getattr(a, k)}
        store.patch("streams", a.id, dict(fields, touched=today()))
        print("frente", a.id)
    elif a.cmd == "wait" and a.action == "add":
        store.put("waiting", a.id, {"area": a.area, "item": a.item, "since": today()})
        print("esperando", a.id)
    elif a.cmd == "wait" and a.action == "rm":
        store.patch("waiting", a.id, {"removed": True})
        print("removido", a.id)
    elif a.cmd == "brief":
        text = brief(store)
        if a.out:
            open(a.out, "w", encoding="utf-8").write(text)
            print(os.path.abspath(a.out))
        else:
            print(text)
    elif a.cmd == "seed":
        print("%d documentos" % seed(store, a.file, a.reset))
