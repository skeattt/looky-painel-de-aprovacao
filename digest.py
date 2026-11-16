#!/usr/bin/env python
"""Resumo diário das sessões do Claude Code: o que foi pedido, o que mudou e o que ficou esperando você.

    python digest.py                     # ontem
    python digest.py 2026-11-15
    python digest.py --dir demo/sessoes  # outra pasta de transcrições (a demonstração usa esta)

Lê só os .jsonl locais de ~/.claude/projects (nada sai da máquina) e grava digests/AAAA-MM-DD.md.
A rotina da manhã lê este resumo em vez das transcrições inteiras: é o que deixa a rodada barata.
"""
import argparse
import glob
import json
import os
import re
import sys
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DIR = os.path.join(os.path.expanduser("~"), ".claude", "projects")
EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

# sinais simples, em português: frases do usuário que fecham algo e respostas que terminam pedindo algo
DECIDED = re.compile(r"\b(pode (fazer|seguir|mandar)|aprov|fechado|combinado|vamos de|escolh|prefiro|quero que|não quero|ficou assim|decid)", re.I)
ASKING = re.compile(r"(\?\s*$|quer que eu|posso |confirma|qual (você )?prefere|me diz|aguardo|depende de você)", re.I | re.M)
NOISE = ("<", "[Image", "Base directory for this skill", "Caveat:")


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(x.get("text", "") for x in content if isinstance(x, dict) and x.get("type") == "text")
    return ""


def short(s, n):
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def local_time(ts):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
    except (AttributeError, ValueError):
        return None


def read_sessions(folder, day):
    start = datetime.combine(day, datetime.min.time()).timestamp()
    sessions = {}
    for path in glob.glob(os.path.join(folder, "*", "*.jsonl")):
        if os.path.getmtime(path) < start:
            continue  # não foi tocado desde o começo do dia: não tem nada dele
        sid = os.path.splitext(os.path.basename(path))[0]
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("isSidechain"):
                    continue  # subagentes: o resumo fica no que a sessão principal fez
                t = local_time(ev.get("timestamp", ""))
                if not t or t.date() != day:
                    continue
                s = sessions.setdefault(sid, {"folder": os.path.basename(os.path.dirname(path)), "start": t, "end": t,
                                              "asks": [], "files": [], "last": ""})
                s["start"], s["end"] = min(s["start"], t), max(s["end"], t)
                msg = ev.get("message") or {}
                if ev.get("type") == "user":
                    txt = text_of(msg.get("content")).strip()
                    if txt and not txt.startswith(NOISE):
                        s["asks"].append(txt)
                elif ev.get("type") == "assistant":
                    for part in msg.get("content") or []:
                        if isinstance(part, dict) and part.get("type") == "tool_use" and part.get("name") in EDIT_TOOLS:
                            name = os.path.basename((part.get("input") or {}).get("file_path", ""))
                            if name and name not in s["files"]:
                                s["files"].append(name)
                    txt = text_of(msg.get("content")).strip()
                    if txt:
                        s["last"] = txt
    return [s for s in sorted(sessions.values(), key=lambda s: s["start"]) if s["asks"] or s["files"]]


def pretty_folder(name):
    # "C--Users-voce-projetos-canal" -> "projetos/canal"
    name = re.sub(r"^[A-Za-z]--Users-[^-]+-", "", name)
    return name.replace("--", "/").replace("-", " ")[:60] or name


def render(day, sessions):
    out = ["# Resumo de %s" % day.isoformat(), ""]
    if not sessions:
        return "\n".join(out + ["Nenhuma sessão com atividade neste dia.", ""])
    for s in sessions:
        out.append("## %s (%s-%s)" % (pretty_folder(s["folder"]), s["start"].strftime("%H:%M"), s["end"].strftime("%H:%M")))
        asks = s["asks"]
        out.append("- Pediu: " + (" | ".join(short(a, 160) for a in asks[:4]) + (" (+%d)" % (len(asks) - 4) if len(asks) > 4 else "")
                                  if asks else "(continuação de uma conversa anterior)"))
        if s["files"]:
            out.append("- Mexeu em: " + ", ".join(s["files"][:8]) + (" (+%d)" % (len(s["files"]) - 8) if len(s["files"]) > 8 else ""))
        decided = [short(a, 140) for a in asks if DECIDED.search(a)][:3]
        if decided:
            out.append("- Decidiu: " + " | ".join(decided))
        if s["last"]:
            out.append("- Onde parou: " + short(s["last"], 300))
            if ASKING.search(s["last"][-400:]):
                out.append("- Esperando você: " + short(s["last"][-250:], 250))
        out.append("")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("day", nargs="?", help="AAAA-MM-DD (padrão: ontem)")
    ap.add_argument("--dir", default=DEFAULT_DIR, help="pasta com as transcrições (padrão: ~/.claude/projects)")
    a = ap.parse_args()
    day = date.fromisoformat(a.day) if a.day else date.today() - timedelta(days=1)
    text = render(day, read_sessions(a.dir, day))
    os.makedirs(os.path.join(HERE, "digests"), exist_ok=True)
    with open(os.path.join(HERE, "digests", day.isoformat() + ".md"), "w", encoding="utf-8") as fh:
        fh.write(text)
    sys.stdout.reconfigure(encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
