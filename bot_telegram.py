"""
bot_telegram.py
Bot do Telegram que envia alertas de licitações com bom score.
Também responde comandos para consultar oportunidades.

Dependências: pip install python-telegram-bot anthropic
Obter token: fale com @BotFather no Telegram
"""

import os
import json
import asyncio
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters,
)
from database import (
    init_db, buscar_licitacoes, buscar_por_id,
    buscar_analise, estatisticas, registrar_alerta, marcar_alerta_enviado,
)

log = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "SEU_TOKEN_AQUI")
CHAT_IDS_AUTORIZADOS = set(
    os.getenv("TELEGRAM_CHAT_IDS", "").split(",")
)  # IDs separados por vírgula no .env
SCORE_MINIMO_ALERTA = int(os.getenv("SCORE_MINIMO_ALERTA", "65"))


# ── Formatação de mensagens ──────────────────────────────────────────────────

EMOJI_REC = {
    "PARTICIPAR": "🟢",
    "VERIFICAR": "🟡",
    "NÃO PARTICIPAR": "🔴",
    "ERRO": "⚫",
}

def formatar_resumo(lic: dict, analise: dict = None) -> str:
    valor = lic.get("valor_estimado") or 0
    valor_str = f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    enc = lic.get("data_encerramento") or "N/D"
    if enc and "T" in enc:
        enc = enc.split("T")[0]

    msg = (
        f"📋 *{lic['objeto'][:120]}{'...' if len(lic['objeto']) > 120 else ''}*\n\n"
        f"🏛 {lic['orgao_nome']} — {lic['orgao_uf']}\n"
        f"📌 Modalidade: {lic['modalidade']}\n"
        f"💰 Valor estimado: {valor_str}\n"
        f"📅 Encerramento: {enc}\n"
    )

    if analise:
        rec = analise.get("recomendacao", "?")
        emoji = EMOJI_REC.get(rec, "⚪")
        msg += (
            f"\n{emoji} *Recomendação: {rec}*\n"
            f"📊 Score: {analise.get('score', 0)}/100\n"
            f"💡 {analise.get('justificativa_recomendacao', '')}\n"
        )

    if lic.get("link_pncp"):
        msg += f"\n🔗 [Ver no PNCP]({lic['link_pncp']})"

    return msg


def formatar_detalhes(lic: dict, analise: dict) -> str:
    msg = formatar_resumo(lic, analise)

    if analise:
        requisitos = analise.get("requisitos", [])
        if isinstance(requisitos, str):
            try:
                requisitos = json.loads(requisitos)
            except Exception:
                requisitos = [requisitos]

        riscos = analise.get("riscos", [])
        if isinstance(riscos, str):
            try:
                riscos = json.loads(riscos)
            except Exception:
                riscos = [riscos]

        if requisitos:
            msg += "\n\n*📝 Requisitos críticos:*\n"
            for r in requisitos[:5]:
                msg += f"• {r}\n"

        if riscos:
            msg += "\n*⚠️ Riscos:*\n"
            for r in riscos[:3]:
                msg += f"• {r}\n"

        proximos = analise.get("proximos_passos", [])
        if isinstance(proximos, str):
            try:
                proximos = json.loads(proximos)
            except Exception:
                proximos = []

        if proximos:
            msg += "\n*🚀 Próximos passos:*\n"
            for p in proximos[:3]:
                msg += f"• {p}\n"

    return msg


# ── Verificação de autorização ───────────────────────────────────────────────

def autorizado(update: Update) -> bool:
    chat_id = str(update.effective_chat.id)
    if not CHAT_IDS_AUTORIZADOS or "" in CHAT_IDS_AUTORIZADOS:
        return True  # sem restrição se variável vazia
    return chat_id in CHAT_IDS_AUTORIZADOS


# ── Handlers de comandos ─────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not autorizado(update):
        return
    await update.message.reply_text(
        "🤖 *Bot de Licitações Públicas*\n\n"
        "Monitoro o PNCP e analiso licitações com IA para encontrar oportunidades.\n\n"
        "*Comandos disponíveis:*\n"
        "/oportunidades — Melhores oportunidades do momento\n"
        "/recentes — Licitações recentes coletadas\n"
        "/buscar [termo] — Busca por palavra-chave\n"
        "/stats — Estatísticas gerais\n"
        "/ajuda — Ajuda",
        parse_mode="Markdown",
    )


