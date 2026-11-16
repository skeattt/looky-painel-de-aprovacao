"""Embute páginas HTML independentes como abas da Looky, cada uma no seu shadow root.

Cada arquivo em page/embeds/<aba>.html é uma página comum, que também abre sozinha no navegador.
Ao servir a Looky, o estilo, a marcação e o script de cada uma vão para um shadow root próprio:

- o CSS fica isolado (:root vira :host, body vira o invólucro), então nada vaza para a Looky nem
  vem dela, e o tema claro/escuro da Looky é repassado para a aba;
- o script roda com `document` e `location` trocados por versões que apontam para o shadow root e
  para o trecho do hash depois de "#<aba>/", então o código da página não precisa mudar nada;
- um link "#<outra-aba>/<item>" dentro de uma aba troca de aba na Looky em vez de navegar.

A página de origem continua sendo a fonte: quem a edita edita o arquivo, e a Looky embute a
versão do momento a cada carregamento.
"""
import glob
import json
import os
import re

RUNTIME = r"""<script>
window.__lookyEmbeds = {};
window.__embedDocument = function (root) {
  const own = {
    getElementById: id => root.getElementById(id),
    querySelector: sel => root.querySelector(sel),
    querySelectorAll: sel => root.querySelectorAll(sel),
    body: root.querySelector(".embed-body"),
  };
  return new Proxy(window.document, {
    get(target, key) {
      if (key in own) return own[key];
      const v = target[key];
      return typeof v === "function" ? v.bind(target) : v;
    },
  });
};
window.__embedLocation = function (tab) {
  const prefix = "#" + tab + "/";
  return {
    get hash() { return location.hash.startsWith(prefix) ? "#" + location.hash.slice(prefix.length) : ""; },
    set hash(h) { location.hash = prefix + String(h).replace(/^#/, ""); },
    get href() { return location.href; },
    get pathname() { return location.pathname; },
    get search() { return location.search; },
  };
};
window.__embedHost = function (tab, css, html) {
  const host = document.getElementById("embed-" + tab);
  const root = host.attachShadow({ mode: "open" });
  root.innerHTML = "<style>" + css + "</style><div class=\"embed-body\">" + html + "</div>";
  root.addEventListener("click", e => {
    const a = e.target.closest && e.target.closest("a[href^='#']");
    if (!a) return;
    const m = a.getAttribute("href").match(/^#([a-z0-9-]+)(?:\/(.*))?$/);
    if (!m || m[1] === tab || !document.querySelector('[data-panel="' + m[1] + '"]')) return;
    e.preventDefault();
    location.hash = m[1] + (m[2] ? "/" + m[2] : "");
  });
  const syncTheme = () => {
    const t = document.documentElement.getAttribute("data-theme");
    t ? host.setAttribute("data-theme", t) : host.removeAttribute("data-theme");
  };
  syncTheme();
  new MutationObserver(syncTheme).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return root;
};
</script>
"""


def split_page(src):
    """Separa (css, marcação, js) de uma página com <style> e <script> inline."""
    css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", src, re.S | re.I))
    js = "\n".join(re.findall(r"<script>(.*?)</script>", src, re.S | re.I))
    m = re.search(r"<body[^>]*>(.*)</body>", src, re.S | re.I)
    body = m.group(1) if m else src
    body = re.sub(r"<script>.*?</script>|<style[^>]*>.*?</style>", "", body, flags=re.S | re.I)
    return css, body.strip(), js


def scope_css(css):
    css = css.replace(':root[data-theme="dark"]', ':host([data-theme="dark"])')
    css = css.replace(':root:not([data-theme="light"])', ':host(:not([data-theme="light"]))')
    css = css.replace(":root", ":host")
    return re.sub(r"(^|[\s,}])(html|body)(?=\s*[{,:.\[])", r"\1.embed-body", css)


def js_string(s):
    return json.dumps(s, ensure_ascii=False).replace("</", "<\\/")


def tabs(folder):
    """[(aba, título)] das páginas encontradas em `folder`."""
    out = []
    for path in sorted(glob.glob(os.path.join(folder, "*.html"))):
        tab = os.path.splitext(os.path.basename(path))[0]
        if not re.match(r"^[a-z0-9-]+$", tab):
            continue
        src = open(path, encoding="utf-8").read()
        m = re.search(r"<title>(.*?)</title>", src, re.S | re.I)
        out.append((tab, (m.group(1).strip() if m else tab.capitalize())))
    return out


def build(folder):
    """(botões das abas, contêineres, scripts) para injetar na página principal."""
    found = tabs(folder)
    if not found:
        return "", "", ""
    buttons = "".join('<button role="tab" data-tab="%s">%s</button>' % (t, title) for t, title in found)
    panels = "".join('<section class="panel embed" data-panel="%s"><div id="embed-%s"></div></section>' % (t, t) for t, _ in found)
    scripts = [RUNTIME]
    for tab, _ in found:
        css, html, js = split_page(open(os.path.join(folder, tab + ".html"), encoding="utf-8").read())
        scripts.append(
            "<script>\n(function () {\n"
            "const __root = window.__embedHost(%s, %s, %s);\n"
            "const document = window.__embedDocument(__root), location = window.__embedLocation(%s);\n"
            "%s\n})();\n</script>\n" % (js_string(tab), js_string(scope_css(css)), js_string(html), js_string(tab),
                                         js.replace("</", "<\\/")))
    return buttons, panels, "".join(scripts)
