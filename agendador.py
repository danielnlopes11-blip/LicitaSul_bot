"""
agendador.py
Orquestra a coleta, análise e envio de alertas em ciclos automáticos.
Também expõe uma API REST simples via FastAPI para o dashboard.

Uso:
    python agendador.py              # roda coleta + análise uma vez
    python agendador.py --daemon     # roda em loop contínuo
    uvicorn agendador:api --reload   # só a API REST
"""

import os
import asyncio
import logging
import argparse
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from database import init_db, buscar_licitacoes, buscar_por_id, buscar_analise, estatisticas
from coletor_pncp import coletar_periodo, FILTROS
from analisador_ia import analisar_pendentes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────────────────────────

INTERVALO_COLETA_HORAS = int(os.getenv("INTERVALO_COLETA_HORAS", "4"))
SCORE_MINIMO_ALERTA = int(os.getenv("SCORE_MINIMO_ALERTA", "65"))
TELEGRAM_CHAT_IDS = os.getenv("TELEGRAM_CHAT_IDS", "").split(",")


# ── Ciclo principal ──────────────────────────────────────────────────────────

async def ciclo_completo():
    """Coleta + Analisa + Alerta. Retorna oportunidades encontradas."""
    log.info("=" * 60)
    log.info(f"🚀 Iniciando ciclo: {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    # 1. Coleta
    novas = await coletar_periodo(
        dias_atras=1,
        estados=FILTROS["estados"] or None,
    )
    log.info(f"📥 {len(novas)} novas licitações coletadas.")

    # 2. Análise IA
    oportunidades = await analisar_pendentes(
        score_minimo_alerta=SCORE_MINIMO_ALERTA,
        max_por_ciclo=30,
    )
    log.info(f"🤖 {len(oportunidades)} oportunidades com score >= {SCORE_MINIMO_ALERTA}.")

    # 3. Alertas Telegram (opcional)
    if oportunidades and TELEGRAM_CHAT_IDS and TELEGRAM_CHAT_IDS[0]:
        try:
            from telegram import Bot
            bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN", ""))
            for chat_id in TELEGRAM_CHAT_IDS:
                if not chat_id.strip():
                    continue
                for item in oportunidades[:5]:  # max 5 por ciclo
                    analise = item.get("analise", {})
                    rec = analise.get("recomendacao", "?")
                    score = analise.get("score", 0)
                    objeto = item["objeto"][:100]
                    valor = item.get("valor_estimado", 0)
                    msg = (
                        f"🚨 *Nova oportunidade!* (score {score}/100)\n\n"
                        f"📋 {objeto}\n"
                        f"💰 R$ {valor:,.0f}\n"
                        f"✅ Recomendação: {rec}"
                    )
                    await bot.send_message(chat_id=chat_id.strip(), text=msg, parse_mode="Markdown")
        except Exception as e:
            log.warning(f"Erro ao enviar alertas Telegram: {e}")

    log.info(f"✅ Ciclo concluído. Próximo em {INTERVALO_COLETA_HORAS}h.")
    return oportunidades


async def daemon():
    """Roda ciclos indefinidamente."""
    init_db()
    while True:
        try:
            await ciclo_completo()
        except Exception as e:
            log.error(f"Erro no ciclo: {e}", exc_info=True)
        await asyncio.sleep(INTERVALO_COLETA_HORAS * 3600)


# ── API REST (FastAPI) ────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


api = FastAPI(
    title="Bot Licitações API",
    description="API do analisador de licitações públicas",
    version="1.0.0",
    lifespan=lifespan,
)

api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@api.get("/licitacoes")
def listar_licitacoes(
    score_minimo: int = Query(0, ge=0, le=100),
    uf: str = Query(None),
    sem_analise: bool = Query(False),
    limit: int = Query(20, le=100),
    offset: int = Query(0),
):
    return buscar_licitacoes(
        score_minimo=score_minimo,
        uf=uf,
        sem_analise=sem_analise,
        limit=limit,
        offset=offset,
    )


@api.get("/licitacoes/{licitacao_id}")
def detalhe_licitacao(licitacao_id: int):
    lic = buscar_por_id(licitacao_id)
    if not lic:
        raise HTTPException(404, "Licitação não encontrada")
    analise = buscar_analise(licitacao_id)
    return {"licitacao": lic, "analise": analise}


@api.get("/stats")
def get_stats():
    return estatisticas()


@api.post("/ciclo")
async def executar_ciclo():
    """Dispara um ciclo de coleta+análise manualmente."""
    oportunidades = await ciclo_completo()
    return {"oportunidades_encontradas": len(oportunidades)}


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bot Analisador de Licitações")
    parser.add_argument("--daemon", action="store_true", help="Roda em modo contínuo")
    parser.add_argument("--api", action="store_true", help="Sobe a API REST")
    args = parser.parse_args()

    if args.api:
        import uvicorn
        uvicorn.run("agendador:api", host="0.0.0.0", port=8000, reload=True)
    elif args.daemon:
        asyncio.run(daemon())
    else:
        init_db()
        asyncio.run(ciclo_completo())