async def cmd_oportunidades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not autorizado(update):
        return

    await update.message.reply_text("🔍 Buscando melhores oportunidades...")

    lics = buscar_licitacoes(score_minimo=SCORE_MINIMO_ALERTA, limit=5)

    if not lics:
        await update.message.reply_text(
            "Nenhuma oportunidade com score alto encontrada ainda.\n"
            "Execute o coletor e analisador para atualizar."
        )
        return

    for lic in lics:
        analise = buscar_analise(lic["id"])
        msg = formatar_resumo(lic, analise)

        teclado = InlineKeyboardMarkup([[
            InlineKeyboardButton("📄 Ver detalhes", callback_data=f"detalhes_{lic['id']}"),
        ]])
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=teclado)


async def cmd_recentes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not autorizado(update):
        return

    lics = buscar_licitacoes(limit=5)

    if not lics:
        await update.message.reply_text("Nenhuma licitação no banco ainda.")
        return

    for lic in lics:
        analise = buscar_analise(lic["id"])
        msg = formatar_resumo(lic, analise)
        teclado = InlineKeyboardMarkup([[
            InlineKeyboardButton("📄 Ver detalhes", callback_data=f"detalhes_{lic['id']}"),
        ]])
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=teclado)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not autorizado(update):
        return

    stats = estatisticas()
    valor = stats["valor_total_estimado"]
    valor_str = f"R$ {valor:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")

    por_uf = "\n".join(
        f"  {r['orgao_uf']}: {r['qtd']}"
        for r in stats["por_uf"][:5]
    )

    await update.message.reply_text(
        f"📊 *Estatísticas do Bot*\n\n"
        f"🗂 Total de licitações: {stats['total_licitacoes']}\n"
        f"🤖 Analisadas pela IA: {stats['analisadas']}\n"
        f"🟢 Oportunidades (score ≥ 70): {stats['oportunidades_score_alto']}\n"
        f"💰 Valor total monitorado: {valor_str}\n\n"
        f"*Top estados:*\n{por_uf}",
        parse_mode="Markdown",
    )


async def cmd_ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Como funciona o bot:*\n\n"
        "1️⃣ A cada hora, o bot coleta novas licitações do PNCP\n"
        "2️⃣ Filtra por palavras-chave relevantes para sua empresa\n"
        "3️⃣ A IA (Claude) analisa cada edital e dá um score de 0 a 100\n"
        "4️⃣ Licitações com score alto geram alertas automáticos aqui\n\n"
        "*Configuração:*\n"
        "Edite `PERFIL_EMPRESA` em `analisador_ia.py` para personalizar\n"
        "Edite `FILTROS` em `coletor_pncp.py` para ajustar palavras-chave",
        parse_mode="Markdown",
    )


# ── Callback de botões inline ────────────────────────────────────────────────

async def callback_detalhes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    licitacao_id = int(query.data.split("_")[1])
    lic = buscar_por_id(licitacao_id)
    if not lic:
        await query.edit_message_text("Licitação não encontrada.")
        return

    analise = buscar_analise(licitacao_id)
    msg = formatar_detalhes(lic, analise or {})

    # Telegram tem limite de 4096 chars por mensagem
    if len(msg) > 4000:
        msg = msg[:3990] + "...\n\n_(mensagem truncada)_"

    await query.edit_message_text(msg, parse_mode="Markdown")


# ── Envio de alertas proativo ────────────────────────────────────────────────

async def enviar_alertas(app: Application, oportunidades: list, chat_id: str):
    """Envia alertas das melhores oportunidades para o chat."""
    for item in oportunidades:
        lic = item
        analise = item.get("analise", {})
        msg = (
            "🚨 *NOVA OPORTUNIDADE DETECTADA!*\n\n"
            + formatar_resumo(lic, analise)
        )
        teclado = InlineKeyboardMarkup([[
            InlineKeyboardButton("📄 Ver detalhes", callback_data=f"detalhes_{lic['id']}"),
        ]])
        try:
            await app.bot.send_message(
                chat_id=chat_id,
                text=msg,
                parse_mode="Markdown",
                reply_markup=teclado,
            )
        except Exception as e:
            log.error(f"Erro ao enviar alerta: {e}")


# ── Inicialização do bot ─────────────────────────────────────────────────────

def iniciar_bot():
    init_db()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("oportunidades", cmd_oportunidades))
    app.add_handler(CommandHandler("recentes", cmd_recentes))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("ajuda", cmd_ajuda))
    app.add_handler(CallbackQueryHandler(callback_detalhes, pattern=r"^detalhes_\d+$"))

    print(f"🤖 Bot iniciado! Token: {TOKEN[:10]}...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    iniciar_bot()
