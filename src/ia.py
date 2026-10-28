"""Camada de IA generativa.

A IA NÃO decide nada: quem decide é o modelo de otimização.
A IA recebe o resultado (em JSON) e:
  1. responde perguntas em linguagem natural sobre a decisão;
  2. escreve um resumo executivo para quem não é técnico.

Funciona com OpenAI ou Gemini (basta ter a chave). Sem chave, usa
respostas montadas a partir dos próprios números, para o app nunca quebrar.
"""
import json
import os

import requests

INSTRUCOES = """Você é uma analista de operações de uma empresa de delivery.
Você explica a decisão de um modelo de otimização (MILP) que escolheu onde abrir
hubs de entrega em São Paulo. Os dados são FICTÍCIOS.

Regras:
- Use SOMENTE os números do JSON abaixo. Nunca invente valores.
- "custo_extra_se_abrisse_R$_dia" é quanto o custo diário total aumentaria se
  aquele hub fechado fosse aberto à força. Use isso para explicar por que ele ficou fechado.
- "custo_extra_se_fechasse_R$_dia" é quanto o custo aumentaria se aquele hub aberto
  fosse fechado; "pedidos_sem_atendimento_se_fechasse" > 0 significa que, sem ele,
  alguns bairros ficariam fora do tempo máximo de entrega.
- Responda em português do Brasil, de forma curta e clara, com valores em R$.
- Se a pergunta não puder ser respondida com os dados, diga isso.

RESULTADO DA OTIMIZAÇÃO (JSON):
{contexto}
"""

PEDIDO_RESUMO = """Escreva um resumo executivo (no máximo 180 palavras) para a diretoria,
com: a recomendação (quantos e quais hubs abrir), custo diário, tempo médio de
entrega, os 2 hubs mais ocupados (risco em pico) e 1 próximo passo sugerido."""


def _chave(nome, segredos=None):
    if segredos and nome in segredos:
        return segredos[nome]
    return os.environ.get(nome)


def provedor_disponivel(segredos=None):
    if _chave("OPENAI_API_KEY", segredos):
        return "openai"
    if _chave("GEMINI_API_KEY", segredos):
        return "gemini"
    return None


def _openai(sistema, pergunta, segredos):
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {_chave('OPENAI_API_KEY', segredos)}"},
        json={
            "model": _chave("OPENAI_MODEL", segredos) or "gpt-4o-mini",
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": sistema},
                {"role": "user", "content": pergunta},
            ],
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta"
_modelo_gemini = None  # descoberto na primeira chamada


