# Rotina diária do agente

Texto para colar numa tarefa agendada do Claude Code (uma vez por dia, de manhã). A ordem importa: primeiro o que o produtor já decidiu, depois o que mudou ontem, por último o que precisa de decisão nova.

```
Você cuida da Looky, o painel de aprovação em <PASTA DA LOOKY>. Trabalhe só pela CLI (python looky.py ...).

1. Cliques primeiro. Rode `python looky.py queue`. Para cada item:
   - aprovado: faça o que o cartão descreve (campo ref, se houver) e o que a nota pedir. Se for uma escolha A/B/C,
     use a opção marcada.
   - passou: não faça nada.
   - só nota: trate a nota como instrução só para aquele item.
   Ao terminar cada um: `python looky.py done <id> "resultado em uma linha"`.
   Se faltar algo que você não consegue fazer sozinho (login, aprovação de gasto, render longo), não marque como
   feito: crie um item com `python looky.py wait add <id> --area ... --item "o que falta"`.

2. O que mudou ontem. Rode `python digest.py` e leia só esse resumo, não as transcrições. Para cada frente
   que andou, atualize com `python looky.py stream set <id> --now "..." --next "..." --state ...`.
   O que ficou esperando o produtor vira `wait add`.

3. Decisões novas. Tudo que precisa de um sim vira cartão: `python looky.py card add <id> --title "Nome: frase"
   --detail "por que precisa de você" --from "<origem>"`. Ideia de motion: --kind motion e --image com a prévia.
   Escolha entre direções: --option "A=..." --option "B=..." --option "C=...".

4. Feche com `python looky.py brief --out brief.md`. Esse arquivo abre toda conversa nova (veja o hook abaixo).

Não pergunte nada no texto: o produtor responde pelo painel.
```

## Hook que carrega o resumo em toda conversa nova

Em `.claude/settings.json` da pasta onde você abre as conversas (ou no `~/.claude/settings.json` para todas):

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [ { "type": "command", "command": "python \"<PASTA DA LOOKY>/looky.py\" brief" } ] }
    ]
  }
}
```

O hook imprime o resumo, e o Claude Code o coloca no começo da conversa. Com ele, uma conversa nova já sabe o que está no ar, o que está parado e quais cliques faltam executar, sem reler o histórico.
