"""
analisador_ia.py
Analisa editais usando Groq ou Gemini.
Trata rate limit (429) com espera automatica baseada no header Retry-After.
"""

import os
import json
import logging
import re
import asyncio
import httpx
from dotenv import load_dotenv
from database import buscar_licitacoes, buscar_por_id, salvar_analise

load_dotenv()
log = logging.getLogger(__name__)

IA_PROVIDER    = os.getenv("IA_PROVIDER",   "groq").lower()
GROQ_API_KEY   = os.getenv("GROQ_API_KEY",   "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_MODEL     = os.getenv("GROQ_MODEL",   "llama-3.3-70b-versatile")
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# Pausa entre análises para não estourar o rate limit
# Groq free: 12.000 tokens/min → ~1 análise a cada 8s com segurança
PAUSA_ENTRE_ANALISES = int(os.getenv("PAUSA_ANALISE_SEGUNDOS", "10"))
MAX_RETRY_RATE_LIMIT = 4   # tentativas quando receber 429


PERFIL_EMPRESA = {
    "nome": "Minha Empresa Ltda",
    "cnpj": "00.000.000/0001-00",
    "porte": "ME",
    "uf_sede": "SC",
    "segmentos": [
        "Desenvolvimento de software",
        "Consultoria em TI",
        "Suporte tecnico",
        "Integracao de sistemas",
    ],
    "certidoes_disponiveis": [
        "CND Federal", "CND Estadual", "CND Municipal",
        "FGTS", "CNDT", "Balanco Patrimonial",
    ],
    "faturamento_anual_reais": 500_000,
    "observacoes": "Empresa com 5 anos de mercado, preferencia por licitacoes regionais.",
}

PROMPT_SISTEMA = """
Voce e um especialista em licitacoes publicas brasileiras.
Analise editais e avalie se fazem sentido para a empresa participar.
Baseie sua analise na Lei 14.133/2021.
RETORNE APENAS JSON VALIDO. Sem texto antes ou depois. Sem markdown.
"""

def montar_prompt(licitacao: dict) -> str:
    return f"""
Analise esta licitacao:

OBJETO: {licitacao.get('objeto', '')}
MODALIDADE: {licitacao.get('modalidade', '')}
VALOR ESTIMADO: R$ {licitacao.get('valor_estimado', 0):,.2f}
ORGAO: {licitacao.get('orgao_nome', '')} ({licitacao.get('orgao_uf', '')})
ENCERRAMENTO: {licitacao.get('data_encerramento', 'N/D')}

PERFIL DA EMPRESA:
{json.dumps(PERFIL_EMPRESA, ensure_ascii=False)}

Retorne SOMENTE este JSON:
{{
  "score": <0 a 100>,
  "oportunidade": "<resumo em 1 frase>",
  "requisitos_criticos": ["<req 1>", "<req 2>"],
  "documentos_necessarios": ["<doc 1>", "<doc 2>"],
  "riscos": ["<risco 1>"],
  "recomendacao": "PARTICIPAR",
  "justificativa_recomendacao": "<motivo curto>",
  "proximos_passos": ["<acao 1>"]
}}
O campo recomendacao deve ser: PARTICIPAR | NAO PARTICIPAR | VERIFICAR
"""


# ── Clientes IA com retry no rate limit ──────────────────────────────────────

async def chamar_groq(prompt: str) -> str:
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY nao configurada")

    for tentativa in range(1, MAX_RETRY_RATE_LIMIT + 1):
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": GROQ_MODEL,
                    "messages": [
                        {"role": "system", "content": PROMPT_SISTEMA},
                        {"role": "user",   "content": prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 600,          # reduzido para economizar tokens
                    "response_format": {"type": "json_object"},
                },
            )

        if resp.status_code == 429:
            # Lê o tempo de espera sugerido pelo Groq
            retry_after = int(resp.headers.get("retry-after", "15"))
            # Também tenta extrair do body ("try again in X.Xs")
            try:
                body = resp.json()
                msg  = body.get("error", {}).get("message", "")
                match = re.search(r"try again in (\d+\.?\d*)s", msg)
                if match:
                    retry_after = int(float(match.group(1))) + 2
            except Exception:
                pass

            log.warning(f"Rate limit Groq (tentativa {tentativa}/{MAX_RETRY_RATE_LIMIT}). Aguardando {retry_after}s...")
            await asyncio.sleep(retry_after)
            continue

        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    raise Exception("Rate limit Groq esgotado após todas as tentativas")


async def chamar_gemini(prompt: str) -> str:
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY nao configurada")

    for tentativa in range(1, MAX_RETRY_RATE_LIMIT + 1):
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
        )
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json={
                "system_instruction": {"parts": [{"text": PROMPT_SISTEMA}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.1,
                    "maxOutputTokens": 600,
                    "responseMimeType": "application/json",
                },
            })

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("retry-after", "30"))
            log.warning(f"Rate limit Gemini (tentativa {tentativa}). Aguardando {retry_after}s...")
            await asyncio.sleep(retry_after)
            continue

        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]

    raise Exception("Rate limit Gemini esgotado após todas as tentativas")