def _escolher_modelo_gemini(chave):
    """Pergunta à API quais modelos existem e escolhe um 'flash' (rápido e grátis)."""
    r = requests.get(f"{GEMINI_URL}/models", headers={"x-goog-api-key": chave}, timeout=30)
    r.raise_for_status()
    nomes = [m["name"].split("/")[-1] for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    flash = [n for n in nomes if "flash" in n and "lite" not in n
             and "preview" not in n and "exp" not in n and "image" not in n and "tts" not in n]
    return (sorted(flash)[-1] if flash else nomes[0])


def _gemini(sistema, pergunta, segredos):
    global _modelo_gemini
    chave = _chave("GEMINI_API_KEY", segredos)
    modelos = [m for m in (_chave("GEMINI_MODEL", segredos), _modelo_gemini,
                           "gemini-flash-latest") if m]
    corpo = {
        "system_instruction": {"parts": [{"text": sistema}]},
        "contents": [{"role": "user", "parts": [{"text": pergunta}]}],
        "generationConfig": {"temperature": 0.2},
    }
    for tentativa in range(2):
        for modelo in modelos:
            # a chave vai no cabeçalho, nunca na URL (assim ela não aparece em mensagens de erro)
            r = requests.post(f"{GEMINI_URL}/models/{modelo}:generateContent",
                              headers={"x-goog-api-key": chave}, json=corpo, timeout=60)
            if r.status_code == 404:
                continue
            r.raise_for_status()
            _modelo_gemini = modelo
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        modelos = [_escolher_modelo_gemini(chave)]
    raise requests.HTTPError("nenhum modelo do Gemini disponível para esta chave")


def _erro_seguro(e):
    """Mensagem de erro sem URL nem chave."""
    resp = getattr(e, "response", None)
    if resp is not None:
        return {400: "pedido inválido (confira a chave)", 401: "chave inválida",
                403: "chave sem permissão", 404: "modelo não encontrado",
                429: "limite de uso grátis atingido, tente em 1 minuto"}.get(
            resp.status_code, f"erro {resp.status_code}")
    return str(e).split(" for url")[0].split("?")[0]


def perguntar(pergunta: str, resumo: dict, segredos=None) -> tuple[str, str]:
    """Devolve (resposta, origem). origem = 'openai', 'gemini' ou 'local'."""
    sistema = INSTRUCOES.format(contexto=json.dumps(resumo, ensure_ascii=False))
    prov = provedor_disponivel(segredos)
    try:
        if prov == "openai":
            return _openai(sistema, pergunta, segredos), "openai"
        if prov == "gemini":
            return _gemini(sistema, pergunta, segredos), "gemini"
    except requests.RequestException as e:
        return f"{resposta_local(pergunta, resumo)}\n\n_(A IA não respondeu: {_erro_seguro(e)}. Resposta gerada localmente.)_", "local"
    return resposta_local(pergunta, resumo), "local"


def resumo_executivo(resumo: dict, segredos=None) -> tuple[str, str]:
    if provedor_disponivel(segredos):
        return perguntar(PEDIDO_RESUMO, resumo, segredos)
    return resumo_local(resumo), "local"


# ---------- respostas sem IA (modo demonstração) ----------

def _brl(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(v):
    return f"{v:.1f}%".replace(".", ",")


def resposta_local(pergunta: str, r: dict) -> str:
    p = pergunta.lower()
    for h in r["hubs_fechados"]:
        if h["hub"].lower() in p:
            extra = h["custo_extra_se_abrisse_R$_dia"]
            if extra is None:
                return f"O hub {h['hub']} ficou fechado."
            return (f"O hub **{h['hub']}** ficou fechado porque abri-lo **aumentaria o custo "
                    f"em {_brl(extra)} por dia**. O aluguel e a operação dele "
                    f"({_brl(h['custo_dia_R$'])}/dia) custam mais do que a economia em "
                    f"deslocamento que ele traria, já que os bairros próximos são bem "
                    f"atendidos por outros hubs dentro de {r['parametros']['tempo_maximo_entrega_min']} min.")
    for h in r["hubs_abertos"]:
        if h["hub"].lower() in p:
            extra = h["custo_extra_se_fechasse_R$_dia"]
            perde = h["pedidos_sem_atendimento_se_fechasse"] or 0
            if perde:
                motivo = (f"Sem ele, {perde} pedidos/dia ficariam fora do tempo máximo de entrega: "
                          "nenhum outro hub alcança esses bairros a tempo.")
            elif extra is not None:
                motivo = (f"Fechá-lo deixaria a operação {_brl(extra)} por dia mais cara, porque "
                          "os outros hubs teriam que entregar mais longe (ou já estão quase cheios).")
            else:
                motivo = ""
            return (f"O hub **{h['hub']}** foi aberto: atende {h['pedidos_dia']} pedidos/dia "
                    f"({_pct(h['ocupacao_%'])} da capacidade) nos bairros {', '.join(h['bairros'])}. "
                    + motivo)
    for b in r["bairros"]:
        if b["bairro"].lower() in p:
            return (f"**{b['bairro']}** ({b['pedidos_dia']} pedidos/dia) é atendido pelo hub "
                    f"**{b['hub']}**, a {b['km']} km, com entrega em cerca de {b['minutos']} min.")
    return ("No modo demonstração (sem chave de IA), eu respondo perguntas citando um hub ou "
            "um bairro, por exemplo: *Por que o hub Penha ficou fechado?* ou "
            "*Quem atende a Vila Olímpia?*. Com uma chave da OpenAI ou do Gemini, "
            "dá para perguntar qualquer coisa.")


def resumo_local(r: dict) -> str:
    ab = sorted(r["hubs_abertos"], key=lambda h: -h["ocupacao_%"])
    nomes = ", ".join(h["hub"] for h in r["hubs_abertos"])
    cheios = " e ".join(f"{h['hub']} ({_pct(h['ocupacao_%'])})" for h in ab[:2])
    return (
        f"**Recomendação:** abrir **{len(r['hubs_abertos'])} hubs** ({nomes}).\n\n"
        f"**Custo diário:** {_brl(r['custo_total_dia_R$'])}, sendo "
        f"{_brl(r['custo_fixo_hubs_dia_R$'])} de hubs e {_brl(r['custo_entregas_dia_R$'])} de entregas.\n\n"
        f"**Atendimento:** {r['pedidos_dia_total']:,} pedidos/dia, tempo médio de ".replace(",", ".")
        + f"{str(r['tempo_medio_entrega_min']).replace('.', ',')} min, limite de {r['parametros']['tempo_maximo_entrega_min']} min.\n\n"
        f"**Risco:** {cheios} estão perto do limite e podem não aguentar um pico de demanda.\n\n"
        f"**Próximo passo:** simular um pico de 30% para ver se a rede continua de pé."
    )
