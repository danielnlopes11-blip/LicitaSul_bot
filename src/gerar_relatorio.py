"""
Gera relatório HTML, mensagem para o Telegram e resumo para Issue do GitHub.
"""

import json
from datetime import datetime
from pathlib import Path

DATA_FILE = Path("data/licitacoes_consolidadas.json")
REPORTS_DIR = Path("reports")
REPORTS_DIR.mkdir(exist_ok=True)

MAX_ITENS_TELEGRAM = 15   # máximo de licitações no corpo da mensagem
MAX_CHAR_TELEGRAM  = 4000  # limite seguro da API Telegram (4096)


def carregar_dados() -> list[dict]:
    if not DATA_FILE.exists():
        return []
    with open(DATA_FILE, encoding="utf-8") as f:
        return json.load(f)


def formatar_valor(v) -> str:
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "—"


# ─── HTML ─────────────────────────────────────────────────────────────────────

def gerar_html(licitacoes: list[dict]) -> str:
    hoje = datetime.now().strftime("%d/%m/%Y %H:%M")
    total = len(licitacoes)
    urgentes = [l for l in licitacoes if "URGENTE" in l.get("_prioridade", "")]

    linhas = ""
    for l in licitacoes:
        prio = l.get("_prioridade", "")
        cor = {"🔴": "#fee2e2", "🟡": "#fef9c3", "🟢": "#dcfce7", "⚪": "#f9fafb"}.get(prio[:2], "#f9fafb")
        valor = formatar_valor(l.get("valor_estimado", 0))
        link = l.get("link", "#")
        dias = l.get("dias_ate_encerramento")
        dias_txt = f"{dias} dias" if isinstance(dias, int) and dias >= 0 else ("Encerrado" if isinstance(dias, int) else "—")
        objeto = (l.get("objeto") or "")
        linhas += f"""
        <tr style="background:{cor}">
          <td>{prio}</td>
          <td><strong>{l.get('municipio','')}</strong></td>
          <td>{l.get('orgao','')[:50]}</td>
          <td>{l.get('modalidade','')}</td>
          <td title="{objeto}">{objeto[:80]}{'…' if len(objeto)>80 else ''}</td>
          <td style="white-space:nowrap">{valor}</td>
          <td style="white-space:nowrap">{l.get('data_encerramento','')[:10]}</td>
          <td style="white-space:nowrap">{dias_txt}</td>
          <td><a href="{link}" target="_blank">Ver →</a></td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Licitações Içara/Criciúma — {hoje}</title>
<style>
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:0;padding:20px;background:#f0f4f8;color:#1a202c}}
  h1{{color:#2d3748;border-bottom:3px solid #4299e1;padding-bottom:10px}}
  .stats{{display:flex;gap:16px;flex-wrap:wrap;margin:20px 0}}
  .card{{background:white;border-radius:12px;padding:16px 24px;box-shadow:0 2px 8px rgba(0,0,0,.08);min-width:140px;text-align:center}}
  .card .num{{font-size:2rem;font-weight:700;color:#3182ce}}
  .card .lab{{font-size:.85rem;color:#718096;margin-top:4px}}
  .container{{background:white;border-radius:12px;padding:24px;box-shadow:0 2px 8px rgba(0,0,0,.08);margin-top:20px;overflow-x:auto}}
  table{{border-collapse:collapse;width:100%;font-size:.875rem}}
  th{{background:#2d3748;color:white;padding:10px 12px;text-align:left;position:sticky;top:0}}
  td{{padding:8px 12px;border-bottom:1px solid #e2e8f0;vertical-align:top}}
  tr:hover td{{filter:brightness(.96)}}
  a{{color:#3182ce;text-decoration:none}}
  a:hover{{text-decoration:underline}}
  .legend{{margin-top:12px;font-size:.8rem;color:#718096}}
  footer{{margin-top:30px;text-align:center;color:#a0aec0;font-size:.8rem}}
</style>
</head>
<body>
<h1>📋 Licitações de Serviços — Içara/Criciúma e Região</h1>
<p>Gerado em: <strong>{hoje}</strong> | Fontes: PNCP · Portal SC · TCE-SC · Prefeituras</p>
<div class="stats">
  <div class="card"><div class="num">{total}</div><div class="lab">Total encontradas</div></div>
  <div class="card"><div class="num" style="color:#e53e3e">{len(urgentes)}</div><div class="lab">Urgentes (≤2 dias)</div></div>
  <div class="card"><div class="num">{len([l for l in licitacoes if isinstance(l.get('dias_ate_encerramento'),int) and 0<l['dias_ate_encerramento']<=7])}</div><div class="lab">Esta semana</div></div>
</div>
<div class="container">
  <table>
    <thead><tr>
      <th>Prioridade</th><th>Município</th><th>Órgão</th><th>Modalidade</th>
      <th>Objeto</th><th>Valor Est.</th><th>Encerramento</th><th>Dias</th><th>Link</th>
    </tr></thead>
    <tbody>
      {linhas if linhas else '<tr><td colspan="9" style="text-align:center;padding:40px;color:#a0aec0">Nenhuma licitação encontrada no período.</td></tr>'}
    </tbody>
  </table>
  <div class="legend">🔴 URGENTE ≤2 dias &nbsp;|&nbsp; 🟡 Esta semana ≤7 dias &nbsp;|&nbsp; 🟢 Este mês ≤30 dias</div>
</div>
<footer>Agente de licitações automático | GitHub Actions |
  <a href="https://pncp.gov.br">PNCP</a> ·
  <a href="https://portaldecompras.sc.gov.br">Portal SC</a> ·
  <a href="https://e-sfinge.tce.sc.gov.br">TCE-SC</a>
</footer>
</body></html>"""


