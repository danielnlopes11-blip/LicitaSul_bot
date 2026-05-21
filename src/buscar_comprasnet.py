"""
Busca licitações no ComprasNet (federal) e BEC/SP
API: https://compras.dados.gov.br/
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

OUTPUT_DIR = Path("data")
OUTPUT_DIR.mkdir(exist_ok=True)

# Códigos SIORG/UASG de órgãos federais em Içara/Criciúma
UASGS_REGIAO = {
    # Órgãos federais com presença na região de Criciúma/Içara
    "153098": "IFSC - Campus Criciúma",
    "153063": "IFSC - Reitoria",
    "110404": "INSS - APS Criciúma",
    "110405": "INSS - APS Içara",
    "926130": "Receita Federal - Criciúma",
    "200305": "CEF - Criciúma",
    "250005": "UFSC - Unidade Criciúma",
}

HEADERS = {"Accept": "application/json"}
BASE_URL = "https://compras.dados.gov.br"


def buscar_licitacoes_uasg(uasg: str, nome_orgao: str) -> list[dict]:
    """Busca licitações abertas de uma UASG específica."""
    licitacoes = []
    data_ini = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")

    print(f"  🔍 ComprasNet - {nome_orgao} (UASG {uasg})...")

    try:
        url = f"{BASE_URL}/licitacoes/doc/licitacao"
        params = {
            "co_uasg": uasg,
            "_offset": 0,
            "_limit": 50,
            "dt_abertura_ini": data_ini,
        }
        resp = requests.get(url, params=params, headers=HEADERS, timeout=20)
        if resp.status_code == 200:
            dados = resp.json()
            for item in dados.get("_embedded", {}).get("licitacoes", []):
                licitacoes.append({
                    "id": f"COMPRASNET-{uasg}-{item.get('co_licitacao', '')}",
                    "fonte": "ComprasNet",
                    "municipio": "Criciúma/Içara",
                    "uf": "SC",
                    "orgao": nome_orgao,
                    "cnpj": "",
                    "modalidade": item.get("no_modalidade", ""),
                    "objeto": item.get("ds_objeto", ""),
                    "valor_estimado": item.get("vl_global_estimado", 0),
                    "data_publicacao": item.get("dt_abertura", ""),
                    "data_encerramento": item.get("dt_entrega_proposta", ""),
                    "situacao": item.get("no_situacao", ""),
                    "link": f"https://www.gov.br/compras/pt-br/detalhe-licitacao?uasg={uasg}&nroEdital={item.get('co_licitacao','')}",
                    "numero_processo": item.get("co_licitacao", ""),
                })
    except Exception as e:
        print(f"    ⚠️  Erro UASG {uasg}: {e}")

    time.sleep(0.3)
    return licitacoes


def buscar_por_municipio_pncp_federal() -> list[dict]:
    """Usa a API do PNCP para buscar órgãos federais em SC."""
    licitacoes = []
    print("  🔍 Órgãos federais em SC via PNCP...")

    municipios = {
        "Criciúma": "4204608",
        "Içara": "4207007",
    }

    for cidade, ibge in municipios.items():
        try:
            data_ini = (datetime.now() - timedelta(days=14)).strftime("%Y%m%d")
            data_fim = datetime.now().strftime("%Y%m%d")
            url = "https://pncp.gov.br/api/pncp/v1/contratacoes/publicacoes"
            params = {
                "codigoMunicipioIbge": ibge,
                "dataInicial": data_ini,
                "dataFinal": data_fim,
                "esfera": "F",  # Federal
                "pagina": 1,
                "tamanhoPagina": 50,
            }
            resp = requests.get(url, params=params, timeout=20)
            if resp.status_code == 200:
                dados = resp.json()
                for item in dados.get("data", []):
                    licitacoes.append({
                        "id": f"PNCP-FED-{item.get('numeroControlePNCP', '')}",
                        "fonte": "PNCP Federal",
                        "municipio": cidade,
                        "uf": "SC",
                        "orgao": item.get("unidadeOrgao", {}).get("nomeUnidade", ""),
                        "cnpj": item.get("unidadeOrgao", {}).get("cnpj", ""),
                        "modalidade": item.get("modalidadeNome", ""),
                        "objeto": item.get("objetoCompra", ""),
                        "valor_estimado": item.get("valorTotalEstimado", 0),
                        "data_publicacao": item.get("dataPublicacaoPncp", ""),
                        "data_encerramento": item.get("dataEncerramentoProposta", ""),
                        "situacao": item.get("situacaoCompraNome", ""),
                        "link": f"https://pncp.gov.br/app/editais/{item.get('numeroControlePNCP','')}",
                        "numero_processo": item.get("processo", ""),
                    })
        except Exception as e:
            print(f"    ⚠️  Federal {cidade}: {e}")
        time.sleep(0.5)

    return licitacoes


def main():
    print("=" * 60)
    print("🔍 ComprasNet / Órgãos Federais na Região")
    print("=" * 60)

    todas = []

    # Busca por UASG (órgãos conhecidos)
    for uasg, nome in UASGS_REGIAO.items():
        todas.extend(buscar_licitacoes_uasg(uasg, nome))

    # Busca geral federal via PNCP
    todas.extend(buscar_por_municipio_pncp_federal())

    output_file = OUTPUT_DIR / "licitacoes_federal.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(todas, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Total Federal: {len(todas)} licitações em {output_file}")


if __name__ == "__main__":
    main()
