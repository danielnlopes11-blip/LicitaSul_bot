"""
Busca licitações no Portal de Compras de Santa Catarina
https://www.portaldecompras.sc.gov.br/
e também via scraping do TCE-SC (Tribunal de Contas de SC)
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

OUTPUT_DIR = Path("data")
OUTPUT_DIR.mkdir(exist_ok=True)

MUNICIPIOS_SC = [
    "Içara", "Criciúma", "Morro da Fumaça", "Cocal do Sul",
    "Urussanga", "Forquilhinha", "Siderópolis", "Nova Veneza",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html",
}

# ─── Portal de Compras SC ─────────────────────────────────────────────────────

def buscar_portal_sc() -> list[dict]:
    """Busca via API do Portal de Compras SC."""
    licitacoes = []
    base = "https://www.portaldecompras.sc.gov.br/api/licitacoes"
    data_inicio = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    for municipio in MUNICIPIOS_SC:
        print(f"  🔍 Portal SC - {municipio}...")
        try:
            params = {
                "municipio": municipio,
                "uf": "SC",
                "dataInicio": data_inicio,
                "tipo": "servico",
                "situacao": "aberta",
                "pagina": 1,
                "registros": 50,
            }
            resp = requests.get(base, params=params, headers=HEADERS, timeout=20)
            if resp.status_code == 200:
                dados = resp.json()
                items = dados.get("resultado", dados.get("licitacoes", []))
                for item in items:
                    licitacoes.append({
                        "id": f"SC-{item.get('id', '')}",
                        "fonte": "Portal SC",
                        "municipio": municipio,
                        "uf": "SC",
                        "orgao": item.get("orgao", item.get("entidade", "")),
                        "cnpj": item.get("cnpj", ""),
                        "modalidade": item.get("modalidade", ""),
                        "objeto": item.get("objeto", item.get("descricao", "")),
                        "valor_estimado": item.get("valor", 0),
                        "data_publicacao": item.get("dataPublicacao", ""),
                        "data_encerramento": item.get("dataEncerramento", ""),
                        "situacao": item.get("situacao", "Aberta"),
                        "link": item.get("link", item.get("url", "")),
                        "numero_processo": item.get("numeroProcesso", item.get("numero", "")),
                    })
        except Exception as e:
            print(f"    ⚠️  Erro Portal SC ({municipio}): {e}")
        time.sleep(0.5)

    return licitacoes


# ─── TCE-SC Consulta Pública ──────────────────────────────────────────────────

def buscar_tce_sc() -> list[dict]:
    """Busca licitações via TCE-SC sistema e-Sfinge."""
    licitacoes = []
    print("  🔍 TCE-SC (e-Sfinge)...")

    try:
        # API pública do TCE-SC para consulta de licitações
        url = "https://e-sfinge.tce.sc.gov.br/publico/licitacao/consultar"
        municipios_ibge = {
            "Içara": "4207007",
            "Criciúma": "4204608",
            "Morro da Fumaça": "4211603",
            "Cocal do Sul": "4203956",
            "Urussanga": "4219507",
            "Forquilhinha": "4205704",
        }

        for nome, codigo in municipios_ibge.items():
            try:
                params = {
                    "codigoMunicipio": codigo,
                    "exercicio": datetime.now().year,
                    "situacao": "A",  # Aberta
                }
                resp = requests.get(url, params=params, headers=HEADERS, timeout=20)
                if resp.status_code == 200:
                    try:
                        dados = resp.json()
                        for item in dados.get("licitacoes", []):
                            licitacoes.append({
                                "id": f"TCE-{codigo}-{item.get('numero', '')}",
                                "fonte": "TCE-SC",
                                "municipio": nome,
                                "uf": "SC",
                                "orgao": item.get("entidade", ""),
                                "cnpj": item.get("cnpj", ""),
                                "modalidade": item.get("modalidade", ""),
                                "objeto": item.get("objeto", ""),
                                "valor_estimado": item.get("valorEstimado", 0),
                                "data_publicacao": item.get("dataPublicacao", ""),
                                "data_encerramento": item.get("dataEncerramento", ""),
                                "situacao": "Aberta",
                                "link": f"https://e-sfinge.tce.sc.gov.br/publico/licitacao/{item.get('id', '')}",
                                "numero_processo": item.get("numero", ""),
                            })
                    except Exception:
                        pass  # resposta não é JSON, ignorar
            except Exception as e:
                print(f"    ⚠️  TCE-SC ({nome}): {e}")
            time.sleep(0.3)

    except Exception as e:
        print(f"  ⚠️  Erro geral TCE-SC: {e}")

    return licitacoes


# ─── Prefeituras diretamente ──────────────────────────────────────────────────

def buscar_prefeitura_icara() -> list[dict]:
    """Busca licitações diretamente no site da Prefeitura de Içara."""
    licitacoes = []
    print("  🔍 Prefeitura de Içara...")
    try:
        url = "https://www.icara.sc.gov.br/licitacoes"
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            # Estrutura genérica — adaptar conforme layout real do site
            for item in soup.select(".licitacao-item, .licitacao, article.licitacao"):
                titulo = item.select_one("h2, h3, .titulo")
                link_tag = item.select_one("a")
                data = item.select_one(".data, .data-publicacao")
                if titulo:
                    licitacoes.append({
                        "id": f"ICARA-{hash(titulo.get_text())}",
                        "fonte": "Prefeitura Içara",
                        "municipio": "Içara",
                        "uf": "SC",
                        "orgao": "Prefeitura Municipal de Içara",
                        "cnpj": "82.916.832/0001-08",
                        "modalidade": "",
                        "objeto": titulo.get_text(strip=True),
                        "valor_estimado": 0,
                        "data_publicacao": data.get_text(strip=True) if data else "",
                        "data_encerramento": "",
                        "situacao": "Aberta",
                        "link": link_tag["href"] if link_tag else url,
                        "numero_processo": "",
                    })
    except Exception as e:
        print(f"  ⚠️  Prefeitura Içara: {e}")

    print(f"    ✅ {len(licitacoes)} licitações em Içara (site prefeitura)")
    return licitacoes


def buscar_prefeitura_criciuma() -> list[dict]:
    """Busca licitações diretamente no site da Prefeitura de Criciúma."""
    licitacoes = []
    print("  🔍 Prefeitura de Criciúma...")
    try:
        url = "https://www.criciuma.sc.gov.br/site/licitacoes"
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for item in soup.select(".licitacao-item, table tr, .item-licitacao"):
                cols = item.select("td")
                if len(cols) >= 2:
                    licitacoes.append({
                        "id": f"CRICIUMA-{hash(cols[0].get_text())}",
                        "fonte": "Prefeitura Criciúma",
                        "municipio": "Criciúma",
                        "uf": "SC",
                        "orgao": "Prefeitura Municipal de Criciúma",
                        "cnpj": "82.916.077/0001-40",
                        "modalidade": cols[1].get_text(strip=True) if len(cols) > 1 else "",
                        "objeto": cols[0].get_text(strip=True),
                        "valor_estimado": 0,
                        "data_publicacao": cols[2].get_text(strip=True) if len(cols) > 2 else "",
                        "data_encerramento": cols[3].get_text(strip=True) if len(cols) > 3 else "",
                        "situacao": "Aberta",
                        "link": url,
                        "numero_processo": "",
                    })
    except Exception as e:
        print(f"  ⚠️  Prefeitura Criciúma: {e}")

    print(f"    ✅ {len(licitacoes)} licitações em Criciúma (site prefeitura)")
    return licitacoes


def main():
    print("=" * 60)
    print("🔍 Portal SC / TCE-SC / Prefeituras")
    print("=" * 60)

    todas = []
    todas.extend(buscar_portal_sc())
    todas.extend(buscar_tce_sc())
    todas.extend(buscar_prefeitura_icara())
    todas.extend(buscar_prefeitura_criciuma())

    output_file = OUTPUT_DIR / "licitacoes_sc.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(todas, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Total SC/Prefeituras: {len(todas)} licitações em {output_file}")


if __name__ == "__main__":
    main()
