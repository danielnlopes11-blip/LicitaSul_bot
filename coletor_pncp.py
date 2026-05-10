"""
coletor_pncp.py
Coleta licitacoes da API oficial do PNCP.

URL correta (API de Consulta):
  https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao
  https://pncp.gov.br/api/consulta/v1/contratacoes/proposta
"""

import httpx
import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_URL = "https://pncp.gov.br/api/consulta/v1"

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "BotLicitacoes/1.0",
}

FILTROS = {
    "palavras_chave": [
        "software", "sistema", "tecnologia", "TI", "consultoria",
        "desenvolvimento", "aplicativo", "plataforma", "licenca", "suporte",
    ],
    "valor_minimo": 10_000,
    "valor_maximo": 5_000_000,
    "estados": [],   # vazio = todos
}


# ── Chamadas HTTP ─────────────────────────────────────────────────────────────

async def buscar_contratacoes(data_inicio: str, data_fim: str, pagina: int = 1, tamanho: int = 50) -> dict:
    """Endpoint: /contratacoes/publicacao — filtra por data de publicacao."""
    params = {
        "dataInicial":   data_inicio,
        "dataFinal":     data_fim,
        "pagina":        pagina,
        "tamanhoPagina": tamanho,
    }
    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        url = f"{BASE_URL}/contratacoes/publicacao"
        log.info(f"GET {url} {params}")
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


async def buscar_contratacoes_proposta(pagina: int = 1, tamanho: int = 50) -> dict:
    """Endpoint: /contratacoes/proposta — licitacoes com propostas abertas agora."""
    params = {"pagina": pagina, "tamanhoPagina": tamanho}
    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        url = f"{BASE_URL}/contratacoes/proposta"
        log.info(f"GET {url} {params}")
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


# ── Filtros e formatacao ──────────────────────────────────────────────────────

def aplicar_filtros(item: dict) -> bool:
    valor = item.get("valorTotalEstimado") or item.get("valorTotalHomologado") or 0
    if FILTROS["valor_minimo"] and valor < FILTROS["valor_minimo"]:
        return False
    if FILTROS["valor_maximo"] and valor > FILTROS["valor_maximo"]:
        return False
    if FILTROS["estados"]:
        uf = (item.get("unidadeOrgao") or {}).get("ufSigla", "")
        if uf not in FILTROS["estados"]:
            return False
    if FILTROS["palavras_chave"]:
        objeto = (item.get("objetoCompra") or "").lower()
        if not any(p.lower() in objeto for p in FILTROS["palavras_chave"]):
            return False
    return True


def formatar(raw: dict) -> dict:
    orgao = raw.get("unidadeOrgao") or {}
    return {
        "id_externo":       raw.get("numeroControlePNCP") or raw.get("numeroCompra", ""),
        "numero_compra":    raw.get("numeroCompra", ""),
        "ano":              raw.get("anoCompra"),
        "objeto":           raw.get("objetoCompra", ""),
        "modalidade":       raw.get("modalidadeNome", ""),
        "situacao":         raw.get("situacaoCompraNome", ""),
        "valor_estimado":   raw.get("valorTotalEstimado") or 0,
        "valor_homologado": raw.get("valorTotalHomologado"),
        "data_publicacao":  raw.get("dataPublicacaoPncp"),
        "data_encerramento": raw.get("dataEncerramentoProposta"),
        "orgao_nome":       orgao.get("nomeUnidade", ""),
        "orgao_cnpj":       orgao.get("cnpj", ""),
        "orgao_uf":         orgao.get("ufSigla", ""),
        "orgao_municipio":  orgao.get("municipioNome", ""),
        "link_pncp":        raw.get("linkSistemaOrigem", ""),
        "itens":            [],
        "documentos":       [],
        "raw":              raw,
    }


# ── Pipelines de coleta ───────────────────────────────────────────────────────

async def coletar_periodo(dias_atras: int = 2) -> list:
    """Coleta licitacoes publicadas nos ultimos N dias."""
    # Import do database aqui dentro para evitar circular import
    from database import licitacao_ja_existe, salvar_licitacoes

    hoje   = datetime.now()
    inicio = (hoje - timedelta(days=dias_atras)).strftime("%Y%m%d")
    fim    = hoje.strftime("%Y%m%d")

    novas  = []
    pagina = 1

    while True:
        try:
            resultado = await buscar_contratacoes(inicio, fim, pagina=pagina)
        except httpx.HTTPStatusError as e:
            log.error(f"HTTP {e.response.status_code} na pagina {pagina}: {e.response.text[:200]}")
            break
        except Exception as e:
            log.error(f"Erro na coleta pagina {pagina}: {e}")
            break

        dados         = resultado.get("data", [])
        total_paginas = resultado.get("totalPaginas", 1)
        log.info(f"Pagina {pagina}/{total_paginas} — {len(dados)} registros")

        for raw in dados:
            id_externo = raw.get("numeroControlePNCP") or raw.get("numeroCompra", "")
            if licitacao_ja_existe(id_externo):
                continue
            if not aplicar_filtros(raw):
                continue
            novas.append(formatar(raw))

        if pagina >= total_paginas:
            break
        pagina += 1
        await asyncio.sleep(0.3)

    if novas:
        salvar_licitacoes(novas)
        log.info(f"✅ {len(novas)} novas licitacoes salvas.")
    else:
        log.info("Nenhuma nova licitacao encontrada.")

    return novas


async def coletar_abertas() -> list:
    """Coleta licitacoes com propostas abertas agora."""
    from database import licitacao_ja_existe, salvar_licitacoes

    novas  = []
    pagina = 1

    while pagina <= 5:
        try:
            resultado = await buscar_contratacoes_proposta(pagina=pagina)
        except Exception as e:
            log.error(f"Erro em /proposta pagina {pagina}: {e}")
            break

        dados         = resultado.get("data", [])
        total_paginas = resultado.get("totalPaginas", 1)
        log.info(f"[ABERTAS] Pagina {pagina}/{total_paginas} — {len(dados)} registros")

        for raw in dados:
            id_externo = raw.get("numeroControlePNCP") or raw.get("numeroCompra", "")
            if licitacao_ja_existe(id_externo):
                continue
            if not aplicar_filtros(raw):
                continue
            novas.append(formatar(raw))

        if pagina >= total_paginas:
            break
        pagina += 1
        await asyncio.sleep(0.3)

    if novas:
        salvar_licitacoes(novas)
        log.info(f"✅ {len(novas)} licitacoes abertas salvas.")
    else:
        log.info("Nenhuma licitacao aberta encontrada com os filtros.")

    return novas


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from database import init_db
    init_db()

    modo = sys.argv[1] if len(sys.argv) > 1 else "1"

    if modo == "abertas":
        result = asyncio.run(coletar_abertas())
    else:
        dias = int(modo) if modo.isdigit() else 2
        result = asyncio.run(coletar_periodo(dias_atras=dias))

    print(f"\nTotal coletado: {len(result)}")
    if result:
        print(json.dumps(result[0], ensure_ascii=False, indent=2))
