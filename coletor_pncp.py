"""
coletor_pncp.py
Coleta licitacoes da API do PNCP com timeout generoso e retry automatico.
"""

import httpx
import asyncio
import json
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_URL   = "https://pncp.gov.br/api/consulta/v1"
HEADERS    = {"Accept": "application/json", "User-Agent": "BotLicitacoes/1.0"}
TIMEOUT    = 60   # segundos — API do PNCP pode ser lenta
MAX_RETRY  = 3    # tentativas por requisição

MODALIDADES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]

FILTROS = {
    "palavras_chave": [
        "software", "sistema", "tecnologia", "consultoria",
        "desenvolvimento", "aplicativo", "plataforma", "suporte",
        "informatica", "licenca", "dados", "digital", "servico de ti",
    ],
    "valor_minimo": 10_000,
    "valor_maximo": 5_000_000,
    "estados": [],
}


# ── HTTP com retry ────────────────────────────────────────────────────────────

async def get_json(url: str, params: dict) -> dict | None:
    """
    GET com timeout de 60s e até 3 tentativas automáticas.
    Retorna None se: sem conteúdo, timeout após retries, erro HTTP.
    """
    for tentativa in range(1, MAX_RETRY + 1):
        try:
            async with httpx.AsyncClient(
                headers=HEADERS,
                timeout=httpx.Timeout(TIMEOUT),
            ) as client:
                resp = await client.get(url, params=params)

            # Sem conteúdo = modalidade sem dados no período
            if resp.status_code == 204 or not resp.content.strip():
                return None

            # Erro do servidor
            if resp.status_code >= 400:
                log.warning(f"HTTP {resp.status_code} | params={params} | {resp.text[:100]}")
                return None

            # Parse JSON
            try:
                return resp.json()
            except Exception:
                return None   # body não é JSON = sem dados

        except httpx.ReadTimeout:
            log.warning(f"Timeout (tentativa {tentativa}/{MAX_RETRY}) | params={params}")
            if tentativa < MAX_RETRY:
                await asyncio.sleep(5 * tentativa)   # espera 5s, 10s antes de tentar de novo
            else:
                log.error(f"Desistindo após {MAX_RETRY} timeouts | params={params}")
                return None   # pula esta modalidade, não derruba o processo

        except Exception as e:
            log.error(f"Erro inesperado (tentativa {tentativa}): {e}")
            if tentativa < MAX_RETRY:
                await asyncio.sleep(3)
            else:
                return None

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
    from database import licitacao_ja_existe, salvar_licitacoes

    hoje   = datetime.now()
    inicio = (hoje - timedelta(days=dias_atras)).strftime("%Y%m%d")
    fim    = hoje.strftime("%Y%m%d")

    novas  = []
    vistas = set()

    for modalidade in MODALIDADES:
        pagina = 1
        while True:
            resultado = await get_json(
                f"{BASE_URL}/contratacoes/publicacao",
                {
                    "dataInicial":                 inicio,
                    "dataFinal":                   fim,
                    "codigoModalidadeContratacao": modalidade,
                    "pagina":                      pagina,
                    "tamanhoPagina":               50,
                },
            )

            if resultado is None:
                break   # sem dados ou erro — próxima modalidade

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
            await asyncio.sleep(0.5)

        await asyncio.sleep(0.5)

    if novas:
        salvar_licitacoes(novas)
        log.info(f"✅ {len(novas)} novas licitacoes salvas.")
    else:
        log.info("Nenhuma licitacao nova encontrada.")

    return novas


# ── Fallback: abertas ─────────────────────────────────────────────────────────

async def coletar_abertas() -> list:
    from database import licitacao_ja_existe, salvar_licitacoes

    novas  = []
    vistas = set()

    for pagina in range(1, 6):
        resultado = await get_json(
            f"{BASE_URL}/contratacoes/proposta",
            {"pagina": pagina, "tamanhoPagina": 50},
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
        await asyncio.sleep(0.5)

    if novas:
        salvar_licitacoes(novas)
        log.info(f"✅ {len(novas)} licitacoes abertas salvas.")
    else:
        log.info("Nenhuma licitacao aberta encontrada.")

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
