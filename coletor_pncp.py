"""
coletor_pncp.py
Coleta licitacoes da API oficial do PNCP.

Codigos de modalidade (Lei 14.133/2021):
  1  - Leilao Eletronico
  2  - Dialogo Competitivo
  3  - Concurso
  4  - Concorrencia
  5  - Concorrencia Internacional
  6  - Pregao Eletronico        ← principal
  7  - Dispensa de Licitacao
  8  - Inexigibilidade
  9  - Manifestacao de Interesse
  10 - Pre-qualificacao
  11 - Credenciamento
  12 - Leilao Presencial
"""

import httpx
import asyncio
import json
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_URL = "https://pncp.gov.br/api/consulta/v1"
HEADERS  = {"Accept": "application/json", "User-Agent": "BotLicitacoes/1.0"}

MODALIDADES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]

FILTROS = {
    "palavras_chave": [
        "software", "sistema", "tecnologia", "consultoria",
        "desenvolvimento", "aplicativo", "plataforma", "suporte",
        "informatica", "licenca", "dados", "digital", "servico de ti",
    ],
    "valor_minimo": 10_000,
    "valor_maximo": 5_000_000,
    "estados": [],  # vazio = todos
}


# ── HTTP helpers ──────────────────────────────────────────────────────────────

async def get_json(url: str, params: dict) -> dict | None:
    """
    Faz GET e retorna o JSON ou None se:
    - Resposta vazia (body em branco)
    - Status 204 (No Content)
    - JSON inválido (modalidade sem dados retorna body vazio com 200/204)
    """
    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        resp = await client.get(url, params=params)

        # Sem conteúdo = sem dados para esta modalidade/período
        if resp.status_code == 204 or not resp.content.strip():
            return None

        # Erro real do servidor
        if resp.status_code >= 400:
            log.warning(f"HTTP {resp.status_code} | {url} | {resp.text[:150]}")
            return None

        # Tenta parsear JSON
        try:
            return resp.json()
        except Exception:
            # Corpo não é JSON válido = sem resultados
            return None


# ── Filtros e formatação ──────────────────────────────────────────────────────

def passou_filtros(item: dict) -> bool:
    valor = float(item.get("valorTotalEstimado") or item.get("valorTotalHomologado") or 0)
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


# ── Coleta por período ────────────────────────────────────────────────────────

async def coletar_periodo(dias_atras: int = 2) -> list:
    """
    Coleta licitações publicadas nos últimos N dias,
    percorrendo todas as modalidades.
    """
    from database import licitacao_ja_existe, salvar_licitacoes

    hoje   = datetime.now()
    inicio = (hoje - timedelta(days=dias_atras)).strftime("%Y%m%d")
    fim    = hoje.strftime("%Y%m%d")

    novas  = []
    vistas = set()

    for modalidade in MODALIDADES:
        pagina = 1
        while True:
            params = {
                "dataInicial":                 inicio,
                "dataFinal":                   fim,
                "codigoModalidadeContratacao": modalidade,
                "pagina":                      pagina,
                "tamanhoPagina":               50,
            }

            resultado = await get_json(f"{BASE_URL}/contratacoes/publicacao", params)

            # None = sem dados para esta modalidade, vai para próxima
            if resultado is None:
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

            if pagina >= total_paginas or pagina >= 3:
                break
            pagina += 1
            await asyncio.sleep(0.2)

        await asyncio.sleep(0.3)

    if novas:
        salvar_licitacoes(novas)
        log.info(f"✅ {len(novas)} novas licitacoes salvas.")
    else:
        log.info("Nenhuma licitacao encontrada com os filtros atuais.")

    return novas


# ── Coleta abertas (fallback) ─────────────────────────────────────────────────

async def coletar_abertas() -> list:
    """Licitações com propostas abertas agora — não precisa de data nem modalidade."""
    from database import licitacao_ja_existe, salvar_licitacoes

    novas  = []
    vistas = set()

    for pagina in range(1, 6):
        resultado = await get_json(
            f"{BASE_URL}/contratacoes/proposta",
            {"pagina": pagina, "tamanhoPagina": 50}
        )
        if resultado is None:
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
        result = asyncio.run(coletar_periodo(dias_atras=int(modo) if modo.isdigit() else 2))

    print(f"\nTotal coletado: {len(result)}")
    if result:
        print(json.dumps(result[0], ensure_ascii=False, indent=2))
