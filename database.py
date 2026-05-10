"""
database.py
Camada de persistência usando SQLite (fácil de usar, sem servidor).
Para produção, substitua pela connection string do PostgreSQL no DATABASE_URL.
"""

import sqlite3
import json
import os
from datetime import datetime
from contextlib import contextmanager

DATABASE_PATH = os.getenv("DATABASE_PATH", "licitacoes.db")


# ── Conexão ─────────────────────────────────────────────────────────────────

@contextmanager
def get_conn():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Criação das tabelas ──────────────────────────────────────────────────────

def init_db():
    """Cria as tabelas se não existirem."""
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS licitacoes (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            id_externo          TEXT    UNIQUE,
            numero_compra       TEXT,
            ano                 INTEGER,
            objeto              TEXT,
            modalidade          TEXT,
            situacao            TEXT,
            valor_estimado      REAL,
            valor_homologado    REAL,
            data_publicacao     TEXT,
            data_encerramento   TEXT,
            orgao_nome          TEXT,
            orgao_cnpj          TEXT,
            orgao_uf            TEXT,
            orgao_municipio     TEXT,
            link_pncp           TEXT,
            itens               TEXT,   -- JSON
            documentos          TEXT,   -- JSON
            raw                 TEXT,   -- JSON completo
            criado_em           TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS analises (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            licitacao_id        INTEGER REFERENCES licitacoes(id),
            score               INTEGER,
            oportunidade        TEXT,
            requisitos          TEXT,   -- JSON
            documentos_exigidos TEXT,   -- JSON
            riscos              TEXT,   -- JSON
            recomendacao        TEXT,
            analise_completa    TEXT,   -- JSON completo retornado pela IA
            analisado_em        TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS alertas (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            licitacao_id        INTEGER REFERENCES licitacoes(id),
            canal               TEXT,   -- 'telegram' | 'email'
            destinatario        TEXT,
            enviado             INTEGER DEFAULT 0,
            enviado_em          TEXT,
            criado_em           TEXT    DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_licitacoes_uf   ON licitacoes(orgao_uf);
        CREATE INDEX IF NOT EXISTS idx_licitacoes_data ON licitacoes(data_publicacao);
        CREATE INDEX IF NOT EXISTS idx_analises_score  ON analises(score);
        """)
    print("✅ Banco de dados inicializado.")


# ── CRUD Licitações ──────────────────────────────────────────────────────────

def salvar_licitacoes(lista: list) -> int:
    """Insere licitações novas (ignora duplicatas). Retorna qtd inserida."""
    inseridas = 0
    with get_conn() as conn:
        for l in lista:
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO licitacoes
                    (id_externo, numero_compra, ano, objeto, modalidade, situacao,
                     valor_estimado, valor_homologado, data_publicacao, data_encerramento,
                     orgao_nome, orgao_cnpj, orgao_uf, orgao_municipio, link_pncp,
                     itens, documentos, raw)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    l["id_externo"], l["numero_compra"], l["ano"],
                    l["objeto"], l["modalidade"], l["situacao"],
                    l["valor_estimado"], l.get("valor_homologado"),
                    l.get("data_publicacao"), l.get("data_encerramento"),
                    l["orgao_nome"], l["orgao_cnpj"], l["orgao_uf"],
                    l["orgao_municipio"], l.get("link_pncp", ""),
                    json.dumps(l.get("itens", []), ensure_ascii=False),
                    json.dumps(l.get("documentos", []), ensure_ascii=False),
                    json.dumps(l.get("raw", {}), ensure_ascii=False),
                ))
                inseridas += 1
            except Exception as e:
                print(f"Erro ao salvar {l.get('id_externo')}: {e}")
    return inseridas


def licitacao_ja_existe(id_externo: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM licitacoes WHERE id_externo = ?", (id_externo,)
        ).fetchone()
        return row is not None


def buscar_licitacoes(
    score_minimo: int = 0,
    uf: str = None,
    sem_analise: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list:
    """Retorna licitações com filtros opcionais."""
    sql = """
        SELECT l.*, a.score, a.recomendacao
        FROM licitacoes l
        LEFT JOIN analises a ON a.licitacao_id = l.id
        WHERE 1=1
    """
    params = []
    if uf:
        sql += " AND l.orgao_uf = ?"
        params.append(uf)
    if score_minimo:
        sql += " AND (a.score IS NULL OR a.score >= ?)"
        params.append(score_minimo)
    if sem_analise:
        sql += " AND a.id IS NULL"
    sql += " ORDER BY l.data_publicacao DESC LIMIT ? OFFSET ?"
    params += [limit, offset]

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def buscar_por_id(licitacao_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM licitacoes WHERE id = ?", (licitacao_id,)
        ).fetchone()
        return dict(row) if row else None


# ── CRUD Análises ────────────────────────────────────────────────────────────

def salvar_analise(licitacao_id: int, analise: dict):
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO analises
            (licitacao_id, score, oportunidade, requisitos, documentos_exigidos,
             riscos, recomendacao, analise_completa)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            licitacao_id,
            analise.get("score"),
            analise.get("oportunidade"),
            json.dumps(analise.get("requisitos_criticos", []), ensure_ascii=False),
            json.dumps(analise.get("documentos_necessarios", []), ensure_ascii=False),
            json.dumps(analise.get("riscos", []), ensure_ascii=False),
            analise.get("recomendacao"),
            json.dumps(analise, ensure_ascii=False),
        ))


def buscar_analise(licitacao_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM analises WHERE licitacao_id = ?", (licitacao_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        for campo in ("requisitos", "documentos_exigidos", "riscos", "analise_completa"):
            try:
                d[campo] = json.loads(d[campo])
            except Exception:
                pass
        return d


# ── CRUD Alertas ─────────────────────────────────────────────────────────────

def registrar_alerta(licitacao_id: int, canal: str, destinatario: str):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO alertas (licitacao_id, canal, destinatario)
            VALUES (?,?,?)
        """, (licitacao_id, canal, destinatario))


def marcar_alerta_enviado(alerta_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE alertas SET enviado=1, enviado_em=? WHERE id=?",
            (datetime.now().isoformat(), alerta_id)
        )


def alertas_pendentes() -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM alertas WHERE enviado=0"
        ).fetchall()
        return [dict(r) for r in rows]


# ── Estatísticas ─────────────────────────────────────────────────────────────

def estatisticas() -> dict:
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM licitacoes").fetchone()[0]
        analisadas = conn.execute("SELECT COUNT(*) FROM analises").fetchone()[0]
        oportunidades = conn.execute(
            "SELECT COUNT(*) FROM analises WHERE score >= 70"
        ).fetchone()[0]
        valor_total = conn.execute(
            "SELECT SUM(valor_estimado) FROM licitacoes"
        ).fetchone()[0] or 0

        por_uf = conn.execute("""
            SELECT orgao_uf, COUNT(*) as qtd
            FROM licitacoes
            GROUP BY orgao_uf
            ORDER BY qtd DESC
            LIMIT 10
        """).fetchall()

        return {
            "total_licitacoes": total,
            "analisadas": analisadas,
            "oportunidades_score_alto": oportunidades,
            "valor_total_estimado": valor_total,
            "por_uf": [dict(r) for r in por_uf],
        }


# ── Init automático ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    print(json.dumps(estatisticas(), indent=2))
