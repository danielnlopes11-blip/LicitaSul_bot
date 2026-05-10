"""
analisador_ia.py
Analisa editais de licitação usando Groq ou Gemini (ambos gratuitos).

Configure no .env:
    IA_PROVIDER=groq          # ou: gemini
    GROQ_API_KEY=gsk_...      # obter em: console.groq.com
    GEMINI_API_KEY=AIza...    # obter em: aistudio.google.com
"""

import os
import json
import logging
import re
import httpx
from dotenv import load_dotenv
from database import (
    buscar_licitacoes, buscar_por_id,
    salvar_analise, buscar_analise,
)

load_dotenv()
log = logging.getLogger(__name__)

# ── Configuração do provider ─────────────────────────────────────────────────

IA_PROVIDER  = os.getenv("IA_PROVIDER",   "groq").lower()   # "groq" ou "gemini"
GROQ_API_KEY   = os.getenv("GROQ_API_KEY",   "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Modelos recomendados (gratuitos)
GROQ_MODEL   = os.getenv("GROQ_MODEL",   "llama-3.3-70b-versatile")  # rápido e capaz
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")          # rápido e gratuito


# ── Perfil da empresa ────────────────────────────────────────────────────────

PERFIL_EMPRESA = {
    "nome": "Minha Empresa Ltda",
    "cnpj": "00.000.000/0001-00",
    "porte": "ME",   # ME | EPP | Médio | Grande
    "uf_sede": "SC",
    "segmentos": [
        "Desenvolvimento de software",
        "Consultoria em TI",
        "Suporte técnico",
        "Integração de sistemas",
    ],
    "certidoes_disponiveis": [
        "CND Federal", "CND Estadual", "CND Municipal",
        "FGTS", "CNDT", "Balanço Patrimonial",
    ],
    "experiencia": [
        "Sistemas de gestão pública (ERP)",
        "Portais web e aplicativos móveis",
        "Infraestrutura e cloud",
    ],
    "faturamento_anual_reais": 500_000,
    "observacoes": "Empresa com 5 anos de mercado, preferência por licitações regionais.",
}


# ── Prompt ───────────────────────────────────────────────────────────────────

PROMPT_SISTEMA = """
Você é um especialista em licitações públicas brasileiras com 20 anos de experiência.
Sua função é analisar editais e oportunidades de licitação, avaliando se fazem sentido
para uma empresa participar, identificando riscos e requisitos críticos.

Seja objetivo, direto e prático. Baseie sua análise na legislação vigente
(Lei 14.133/2021 - Nova Lei de Licitações).

RETORNE APENAS JSON VÁLIDO. Sem texto antes ou depois. Sem markdown. Sem blocos de código.
"""

def montar_prompt(licitacao: dict, texto_edital: str = "") -> str:
    perfil_str = json.dumps(PERFIL_EMPRESA, ensure_ascii=False, indent=2)
    return f"""
Analise esta licitação e avalie se a empresa deve participar.

## DADOS DA LICITAÇÃO
- Objeto: {licitacao.get('objeto', '')}
- Modalidade: {licitacao.get('modalidade', '')}
- Situação: {licitacao.get('situacao', '')}
- Valor Estimado: R$ {licitacao.get('valor_estimado', 0):,.2f}
- Órgão: {licitacao.get('orgao_nome', '')} ({licitacao.get('orgao_uf', '')})
- Data Publicação: {licitacao.get('data_publicacao', '')}
- Data Encerramento: {licitacao.get('data_encerramento', '')}

## ITENS DA LICITAÇÃO
{json.dumps(licitacao.get('itens', []), ensure_ascii=False)[:1500]}

## TEXTO DO EDITAL (trecho)
{texto_edital[:3000] if texto_edital else "Edital não disponível. Analise com base nos dados acima."}

## PERFIL DA EMPRESA
{perfil_str}

## RETORNE SOMENTE ESTE JSON (sem markdown, sem texto extra):
{{
  "score": <0 a 100>,
  "oportunidade": "<resumo em 2 frases>",
  "alinhamento_empresa": "<como o objeto se alinha com a empresa>",
  "requisitos_criticos": ["<req 1>", "<req 2>"],
  "documentos_necessarios": ["<doc 1>", "<doc 2>"],
  "riscos": ["<risco 1>", "<risco 2>"],
  "pontos_positivos": ["<ponto 1>"],
  "recomendacao": "PARTICIPAR",
  "justificativa_recomendacao": "<motivo em 1-2 frases>",
  "proximos_passos": ["<ação 1>", "<ação 2>"]
}}

O campo "recomendacao" deve ser exatamente um de: PARTICIPAR | NÃO PARTICIPAR | VERIFICAR
"""


# ── Clientes de IA ───────────────────────────────────────────────────────────

async def chamar_groq(prompt: str) -> str:
    """
    Chama a API do Groq — compatível com OpenAI.
    Plano gratuito: 14.400 requisições/dia, 6.000 tokens/min.
    Obter key gratuita: https://console.groq.com
    """
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY não configurada no .env")

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "system", "content": PROMPT_SISTEMA},
                    {"role": "user",   "content": prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 1500,
                "response_format": {"type": "json_object"},  # força JSON puro
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


async def chamar_gemini(prompt: str) -> str:
    """
    Chama a API do Gemini (Google AI Studio).
    Plano gratuito: 1.500 requisições/dia, 1M tokens/min (flash).
    Obter key gratuita: https://aistudio.google.com/apikey
    """
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY não configurada no .env")

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )

    payload = {
        "system_instruction": {
            "parts": [{"text": PROMPT_SISTEMA}]
        },
        "contents": [
            {"role": "user", "parts": [{"text": prompt}]}
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 1500,
            "responseMimeType": "application/json",  # força JSON puro
        },
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]