# ─── Telegram ─────────────────────────────────────────────────────────────────

def gerar_telegram(licitacoes: list[dict]) -> str:
    hoje = datetime.now().strftime("%d/%m/%Y")
    dia_semana = datetime.now().strftime("%A")
    dias_pt = {
        "Monday": "Segunda-feira", "Tuesday": "Terça-feira",
        "Wednesday": "Quarta-feira", "Thursday": "Quinta-feira",
        "Friday": "Sexta-feira", "Saturday": "Sábado", "Sunday": "Domingo",
    }
    dia_pt = dias_pt.get(dia_semana, dia_semana)

    total = len(licitacoes)
    urgentes  = [l for l in licitacoes if "URGENTE" in l.get("_prioridade", "")]
    semana    = [l for l in licitacoes if "semana"  in l.get("_prioridade", "").lower()]
    mes       = [l for l in licitacoes if "mês"     in l.get("_prioridade", "").lower()
                                       or "Este m"  in l.get("_prioridade", "")]

    linhas = []
    linhas.append(f"📋 <b>Licitações — {dia_pt}, {hoje}</b>")
    linhas.append(f"📍 Içara · Criciúma e região | SC")
    linhas.append("")
    linhas.append(f"🔢 <b>Total:</b> {total} licitações de serviços")
    linhas.append(f"🔴 Urgentes (≤2 dias): <b>{len(urgentes)}</b>")
    linhas.append(f"🟡 Esta semana:         <b>{len(semana)}</b>")
    linhas.append(f"🟢 Este mês:            <b>{len(mes)}</b>")

    def bloco(titulo: str, lista: list[dict], limite: int = 5) -> list[str]:
        if not lista:
            return []
        block = ["", f"<b>{titulo}</b>"]
        for l in lista[:limite]:
            objeto = (l.get("objeto") or "Sem descrição")[:70]
            orgao  = (l.get("orgao")  or "")[:35]
            mun    = l.get("municipio", "")
            link   = l.get("link", "")
            dias   = l.get("dias_ate_encerramento")
            dias_txt = f" · {dias}d restantes" if isinstance(dias, int) and dias >= 0 else ""
            valor  = formatar_valor(l.get("valor_estimado", 0))

            entrada = (
                f"\n• <b>{mun}</b> | {orgao}\n"
                f"  {objeto}\n"
                f"  💰 {valor}{dias_txt}"
            )
            if link:
                entrada += f'\n  🔗 <a href="{link}">Ver edital</a>'
            block.append(entrada)
        if len(lista) > limite:
            block.append(f"\n  <i>...e mais {len(lista)-limite} nesta categoria</i>")
        return block

    linhas += bloco("🔴 URGENTES — encerram em até 2 dias", urgentes, 5)
    linhas += bloco("🟡 ESTA SEMANA", semana, 5)
    linhas += bloco("🟢 ESTE MÊS (próximas)", mes, 5)

    linhas.append("")
    linhas.append("─────────────────────────")
    linhas.append("📂 Planilha CSV completa em anexo")
    linhas.append(f"🤖 Fontes: PNCP · Portal SC · TCE-SC · Prefeituras")

    msg = "\n".join(linhas)

    # Trunca se necessário para não estourar o limite do Telegram
    if len(msg) > MAX_CHAR_TELEGRAM:
        msg = msg[:MAX_CHAR_TELEGRAM - 100] + "\n\n<i>...mensagem truncada. Veja a planilha CSV completa.</i>"

    return msg


