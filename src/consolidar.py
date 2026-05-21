"""
Consolida todos os arquivos JSON de licitações, deduplica e filtra.
"""

import json
from datetime import datetime
from pathlib import Path

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

ARQUIVOS_FONTE = [
    DATA_DIR / "licitacoes_pncp.json",
    DATA_DIR / "licitacoes_sc.json",
    DATA_DIR / "licitacoes_federal.json",
]

MODALIDADES_SERVICO = [
    "pregão", "concorrência", "dispensa", "inexigibilidade",
    "chamamento", "credenciamento", "leilão", "convite",
]

PALAVRAS_EXCLUIR = [
    "aquisição de veículo", "compra de combustível",
    "material de escritório permanente", "equipamento hospitalar permanente",
]


def carregar_todos() -> list[dict]:
    todos = []
    for arq in ARQUIVOS_FONTE:
        if arq.exists():
            with open(arq, encoding="utf-8") as f:
                dados = json.load(f)
                todos.extend(dados)
                print(f"  📂 {arq.name}: {len(dados)} registros")
        else:
            print(f"  ⚠️  {arq.name} não encontrado")
    return todos


def deduplicar(licitacoes: list[dict]) -> list[dict]:
    vistas = set()
    unicas = []
    for lic in licitacoes:
        chave = lic.get("id", "")
        if not chave:
            # Gera chave por conteúdo
            chave = f"{lic.get('orgao','')}-{lic.get('objeto','')[:50]}"
        if chave not in vistas:
            vistas.add(chave)
            unicas.append(lic)
    return unicas


def filtrar_servicos(licitacoes: list[dict]) -> list[dict]:
    """Mantém apenas licitações de serviços (não compras de bens)."""
    resultado = []
    for lic in licitacoes:
        objeto = (lic.get("objeto") or "").lower()
        modalidade = (lic.get("modalidade") or "").lower()

        # Exclui palavras que indicam compra pura de material
        if any(excl in objeto for excl in PALAVRAS_EXCLUIR):
            continue

        # Mantém se modalidade for típica de serviços
        if any(m in modalidade for m in MODALIDADES_SERVICO):
            resultado.append(lic)
            continue

        # Mantém se objeto contém palavras de serviço
        palavras_servico = [
            "serviç", "manutenç", "conservaç", "limpez", "vigilânc",
            "seguranç", "transport", "tecnolog", "softwar", "sistem",
            "consult", "assessor", "capacit", "treinament", "reform",
            "construç", "paviment", "obra", "projeto", "estudos",
            "coleta", "destinaç", "resíduo", "saúde", "médic",
            "enferma", "hospita", "forneciment", "locaç",
        ]
        if any(p in objeto for p in palavras_servico):
            resultado.append(lic)

    return resultado


def enriquecer(licitacoes: list[dict]) -> list[dict]:
    """Adiciona campos calculados."""
    agora = datetime.now()
    for lic in licitacoes:
        # Calcula dias até encerramento
        enc = lic.get("data_encerramento", "")
        if enc:
            try:
                # Tenta vários formatos de data
                for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
                    try:
                        dt = datetime.strptime(enc[:len(fmt)], fmt)
                        lic["dias_ate_encerramento"] = (dt - agora).days
                        break
                    except ValueError:
                        continue
            except Exception:
                lic["dias_ate_encerramento"] = None
        else:
            lic["dias_ate_encerramento"] = None

        # Prioridade: licitações encerrando em breve
        dias = lic.get("dias_ate_encerramento")
        if dias is not None:
            if dias <= 2:
                lic["_prioridade"] = "🔴 URGENTE"
            elif dias <= 7:
                lic["_prioridade"] = "🟡 Esta semana"
            elif dias <= 30:
                lic["_prioridade"] = "🟢 Este mês"
            else:
                lic["_prioridade"] = "⚪ Futuro"
        else:
            lic["_prioridade"] = "⚪ Sem data"

    return licitacoes


def ordenar(licitacoes: list[dict]) -> list[dict]:
    def chave_ordem(l):
        dias = l.get("dias_ate_encerramento")
        if dias is None:
            return 9999
        return dias if dias >= 0 else 9998

    return sorted(licitacoes, key=chave_ordem)


def main():
    print("=" * 60)
    print("📊 Consolidando resultados")
    print("=" * 60)

    todos = carregar_todos()
    print(f"\n  Total bruto: {len(todos)}")

    unicos = deduplicar(todos)
    print(f"  Após deduplicar: {len(unicos)}")

    servicos = filtrar_servicos(unicos)
    print(f"  Após filtro serviços: {len(servicos)}")

    enriquecidos = enriquecer(servicos)
    ordenados = ordenar(enriquecidos)

    # Salva consolidado
    saida = DATA_DIR / "licitacoes_consolidadas.json"
    with open(saida, "w", encoding="utf-8") as f:
        json.dump(ordenados, f, ensure_ascii=False, indent=2)

    # Salva CSV simples
    import csv
    csv_saida = Path("reports") / "licitacoes.csv"
    csv_saida.parent.mkdir(exist_ok=True)
    campos = [
        "id", "fonte", "municipio", "orgao", "modalidade", "objeto",
        "valor_estimado", "data_publicacao", "data_encerramento",
        "situacao", "_prioridade", "link", "numero_processo",
    ]
    with open(csv_saida, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(ordenados)

    print(f"\n✅ {len(ordenados)} licitações consolidadas")
    print(f"   JSON: {saida}")
    print(f"   CSV:  {csv_saida}")

    # Estatísticas
    por_municipio = {}
    for l in ordenados:
        m = l.get("municipio", "Desconhecido")
        por_municipio[m] = por_municipio.get(m, 0) + 1

    print("\n📍 Por município:")
    for m, n in sorted(por_municipio.items(), key=lambda x: -x[1]):
        print(f"   {m}: {n}")

    urgentes = [l for l in ordenados if "URGENTE" in l.get("_prioridade", "")]
    print(f"\n🔴 Urgentes (encerram em ≤2 dias): {len(urgentes)}")


if __name__ == "__main__":
    main()