async def chamar_ia(prompt: str) -> str:
    """Despacha para o provider configurado em IA_PROVIDER."""
    if IA_PROVIDER == "gemini":
        return await chamar_gemini(prompt)
    return await chamar_groq(prompt)   # padrão: groq


# ── Análise principal ────────────────────────────────────────────────────────

async def analisar_licitacao(licitacao: dict, texto_edital: str = "") -> dict:
    """Envia a licitação para a IA e retorna análise estruturada."""
    prompt = montar_prompt(licitacao, texto_edital)

    try:
        texto = await chamar_ia(prompt)

        # Remove eventuais blocos de código markdown que o modelo insira
        texto = re.sub(r"```json|```", "", texto).strip()

        analise = json.loads(texto)
        log.info(
            f"✅ [{IA_PROVIDER.upper()}] id={licitacao.get('id')} "
            f"score={analise.get('score')} rec={analise.get('recomendacao')}"
        )
        return analise

    except json.JSONDecodeError as e:
        log.error(f"JSON inválido: {e} | texto recebido: {texto[:300]}")
        return {"score": 0, "recomendacao": "ERRO", "oportunidade": "Falha no parse JSON"}
    except httpx.HTTPStatusError as e:
        log.error(f"Erro HTTP {e.response.status_code}: {e.response.text[:300]}")
        raise
    except Exception as e:
        log.error(f"Erro inesperado na análise: {e}")
        raise


# ── Download de edital ────────────────────────────────────────────────────────

async def baixar_texto_edital(documentos: list) -> str:
    """Tenta baixar o edital principal e extrair texto."""
    for doc in documentos:
        nome = (doc.get("titulo") or doc.get("nomeArquivo") or "").lower()
        url  = doc.get("uri") or doc.get("url") or ""
        if not url:
            continue
        if any(k in nome for k in ("edital", "termo", "chamamento")):
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    resp = await client.get(url, follow_redirects=True)
                    if resp.status_code == 200:
                        ct = resp.headers.get("content-type", "")
                        if "pdf" in ct:
                            return f"[PDF disponível em: {url}]"
                        return resp.text[:5000]
            except Exception as e:
                log.warning(f"Falha ao baixar edital {url}: {e}")
    return ""


# ── Pipeline em lote ──────────────────────────────────────────────────────────

async def analisar_pendentes(score_minimo_alerta: int = 65, max_por_ciclo: int = 20):
    """Analisa todas as licitações sem análise no banco."""
    import asyncio

    sem_analise = buscar_licitacoes(sem_analise=True, limit=max_por_ciclo)
    log.info(f"Analisando {len(sem_analise)} licitações com [{IA_PROVIDER.upper()}]...")

    oportunidades = []

    for lic in sem_analise:
        docs = json.loads(lic.get("documentos") or "[]")
        texto_edital = await baixar_texto_edital(docs)

        try:
            analise = await analisar_licitacao(lic, texto_edital)
        except Exception:
            continue

        salvar_analise(lic["id"], analise)

        if analise.get("score", 0) >= score_minimo_alerta:
            oportunidades.append({**lic, "analise": analise})

        await asyncio.sleep(0.5)   # evita rate limit

    log.info(f"✅ {len(oportunidades)} oportunidades com score >= {score_minimo_alerta}")
    return oportunidades


# ── CLI de teste ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio, sys

    print(f"🤖 Provider ativo : {IA_PROVIDER.upper()}")
    print(f"📦 Modelo         : {GROQ_MODEL if IA_PROVIDER == 'groq' else GEMINI_MODEL}")
    print()

    if len(sys.argv) > 1:
        lid = int(sys.argv[1])
        lic = buscar_por_id(lid)
        if lic:
            resultado = asyncio.run(analisar_licitacao(lic))
            print(json.dumps(resultado, ensure_ascii=False, indent=2))
        else:
            print(f"Licitação id={lid} não encontrada.")
    else:
        resultados = asyncio.run(analisar_pendentes())
        print(json.dumps(resultados, ensure_ascii=False, indent=2))
