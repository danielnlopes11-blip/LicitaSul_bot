"""
coletor_pncp.py
Coleta licitações da API oficial do PNCP (Portal Nacional de Contratações Públicas)
Documentação: https://pncp.gov.br/api/pncp/swagger-ui/index.html
"""

import httpx
import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Optional
from database import salvar_licitacoes, licitacao_ja_existe

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_URL = "https://pncp.gov.br/api/pncp/v1"

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "BotLicitacoes/1.0"
}

# ── Configuração de filtros globais ─────────────────────────────────────────

FILTROS = {
    "palavras_chave": [
        "software", "sistema", "tecnologia", "TI", "consultoria",
        "desenvolvimento", "aplicativo", "plataforma", "licença", "suporte"
    ],
    "valor_minimo": 10_000,
    "valor_maximo": 5_000_000,
    "modalidades": [],          # vazio = todas
    "estados": [],              # vazio = todos
    "tipos_contratacao": [],    # vazio = todos
}


# ── Funções de coleta ────────────────────────────────────────────────────────

async def buscar_compras(
    data_inicio: str,
    data_fim: str,
    uf: Optional[str] = None,
    pagina: int = 1,
    tamanho: int = 50,
) -> dict:
    """Busca compras (licitações) no PNCP com paginação."""
    params = {
        "dataInicial": data_inicio,
        "dataFinal": data_fim,
        "pagina": pagina,
        "tamanhoPagina": tamanho,
    }
    if uf:
        params["uf"] = uf

    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        url = f"{BASE_URL}/contratacoes/publicacoes"
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


async def buscar_itens_compra(cnpj_orgao: str, ano: int, numero_sequencial: int) -> list:
    """Busca os itens de uma compra específica."""
    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        url = f"{BASE_URL}/orgaos/{cnpj_orgao}/compras/{ano}/{numero_sequencial}/itens"
        resp = await client.get(url, params={"pagina": 1, "tamanhoPagina": 100})
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return resp.json().get("data", [])


async def buscar_documentos_compra(cnpj_orgao: str, ano: int, numero_sequencial: int) -> list:
    """Busca os documentos/arquivos de uma compra (edital, anexos)."""
    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        url = f"{BASE_URL}/orgaos/{cnpj_orgao}/compras/{ano}/{numero_sequencial}/arquivos"
        resp = await client.get(url)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return resp.json().get("data", [])


# ── Filtros e enriquecimento ────────────────────────────────────────────────

def aplicar_filtros(licitacao: dict) -> bool:
    """Retorna True se a licitação passa nos filtros configurados."""

    # Filtro por valor
    valor = licitacao.get("valorTotalEstimado") or licitacao.get("valorTotalHomologado") or 0
    if valor < FILTROS["valor_minimo"]:
        return False
    if FILTROS["valor_maximo"] and valor > FILTROS["valor_maximo"]:
        return False

    # Filtro por estado
    if FILTROS["estados"]:
        uf = licitacao.get("unidadeOrgao", {}).get("ufSigla", "")
        if uf not in FILTROS["estados"]:
            return False

    # Filtro por modalidade
    if FILTROS["modalidades"]:
        modalidade = licitacao.get("modalidadeNome", "").lower()
        if not any(m.lower() in modalidade for m in FILTROS["modalidades"]):
            return False

    # Filtro por palavras-chave (objeto da compra)
    if FILTROS["palavras_chave"]:
        objeto = (licitacao.get("objetoCompra") or "").lower()
        if not any(p.lower() in objeto for p in FILTROS["palavras_chave"]):
            return False

    return True


def formatar_licitacao(raw: dict, itens: list = None, documentos: list = None) -> dict:
    """Normaliza o dict bruto da API para o formato interno."""
    orgao = raw.get("unidadeOrgao", {})
    return {
        "id_externo": raw.get("numeroControlePNCP"),
        "numero_compra": raw.get("numeroCompra"),
        "ano": raw.get("anoCompra"),
        "objeto": raw.get("objetoCompra", ""),
        "modalidade": raw.get("modalidadeNome", ""),
        "situacao": raw.get("situacaoCompraNome", ""),
        "valor_estimado": raw.get("valorTotalEstimado", 0),
        "valor_homologado": raw.get("valorTotalHomologado"),
        "data_publicacao": raw.get("dataPublicacaoPncp"),
        "data_encerramento": raw.get("dataEncerramentoProposta"),
        "orgao_nome": orgao.get("nomeUnidade", ""),
        "orgao_cnpj": orgao.get("cnpj", ""),
        "orgao_uf": orgao.get("ufSigla", ""),
        "orgao_municipio": orgao.get("municipioNome", ""),
        "link_pncp": raw.get("linkSistemaOrigem", ""),
        "itens": itens or [],
        "documentos": documentos or [],
        "raw": raw,
    }


# ── Coleta principal ────────────────────────────────────────────────────────

async def coletar_periodo(dias_atras: int = 1, estados: list = None) -> list:
    """
    Coleta licitações publicadas nos últimos N dias.
    Aplica filtros e enriquece com itens/documentos.
    """
    hoje = datetime.now()
    inicio = (hoje - timedelta(days=dias_atras)).strftime("%Y%m%d")
    fim = hoje.strftime("%Y%m%d")

    ufs = estados or FILTROS["estados"] or [None]  # None = todos os estados
    novas = []

    for uf in ufs:
        pagina = 1
        while True:
            log.info(f"Buscando UF={uf} página={pagina} de {inicio} a {fim}")
            try:
                resultado = await buscar_compras(inicio, fim, uf=uf, pagina=pagina)
            except Exception as e:
                log.error(f"Erro ao buscar UF={uf} pág={pagina}: {e}")
                break

            dados = resultado.get("data", [])
            total_paginas = resultado.get("totalPaginas", 1)

            for raw in dados:
                # Pula duplicatas já salvas
                id_externo = raw.get("numeroControlePNCP")
                if licitacao_ja_existe(id_externo):
                    continue

                # Aplica filtros de relevância
                if not aplicar_filtros(raw):
                    continue

                # Enriquece com itens e documentos
                cnpj = raw.get("unidadeOrgao", {}).get("cnpj", "")
                ano = raw.get("anoCompra")
                num = raw.get("sequencialCompra")

                itens, docs = [], []
                if cnpj and ano and num:
                    try:
                        itens = await buscar_itens_compra(cnpj, ano, num)
                        docs = await buscar_documentos_compra(cnpj, ano, num)
                    except Exception as e:
                        log.warning(f"Não foi possível buscar itens/docs: {e}")

                licitacao = formatar_licitacao(raw, itens, docs)
                novas.append(licitacao)

            if pagina >= total_paginas:
                break
            pagina += 1
            await asyncio.sleep(0.3)  # respeita rate limit da API

    # Persiste no banco
    if novas:
        salvar_licitacoes(novas)
        log.info(f"✅ {len(novas)} novas licitações coletadas e salvas.")
    else:
        log.info("Nenhuma nova licitação encontrada.")

    return novas


# ── CLI de teste ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    dias = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    ufs = sys.argv[2].split(",") if len(sys.argv) > 2 else None

    resultados = asyncio.run(coletar_periodo(dias_atras=dias, estados=ufs))
    print(json.dumps(resultados[:3], ensure_ascii=False, indent=2))
