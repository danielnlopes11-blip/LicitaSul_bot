"""
coletor_pncp.py
Coleta licitacoes da API oficial do PNCP.

Parametro obrigatorio descoberto: codigoModalidadeContratacao
Codigos das modalidades (Lei 14.133/2021):
  1  - Leilao Eletronico
  2  - Dialogo Competitivo
  3  - Concurso
  4  - Concorrencia
  5  - Concorrencia Internacional
  6  - Pregao Eletronico
  7  - Dispensa de Licitacao
  8  - Inexigibilidade
  9  - Manifestacao de Interesse
  10 - Pre-qualificacao
  11 - Credenciamento
  12 - Leilao Presencial
  13 - Concorrencia Presencial (opcional, pode nao existir)
"""

import httpx
import asyncio
import json
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_URL = "https://pncp.gov.br/api/consulta/v1"

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "BotLicitacoes/1.0",
}

# Todas as modalidades que queremos buscar
MODALIDADES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]

FILTROS = {
    "palavras_chave": [
        "software", "sistema", "tecnologia", "ti ", " ti,", "consultoria",
        "desenvolvimento", "aplicativo", "plataforma", "suporte", "informatica",
        "servico de tecnologia", "licenca", "dados", "digital",
    ],
    "valor_minimo": 10_000,
    "valor_maximo": 5_000_000,
    "estados": [],   # vazio = todos
}


# ── Chamadas HTTP ─────────────────────────────────────────────────────────────

async def buscar_por_modalidade(
    data_inicio: str,
    data_fim: str,
    modalidade: int,
    pagina: int = 1,
    tamanho: int = 50,
) -> dict:
    """
    GET /contratacoes/publicacao
    Parametros obrigatorios: dataInicial, dataFinal, codigoModalidadeContratacao, pagina
    """
    params = {
        "dataInicial":                  data_inicio,
        "dataFinal":                    data_fim,
        "codigoModalidadeContratacao":  modalidade,
        "pagina":                       pagina,
        "tamanhoPagina":                tamanho,
    }
    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        resp = await client.get(f"{BASE_URL}/contratacoes/publicacao", params=params)
        resp.raise_for_status()
        return resp.json()


async def buscar_proposta_aberta(pagina: int = 1, tamanho: int = 50) -> dict:
    """
    GET /contratacoes/proposta
    Licitacoes com prazo de proposta aberto agora. Sem filtro de data.
    """
    params = {"pagina": pagina, "tamanhoPagina": tamanho}
    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        resp = await client.get(f"{BASE_URL}/contratacoes/proposta", params=params)
        resp.raise_for_status()
        return resp.json()


# ── Filtros ───────────────────────────────────────────────────────────────────

def passou_filtros(item: dict) -> bool:
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
        "id_externo":        raw.get("numeroControlePNCP") or str(raw.get("numeroCompra", "")),
        "numero_compra":     str(raw.get("numeroCompra", "")),
        "ano":               raw.get("anoCompra"),
        "objeto":            raw.get("objetoCompra", ""),
        "modalidade":        raw.get("modalidadeNome", ""),
        "situacao":          raw.get("situacaoCompraNome", ""),
        "valor_estimado":    float(raw.get("valorTotalEstimado") or 0),
        "valor_homologado":  raw.get("valorTotalHomologado"),
        "data_publicacao":   raw.get("dataPublicacaoPncp"),
        "data_encerramento": raw.get("dataEncerramentoProposta"),
        "orgao_nome":        orgao.get("nomeUnidade", ""),
        "orgao_cnpj":        orgao.get("cnpj", ""),
        "orgao_uf":          orgao.get("ufSigla", ""),
        "orgao_municipio":   orgao.get("municipioNome", ""),
        "link_pncp":         raw.get("linkSistemaOrigem", ""),
        "itens":             [],
        "documentos":        [],
        "raw":               raw,
    }


# ── Pipelines ─────────────────────────────────────────────────────────────────

async def coletar_periodo(dias_atras: int = 2) -> list:
    """
    Coleta licitacoes de todos os tipos de modalidade publicadas nos ultimos N dias.
    Faz uma requisicao por modalidade para satisfazer o parametro obrigatorio.
    """
    from database import licitacao_ja_existe, salvar_licitacoes

    hoje   = datetime.now()
    inicio = (hoje - timedelta(days=dias_atras)).strftime("%Y%m%d")
    fim    = hoje.strftime("%Y%m%d")

    novas = []
    vistas = set()

    for modalidade in MODALIDADES:
        pagina = 1
        while True:
            try:
                resultado = await buscar_por_modalidade(inicio, fim, modalidade, pagina)
            except httpx.HTTPStatusError as e:
                # 404 = sem resultados para esta modalidade/periodo
                if e.response.status_code == 404:
                    break
                log.warning(f"HTTP {e.response.status_code} modalidade={modalidade} pag={pagina}")
                break
            except Exception as e:
                log.error(f"Erro modalidade={modalidade} pag={pagina}: {e}")
                break

            dados         = resultado.get("data", [])
            total_paginas = resultado.get("totalPaginas", 1)

            if dados:
                log.info(f"Modalidade {modalidade:2d} | pag {pagina}/{total_paginas} | {len(dados)} registros")

            for raw in dados:
                id_ext = raw.get("numeroControlePNCP") or str(raw.get("numeroCompra", ""))
                if id_ext in vistas or licitacao_ja_existe(id_ext):
                    continue
                vistas.add(id_ext)
                if not passou_filtros(raw):
                    continue
                novas.append(formatar(raw))

            if pagina >= total_paginas or pagina >= 3:  # max 3 pag por modalidade
                break
            pagina += 1
            await asyncio.sleep(0.2)

        await asyncio.sleep(0.3)  # pausa entre modalidades

    if novas:
        salvar_licitacoes(novas)
        log.info(f"✅ {len(novas)} novas licitacoes salvas.")
    else:
        log.info("Nenhuma licitacao encontrada com os filtros configurados.")

    return novas


async def coletar_abertas() -> list:
    """
    Busca licitacoes com propostas abertas agora (sem filtro de data/modalidade).
    Endpoint alternativo quando /publicacao nao retorna resultados.
    """
    from database import licitacao_ja_existe, salvar_licitacoes

    novas  = []
    vistas = set()
    pagina = 1

    while pagina <= 5:
        try:
            resultado = await buscar_proposta_aberta(pagina=pagina)
        except httpx.HTTPStatusError as e:
            log.warning(f"HTTP {e.response.status_code} em /proposta pag={pagina}: {e.response.text[:200]}")
            break
        except Exception as e:
            log.error(f"Erro /proposta pag={pagina}: {e}")
            break

        dados         = resultado.get("data", [])
        total_paginas = resultado.get("totalPaginas", 1)
        log.info(f"[ABERTAS] pag {pagina}/{total_paginas} | {len(dados)} registros")

        for raw in dados:
            id_ext = raw.get("numeroControlePNCP") or str(raw.get("numeroCompra", ""))
            if id_ext in vistas or licitacao_ja_existe(id_ext):
                continue
            vistas.add(id_ext)
            if not passou_filtros(raw):
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

    modo = sys.argv[1] if len(sys.argv) > 1 else "2"

    if modo == "abertas":
        result = asyncio.run(coletar_abertas())
    else:
        dias = int(modo) if modo.isdigit() else 2
        result = asyncio.run(coletar_periodo(dias_atras=dias))

    print(f"\nTotal coletado: {len(result)}")
    if result:
        print(json.dumps(result[0], ensure_ascii=False, indent=2))