# ─── Issue GitHub ──────────────────────────────────────────────────────────────

def gerar_issue_md(licitacoes: list[dict]) -> str:
    hoje = datetime.now().strftime("%d/%m/%Y")
    urgentes = [l for l in licitacoes if "URGENTE" in l.get("_prioridade", "")]
    semana   = [l for l in licitacoes if "semana"  in l.get("_prioridade", "").lower()]

    linhas = [
        f"## 📋 Licitações de Serviços — {hoje}",
        f"**Total:** {len(licitacoes)} | **🔴 Urgentes:** {len(urgentes)} | **🟡 Esta semana:** {len(semana)}",
        "",
        "---",
    ]

    for titulo, lista, limite in [
        ("🔴 URGENTES — Encerram em até 2 dias", urgentes, 10),
        ("🟡 Esta semana", semana, 15),
    ]:
        if lista:
            linhas.append(f"\n### {titulo}\n")
            for l in lista[:limite]:
                linhas.append(
                    f"- **{l.get('municipio')}** | {l.get('orgao','')[:40]} | "
                    f"{(l.get('objeto') or '')[:60]} | "
                    f"[Ver edital]({l.get('link','#')})"
                )

    linhas += [
        "",
        "---",
        "*Gerado automaticamente pelo [Agente de Licitações](../actions)*",
        f"*Fontes: PNCP · Portal SC · TCE-SC · Prefeituras | {hoje}*",
    ]
    return "\n".join(linhas)


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("📄 Gerando relatórios")
    print("=" * 60)

    licitacoes = carregar_dados()
    print(f"  {len(licitacoes)} licitações carregadas")

    # HTML
    html = gerar_html(licitacoes)
    (REPORTS_DIR / "relatorio.html").write_text(html, encoding="utf-8")
    print("  ✅ relatorio.html")

    # Telegram
    tg = gerar_telegram(licitacoes)
    (REPORTS_DIR / "telegram_resumo.txt").write_text(tg, encoding="utf-8")
    print("  ✅ telegram_resumo.txt")
    print(f"     {len(tg)} caracteres")

    # Issue MD (só cria se houver licitações)
    if licitacoes:
        md = gerar_issue_md(licitacoes)
        (REPORTS_DIR / "resumo_issue.md").write_text(md, encoding="utf-8")
        print("  ✅ resumo_issue.md")
    else:
        print("  ℹ️  Sem licitações, Issue não será criado")


if __name__ == "__main__":
    main()
