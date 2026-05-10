"""
agendador.py
Orquestra coleta + analise + alertas.
Imports dos modulos locais feitos dentro das funcoes para evitar circular import.
"""

import os
import asyncio
import logging
import argparse
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

SCORE_MINIMO_ALERTA    = int(os.getenv("SCORE_MINIMO_ALERTA", "65"))
INTERVALO_COLETA_HORAS = int(os.getenv("INTERVALO_COLETA_HORAS", "4"))
TELEGRAM_CHAT_IDS      = [c for c in os.getenv("TELEGRAM_CHAT_IDS", "").split(",") if c.strip()]


# ── Ciclo principal ───────────────────────────────────────────────────────────

async def ciclo_completo():
    # Imports locais para evitar circular import
    from database import init_db
    from coletor_pncp import coletar_periodo, coletar_abertas
    from analisador_ia import analisar_pendentes
    from datetime import datetime

    init_db()

    log.info("=" * 60)
    log.info(f"Iniciando ciclo: {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    # 1. Coleta por data de publicacao
    novas = await coletar_periodo(dias_atras=2)

    # 2. Se nao achou nada, tenta licitacoes abertas agora
    if not novas:
        log.info("Tentando endpoint /proposta (licitacoes abertas agora)...")
        novas = await coletar_abertas()

    log.info(f"Total coletado: {len(novas)} novas licitacoes.")

    # 3. Analise com IA
    oportunidades = await analisar_pendentes(
        score_minimo_alerta=SCORE_MINIMO_ALERTA,
        max_por_ciclo=30,
    )
    log.info(f"Oportunidades com score >= {SCORE_MINIMO_ALERTA}: {len(oportunidades)}")

    # 4. Alertas Telegram
    if oportunidades and TELEGRAM_CHAT_IDS:
        try:
            from telegram import Bot
            bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN", ""))
            for chat_id in TELEGRAM_CHAT_IDS:
                for item in oportunidades[:5]:
                    analise = item.get("analise", {})
                    msg = (
                        f"Nova oportunidade! Score: {analise.get('score', 0)}/100\n\n"
                        f"{item['objeto'][:100]}\n"
                        f"Valor: R$ {item.get('valor_estimado', 0):,.0f}\n"
                        f"Recomendacao: {analise.get('recomendacao', '')}"
                    )
                    await bot.send_message(chat_id=chat_id.strip(), text=msg)
        except Exception as e:
            log.warning(f"Erro ao enviar Telegram: {e}")

    log.info(f"Ciclo concluido. Proximo em {INTERVALO_COLETA_HORAS}h.")
    return oportunidades


async def daemon():
    while True:
        try:
            await ciclo_completo()
        except Exception as e:
            log.error(f"Erro no ciclo: {e}", exc_info=True)
        await asyncio.sleep(INTERVALO_COLETA_HORAS * 3600)


# ── API REST ──────────────────────────────────────────────────────────────────

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

@asynccontextmanager
async def lifespan(app: FastAPI):
    from database import init_db
    init_db()
    yield

api = FastAPI(title="LicitaBot API", version="1.0.0", lifespan=lifespan)
api.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@api.get("/licitacoes")
def listar(
    score_minimo: int = Query(0),
    uf: str = Query(None),
    sem_analise: bool = Query(False),
    limit: int = Query(20),
    offset: int = Query(0),
):
    from database import buscar_licitacoes
    return buscar_licitacoes(
        score_minimo=score_minimo, uf=uf,
        sem_analise=sem_analise, limit=limit, offset=offset,
    )

@api.get("/licitacoes/{lid}")
def detalhe(lid: int):
    from database import buscar_por_id, buscar_analise
    lic = buscar_por_id(lid)
    if not lic:
        raise HTTPException(404, "Nao encontrada")
    return {"licitacao": lic, "analise": buscar_analise(lid)}

@api.get("/stats")
def stats():
    from database import estatisticas
    return estatisticas()

@api.post("/ciclo")
async def ciclo_manual():
    ops = await ciclo_completo()
    return {"oportunidades": len(ops)}


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--api",    action="store_true")
    args = parser.parse_args()

    if args.api:
        import uvicorn
        uvicorn.run("agendador:api", host="0.0.0.0", port=int(os.getenv("API_PORT", 8000)))
    elif args.daemon:
        asyncio.run(daemon())
    else:
        asyncio.run(ciclo_completo())
