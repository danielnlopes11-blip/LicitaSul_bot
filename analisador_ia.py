"""
analisador_ia.py
Usa a API do Claude (Anthropic) para analisar editais de licitação.
Retorna score, riscos, documentos necessários e recomendação.
"""

import os
import json
import logging
import re
import httpx
import anthropic
from database import (
    buscar_licitacoes, buscar_por_id,
    salvar_analise, buscar_analise,
)

log = logging.getLogger(__name__)

# ── Perfil da empresa (edite conforme sua empresa) ───────────────────────────

PERFIL_EMPRESA = {
    "nome": "Minha Empresa Ltda",
    "cnpj": "00.000.000/0001-00",
    "porte": "ME",  # ME | EPP | Médio | Grande
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
    "observacoes": "Empresa com 5 anos de mercado, preferência por licitações regionais (Sul e Sudeste).",
}

# ── Prompt de análise ────────────────────────────────────────────────────────

PROMPT_SISTEMA = """
Você é um especialista em licitações públicas brasileiras com 20 anos de experiência.
Sua função é analisar editais e oportunidades de licitação, avaliando se fazem sentido
para uma empresa participar, identificando riscos e requisitos críticos.

Seja objetivo, direto e prático. Baseie sua análise na legislação vigente
(Lei 14.133/2021 - Nova Lei de Licitações).

SEMPRE retorne APENAS um JSON válido, sem texto adicional, sem markdown, sem blocos de código.
"""

def montar_prompt(licitacao: dict, texto_edital: str = "") -> str:
    perfil_str = json.dumps(PERFIL_EMPRESA, ensure_ascii=False, indent=2)

    return f"""
Analise esta licitação e avalie se a empresa deve participar.

## DADOS DA LICITAÇÃO
- Objeto: {licitacao['objeto']}
- Modalidade: {licitacao['modalidade']}
- Situação: {licitacao['situacao']}
- Valor Estimado: R$ {licitacao['valor_estimado']:,.2f}
- Órgão: {licitacao['orgao_nome']} ({licitacao['orgao_uf']})
- Data Publicação: {licitacao['data_publicacao']}
- Data Encerramento: {licitacao['data_encerramento']}
- Link: {licitacao.get('link_pncp', 'N/A')}

## ITENS DA LICITAÇÃO
{json.dumps(licitacao.get('itens', []), ensure_ascii=False, indent=2)[:2000]}

## TEXTO DO EDITAL (trecho)
{texto_edital[:3000] if texto_edital else "Edital não disponível. Analise com base nos dados acima."}

## PERFIL DA EMPRESA
{perfil_str}

## INSTRUÇÕES
Retorne SOMENTE este JSON (sem markdown, sem texto extra):
{{
  "score": <0 a 100, onde 100 = oportunidade perfeita>,
  "oportunidade": "<resumo em 2-3 frases do que é a licitação>",
  "alinhamento_empresa": "<como o objeto se alinha com a empresa>",
  "requisitos_criticos": [
    "<requisito 1>",
    "<requisito 2>"
  ],
  "documentos_necessarios": [
    "<documento 1>",
    "<documento 2>"
  ],
  "riscos": [
    "<risco 1: descrição>",
    "<risco 2: descrição>"
  ],
  "pontos_positivos": [
    "<ponto positivo 1>"
  ],
  "recomendacao": "PARTICIPAR" | "NÃO PARTICIPAR" | "VERIFICAR",
  "justificativa_recomendacao": "<motivo principal da recomendação em 1-2 frases>",
  "proximos_passos": [
    "<ação 1 a tomar>",
    "<ação 2 a tomar>"
  ]
}}
"""


# ── Funções de download de edital ────────────────────────────────────────────

async def baixar_texto_edital(documentos: list) -> str:
    """Tenta baixar o edital principal e extrair texto."""
    for doc in documentos:
        nome = (doc.get("titulo") or doc.get("nomeArquivo") or "").lower()
        url = doc.get("uri") or doc.get("url") or ""
        if not url:
            continue
        if "edital" in nome or "termo" in nome or "chamamento" in nome:
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    resp = await client.get(url, follow_redirects=True)
                    if resp.status_code == 200:
                        # Se for PDF, retorna aviso (precisaria de pdfplumber)
                        content_type = resp.headers.get("content-type", "")
                        if "pdf" in content_type:
                            return f"[PDF disponível em: {url}]"
                        return resp.text[:5000]
            except Exception as e:
                log.warning(f"Falha ao baixar edital {url}: {e}")
    return ""


# ── Análise principal ────────────────────────────────────────────────────────

def analisar_licitacao(licitacao: dict, texto_edital: str = "") -> dict:
    """Envia a licitação para o Claude e retorna análise estruturada."""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    prompt = montar_prompt(licitacao, texto_edital)

    try:
        resposta = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            system=PROMPT_SISTEMA,
            messages=[{"role": "user", "content": prompt}],
        )
        texto = resposta.content[0].text.strip()

        # Remove eventuais blocos de código markdown
        texto = re.sub(r"```json|```", "", texto).strip()

        analise = json.loads(texto)
        log.info(
            f"Analisada licitação id={licitacao['id']} | "
            f"score={analise.get('score')} | recomendação={analise.get('recomendacao')}"
        )
        return analise

    except json.JSONDecodeError as e:
        log.error(f"JSON inválido retornado pela IA: {e}\nTexto: {texto[:500]}")
        return {"score": 0, "recomendacao": "ERRO", "oportunidade": "Falha na análise"}
    except Exception as e:
        log.error(f"Erro na análise IA: {e}")
        raise


# ── Pipeline de análise em lote ──────────────────────────────────────────────

async def analisar_pendentes(score_minimo_alerta: int = 65, max_por_ciclo: int = 20):
    """
    Busca licitações sem análise, analisa com IA e salva resultados.
    Retorna lista das análises com score >= score_minimo_alerta.
    """
    import asyncio

    sem_analise = buscar_licitacoes(sem_analise=True, limit=max_por_ciclo)
    log.info(f"Analisando {len(sem_analise)} licitações sem análise...")

    oportunidades = []

    for lic in sem_analise:
        licitacao_id = lic["id"]

        # Baixa edital se disponível
        docs = json.loads(lic.get("documentos") or "[]")
        texto_edital = await baixar_texto_edital(docs)

        # Análise IA
        try:
            analise = analisar_licitacao(lic, texto_edital)
        except Exception:
            continue

        # Salva no banco
        salvar_analise(licitacao_id, analise)

        # Coleta oportunidades boas
        if analise.get("score", 0) >= score_minimo_alerta:
            oportunidades.append({**lic, "analise": analise})

        # Pausa para não sobrecarregar a API
        await asyncio.sleep(1)

    log.info(f"✅ {len(oportunidades)} oportunidades com score >= {score_minimo_alerta}")
    return oportunidades


# ── CLI de teste ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio
    import sys

    if len(sys.argv) > 1:
        # Analisa uma licitação específica pelo ID do banco
        lid = int(sys.argv[1])
        lic = buscar_por_id(lid)
        if lic:
            resultado = analisar_licitacao(lic)
            print(json.dumps(resultado, ensure_ascii=False, indent=2))
        else:
            print(f"Licitação id={lid} não encontrada.")
    else:
        # Analisa todas pendentes
        resultados = asyncio.run(analisar_pendentes())
        print(json.dumps(resultados, ensure_ascii=False, indent=2))
