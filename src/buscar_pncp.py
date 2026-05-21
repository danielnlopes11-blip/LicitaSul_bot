"""
Busca licitações no PNCP - Portal Nacional de Contratações Públicas
API oficial: https://pncp.gov.br/api/pncp/v1/
"""

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

# ─── Configuração de municípios ───────────────────────────────────────────────
MUNICIPIOS = [
    {"nome": "Içara",    "codigo_ibge": "4207007", "uf": "SC"},
    {"nome": "Criciúma", "codigo_ibge": "4204608", "uf": "SC"},
    {"nome": "Morro da Fumaça",  "codigo_ibge": "4211603", "uf": "SC"},
    {"nome": "Cocal do Sul",     "codigo_ibge": "4203956", "uf": "SC"},
    {"nome": "Urussanga",        "codigo_ibge": "4219507", "uf": "SC"},
    {"nome": "Forquilhinha",     "codigo_ibge": "4205704", "uf": "SC"},
    {"nome": "Siderópolis",      "codigo_ibge": "4217709", "uf": "SC"},
    {"nome": "Nova Veneza",      "codigo_ibge": "4211603", "uf": "SC"},
]

PALAVRAS_CHAVE_SERVICO = [
    "serviço", "manutenção", "consultoria", "limpeza", "vigilância",
    "segurança", "transporte", "tecnologia", "TI", "software",
    "engenharia", "obra", "construção", "reforma", "pavimentação",
    "coleta", "resíduos", "saúde", "médico", "enfermagem",
    "capacitação", "treinamento", "assessoria",
]

BASE_URL = "https://pncp.gov.br/api/pncp/v1"
DIAS_RETROATIVOS = int(os.getenv("DIAS_RETROATIVOS", "7"))
OUTPUT_DIR = Path("data")
OUTPUT_DIR.mkdir(exist_ok=True)


def buscar_contratacoes_municipio(codigo_ibge: str, nome: str) -> list[dict]:
    """Busca contratações abertas de um município via PNCP."""
    licitacoes = []
    data_inicio = (datetime.now() - timedelta(days=DIAS_RETROATIVOS)).strftime("%Y%m%d")
    data_fim = datetime.now().strftime("%Y%m%d")
    pagina = 1

    print(f"  🔍 Buscando em {nome} (IBGE: {codigo_ibge})...")

    while True:
        params = {
            "codigoMunicipioIbge": codigo_ibge,
            "dataInicial": data_inicio,
            "dataFinal": data_fim,
            "pagina": pagina,
            "tamanhoPagina": 50,
        }
        try:
            resp = requests.get(
                f"{BASE_URL}/contratacoes/publicacoes",
                params=params,
                timeout=30,
                headers={"Accept": "application/json"},
            )
            if resp.status_code == 404:
                break
            resp.raise_for_status()
            dados = resp.json()

            items = dados.get("data", [])
            if not items:
                break

            for item in items:
                item["_fonte"] = "PNCP"
                item["_municipio_busca"] = nome
                licitacoes.append(item)

            total_paginas = dados.get("totalPaginas", 1)
            if pagina >= total_paginas:
                break
            pagina += 1
            time.sleep(0.5)  # respeita rate limit

        except requests.exceptions.RequestException as e:
            print(f"    ⚠️  Erro ao buscar {nome}: {e}")
            break

    print(f"    ✅ {len(licitacoes)} licitações encontradas em {nome}")
    return licitacoes


def filtrar_servicos(licitacoes: list[dict]) -> list[dict]:
    """Filtra licitações que têm relação com serviços."""
    filtradas = []
    for lic in licitacoes:
        objeto = (lic.get("objetoCompra", "") or "").lower()
        modalidade = (lic.get("modalidadeNome", "") or "").lower()
        texto_busca = objeto + " " + modalidade

        if any(kw.lower() in texto_busca for kw in PALAVRAS_CHAVE_SERVICO):
            filtradas.append(lic)
        # Inclui também pregões eletrônicos (geralmente serviços)
        elif "pregão" in modalidade or "concorrência" in modalidade:
            filtradas.append(lic)

    return filtradas


def formatar_licitacao(raw: dict) -> dict:
    """Normaliza campos para formato padrão."""
    return {
        "id": raw.get("numeroControlePNCP", ""),
        "fonte": "PNCP",
        "municipio": raw.get("unidadeOrgao", {}).get("municipioNome", raw.get("_municipio_busca", "")),
        "uf": "SC",
        "orgao": raw.get("unidadeOrgao", {}).get("nomeUnidade", ""),
        "cnpj": raw.get("unidadeOrgao", {}).get("cnpj", ""),
        "modalidade": raw.get("modalidadeNome", ""),
        "objeto": raw.get("objetoCompra", ""),
        "valor_estimado": raw.get("valorTotalEstimado", 0),
        "data_publicacao": raw.get("dataPublicacaoPncp", ""),
        "data_encerramento": raw.get("dataEncerramentoProposta", ""),
        "situacao": raw.get("situacaoCompraNome", ""),
        "link": f"https://pncp.gov.br/app/editais/{raw.get('numeroControlePNCP', '')}",
        "numero_processo": raw.get("processo", ""),
    }


def main():
    print("=" * 60)
    print("🔍 PNCP - Portal Nacional de Contratações Públicas")
    print(f"   Período: últimos {DIAS_RETROATIVOS} dias")
    print("=" * 60)

    todas = []
    for mun in MUNICIPIOS:
        raw = buscar_contratacoes_municipio(mun["codigo_ibge"], mun["nome"])
        filtradas = filtrar_servicos(raw)
        formatadas = [formatar_licitacao(r) for r in filtradas]
        todas.extend(formatadas)
        time.sleep(1)

    # Deduplica por ID
    vistas = set()
    unicas = []
    for lic in todas:
        if lic["id"] not in vistas:
            vistas.add(lic["id"])
            unicas.append(lic)

    output_file = OUTPUT_DIR / "licitacoes_pncp.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(unicas, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Total PNCP: {len(unicas)} licitações salvas em {output_file}")


if __name__ == "__main__":
    main()