async def chamar_ia(prompt: str) -> str:
    if IA_PROVIDER == "gemini":
        return await chamar_gemini(prompt)
    return await chamar_groq(prompt)


# ── Análise principal ─────────────────────────────────────────────────────────

async def analisar_licitacao(licitacao: dict) -> dict:
    prompt = montar_prompt(licitacao)
    try:
        texto  = await chamar_ia(prompt)
        texto  = re.sub(r"```json|```", "", texto).strip()
        analise = json.loads(texto)
        log.info(f"[{IA_PROVIDER.upper()}] id={licitacao.get('id')} score={analise.get('score')} rec={analise.get('recomendacao')}")
        return analise
    except json.JSONDecodeError as e:
        log.error(f"JSON invalido: {e}")
        return {"score": 0, "recomendacao": "ERRO", "oportunidade": "Falha no parse JSON"}
    except Exception as e:
        log.error(f"Erro na analise: {e}")
        raise


# ── Pipeline em lote ──────────────────────────────────────────────────────────

async def analisar_pendentes(score_minimo_alerta: int = 65, max_por_ciclo: int = 10) -> list:
    """
    Analisa licitações sem análise.
    max_por_ciclo limitado a 10 por padrão para respeitar rate limit do Groq free.
    Com pausa de 10s entre cada análise = ~100s para 10 análises.
    """
    sem_analise  = buscar_licitacoes(sem_analise=True, limit=max_por_ciclo)
    oportunidades = []

    log.info(f"Analisando {len(sem_analise)} licitacoes com [{IA_PROVIDER.upper()}] (pausa {PAUSA_ENTRE_ANALISES}s entre cada)...")

    for i, lic in enumerate(sem_analise):
        try:
            analise = await analisar_licitacao(lic)
        except Exception as e:
            log.error(f"Pulando licitacao id={lic['id']}: {e}")
            continue

        salvar_analise(lic["id"], analise)

        if analise.get("score", 0) >= score_minimo_alerta:
            oportunidades.append({**lic, "analise": analise})

        # Pausa entre análises para não estourar rate limit
        if i < len(sem_analise) - 1:
            log.info(f"Aguardando {PAUSA_ENTRE_ANALISES}s para respeitar rate limit...")
            await asyncio.sleep(PAUSA_ENTRE_ANALISES)

    log.info(f"✅ {len(oportunidades)} oportunidades com score >= {score_minimo_alerta}")
    return oportunidades


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    print(f"Provider: {IA_PROVIDER.upper()} | Modelo: {GROQ_MODEL if IA_PROVIDER == 'groq' else GEMINI_MODEL}")
    print(f"Pausa entre analises: {PAUSA_ENTRE_ANALISES}s | Max por ciclo: 10")

    if len(sys.argv) > 1:
        lic = buscar_por_id(int(sys.argv[1]))
        if lic:
            resultado = asyncio.run(analisar_licitacao(lic))
            print(json.dumps(resultado, ensure_ascii=False, indent=2))
    else:
        asyncio.run(analisar_pendentes())
