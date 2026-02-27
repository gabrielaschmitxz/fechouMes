import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

from werkzeug.security import generate_password_hash
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
USE_POSTGRES = DATABASE_URL.startswith("postgresql://") or DATABASE_URL.startswith("postgres://")
DB_PATH = Path(os.getenv("DB_PATH", str(Path(__file__).resolve().parent / "database.db")))
_PG_POOL = None
_PG_POOL_LOCK = threading.Lock()


class CursorCompat:
    def __init__(self, cursor: Any, postgres: bool):
        self._cursor = cursor
        self._postgres = postgres

    def _fix_placeholders(self, query: str) -> str:
        if not self._postgres:
            return query
        return query.replace("?", "%s")

    def execute(self, query: str, params: Any = None):
        fixed = self._fix_placeholders(query)
        if params is None:
            return self._cursor.execute(fixed)
        return self._cursor.execute(fixed, params)

    def executemany(self, query: str, seq_params: Any):
        fixed = self._fix_placeholders(query)
        return self._cursor.executemany(fixed, seq_params)

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def __getattr__(self, item: str):
        return getattr(self._cursor, item)


class ConnectionCompat:
    def __init__(self, conn: Any, postgres: bool, from_pool: bool = False):
        self._conn = conn
        self._postgres = postgres
        self._from_pool = from_pool

    def cursor(self):
        if self._postgres:
            from psycopg2.extras import RealDictCursor

            return CursorCompat(self._conn.cursor(cursor_factory=RealDictCursor), postgres=True)
        return CursorCompat(self._conn.cursor(), postgres=False)

    def commit(self):
        return self._conn.commit()

    def close(self):
        if self._postgres and self._from_pool:
            pool = _get_pg_pool()
            pool.putconn(self._conn)
            return
        return self._conn.close()

    def __getattr__(self, item: str):
        return getattr(self._conn, item)


def get_connection() -> ConnectionCompat:
    if USE_POSTGRES:
        pool = _get_pg_pool()
        conn = pool.getconn()
        return ConnectionCompat(conn, postgres=True, from_pool=True)

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return ConnectionCompat(conn, postgres=False)


def _get_pg_pool():
    global _PG_POOL
    if _PG_POOL is not None:
        return _PG_POOL

    with _PG_POOL_LOCK:
        if _PG_POOL is not None:
            return _PG_POOL
        from psycopg2.pool import SimpleConnectionPool

        minconn = int(os.getenv("PG_POOL_MIN", "1"))
        maxconn = int(os.getenv("PG_POOL_MAX", "10"))
        _PG_POOL = SimpleConnectionPool(minconn, maxconn, dsn=DATABASE_URL)
    return _PG_POOL


def _init_db_sqlite(cur: CursorCompat) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS receitas_saldos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE,
            saldo_atual REAL NOT NULL DEFAULT 0
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS receitas_extras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao TEXT NOT NULL UNIQUE,
            valor_padrao REAL,
            categoria TEXT NOT NULL DEFAULT 'extra',
            dia_recebimento INTEGER,
            data_recebimento TEXT
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS receitas_lancamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            saldo_id INTEGER NOT NULL,
            receita_extra_id INTEGER,
            tipo_origem TEXT NOT NULL,
            categoria TEXT NOT NULL,
            descricao TEXT,
            valor REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            data_recebimento TEXT,
            FOREIGN KEY (receita_extra_id) REFERENCES receitas_extras (id),
            FOREIGN KEY (saldo_id) REFERENCES receitas_saldos (id)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pessoas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE,
            ativo INTEGER NOT NULL DEFAULT 1,
            padrao INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS contas_fixas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            categoria TEXT,
            valor_padrao REAL,
            desconto_pessoa_nome TEXT,
            desconto_origem TEXT,
            desconto_receita_extra_id INTEGER,
            desconto_aplicado INTEGER NOT NULL DEFAULT 0,
            vencimento_dia INTEGER,
            vencimento_data TEXT,
            mes_referencia INTEGER NOT NULL,
            ano_referencia INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pendente',
            data_fim TEXT
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cartao_config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            limite_total REAL,
            dia_fechamento INTEGER,
            dia_vencimento INTEGER,
            fatura_paga INTEGER DEFAULT 0
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cartao_parceladas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao TEXT NOT NULL,
            valor_parcela REAL NOT NULL,
            total_parcelas INTEGER NOT NULL,
            parcela_atual INTEGER NOT NULL DEFAULT 1,
            mes_inicio INTEGER NOT NULL,
            ano_inicio INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'Ativa',
            pessoa_id INTEGER,
            FOREIGN KEY (pessoa_id) REFERENCES pessoas (id)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cartao_avista (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao TEXT NOT NULL,
            valor REAL NOT NULL,
            mes_referencia INTEGER NOT NULL,
            ano_referencia INTEGER NOT NULL,
            pessoa_id INTEGER,
            FOREIGN KEY (pessoa_id) REFERENCES pessoas (id)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS gastos_pix (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao TEXT NOT NULL,
            valor REAL NOT NULL,
            categoria TEXT,
            mes_referencia INTEGER NOT NULL,
            ano_referencia INTEGER NOT NULL,
            pessoa_id INTEGER,
            receita_extra_id INTEGER,
            FOREIGN KEY (receita_extra_id) REFERENCES receitas_extras (id),
            FOREIGN KEY (pessoa_id) REFERENCES pessoas (id)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pagamentos_terceiros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pessoa_id INTEGER NOT NULL,
            valor REAL NOT NULL,
            descricao TEXT,
            mes_referencia INTEGER NOT NULL,
            ano_referencia INTEGER NOT NULL,
            FOREIGN KEY (pessoa_id) REFERENCES pessoas (id)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pagamentos_terceiros_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pagamento_id INTEGER NOT NULL,
            pessoa_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            item_id INTEGER NOT NULL,
            descricao_item TEXT NOT NULL,
            valor REAL NOT NULL,
            mes_referencia INTEGER NOT NULL,
            ano_referencia INTEGER NOT NULL,
            FOREIGN KEY (pagamento_id) REFERENCES pagamentos_terceiros (id),
            FOREIGN KEY (pessoa_id) REFERENCES pessoas (id),
            UNIQUE (pessoa_id, tipo, item_id, mes_referencia, ano_referencia)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pessoas_descontos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pessoa_id INTEGER NOT NULL,
            valor REAL NOT NULL DEFAULT 0,
            mes_referencia INTEGER NOT NULL,
            ano_referencia INTEGER NOT NULL,
            UNIQUE (pessoa_id, mes_referencia, ano_referencia),
            FOREIGN KEY (pessoa_id) REFERENCES pessoas (id)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pessoas_descontos_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pessoa_id INTEGER NOT NULL,
            descricao TEXT NOT NULL,
            valor REAL NOT NULL DEFAULT 0,
            mes_referencia INTEGER NOT NULL,
            ano_referencia INTEGER NOT NULL,
            FOREIGN KEY (pessoa_id) REFERENCES pessoas (id)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            ativo INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )

    # Indices de performance (SQLite)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_contas_mes_ano ON contas_fixas (mes_referencia, ano_referencia);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_contas_nome_ref ON contas_fixas (nome, ano_referencia, mes_referencia);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cartao_avista_ref ON cartao_avista (mes_referencia, ano_referencia);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cartao_avista_pessoa_ref ON cartao_avista (pessoa_id, ano_referencia, mes_referencia);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cartao_parceladas_status ON cartao_parceladas (status);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cartao_parceladas_pessoa_status ON cartao_parceladas (pessoa_id, status);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_gastos_ref ON gastos_pix (mes_referencia, ano_referencia);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_gastos_pessoa_ref ON gastos_pix (pessoa_id, mes_referencia, ano_referencia);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pag_terc_pessoa_ref ON pagamentos_terceiros (pessoa_id, mes_referencia, ano_referencia);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pag_itens_pessoa_ref ON pagamentos_terceiros_itens (pessoa_id, mes_referencia, ano_referencia);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pag_itens_tipo_item_ref ON pagamentos_terceiros_itens (tipo, item_id, pessoa_id, mes_referencia, ano_referencia);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_contas_desconto_nome ON contas_fixas (desconto_pessoa_nome);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pessoas_desc_ref ON pessoas_descontos (pessoa_id, mes_referencia, ano_referencia);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pessoas_desc_itens_ref ON pessoas_descontos_itens (pessoa_id, mes_referencia, ano_referencia);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_receitas_lanc_saldo ON receitas_lancamentos (saldo_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_receitas_lanc_extra ON receitas_lancamentos (receita_extra_id);")


def _init_db_postgres(cur: CursorCompat) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS receitas_saldos (
            id BIGSERIAL PRIMARY KEY,
            nome TEXT NOT NULL UNIQUE,
            saldo_atual NUMERIC(14,2) NOT NULL DEFAULT 0
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS receitas_extras (
            id BIGSERIAL PRIMARY KEY,
            descricao TEXT NOT NULL UNIQUE,
            valor_padrao NUMERIC(14,2),
            categoria TEXT NOT NULL DEFAULT 'extra',
            dia_recebimento INTEGER,
            data_recebimento DATE
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pessoas (
            id BIGSERIAL PRIMARY KEY,
            nome TEXT NOT NULL UNIQUE,
            ativo BOOLEAN NOT NULL DEFAULT TRUE,
            padrao BOOLEAN NOT NULL DEFAULT FALSE
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS receitas_lancamentos (
            id BIGSERIAL PRIMARY KEY,
            saldo_id BIGINT NOT NULL REFERENCES receitas_saldos (id),
            receita_extra_id BIGINT REFERENCES receitas_extras (id),
            tipo_origem TEXT NOT NULL,
            categoria TEXT NOT NULL,
            descricao TEXT,
            valor NUMERIC(14,2) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            data_recebimento DATE
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS contas_fixas (
            id BIGSERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            categoria TEXT,
            valor_padrao NUMERIC(14,2),
            desconto_pessoa_nome TEXT,
            desconto_origem TEXT,
            desconto_receita_extra_id BIGINT,
            desconto_aplicado BOOLEAN NOT NULL DEFAULT FALSE,
            vencimento_dia INTEGER,
            vencimento_data DATE,
            mes_referencia INTEGER NOT NULL,
            ano_referencia INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pendente',
            data_fim DATE
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cartao_config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            limite_total NUMERIC(14,2),
            dia_fechamento INTEGER,
            dia_vencimento INTEGER,
            fatura_paga BOOLEAN NOT NULL DEFAULT FALSE
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cartao_parceladas (
            id BIGSERIAL PRIMARY KEY,
            descricao TEXT NOT NULL,
            valor_parcela NUMERIC(14,2) NOT NULL,
            total_parcelas INTEGER NOT NULL,
            parcela_atual INTEGER NOT NULL DEFAULT 1,
            mes_inicio INTEGER NOT NULL,
            ano_inicio INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'Ativa',
            pessoa_id BIGINT REFERENCES pessoas (id)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cartao_avista (
            id BIGSERIAL PRIMARY KEY,
            descricao TEXT NOT NULL,
            valor NUMERIC(14,2) NOT NULL,
            mes_referencia INTEGER NOT NULL,
            ano_referencia INTEGER NOT NULL,
            pessoa_id BIGINT REFERENCES pessoas (id)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS gastos_pix (
            id BIGSERIAL PRIMARY KEY,
            descricao TEXT NOT NULL,
            valor NUMERIC(14,2) NOT NULL,
            categoria TEXT,
            mes_referencia INTEGER NOT NULL,
            ano_referencia INTEGER NOT NULL,
            pessoa_id BIGINT REFERENCES pessoas (id),
            receita_extra_id BIGINT REFERENCES receitas_extras (id)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pagamentos_terceiros (
            id BIGSERIAL PRIMARY KEY,
            pessoa_id BIGINT NOT NULL REFERENCES pessoas (id),
            valor NUMERIC(14,2) NOT NULL,
            descricao TEXT,
            mes_referencia INTEGER NOT NULL,
            ano_referencia INTEGER NOT NULL
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pagamentos_terceiros_itens (
            id BIGSERIAL PRIMARY KEY,
            pagamento_id BIGINT NOT NULL REFERENCES pagamentos_terceiros (id),
            pessoa_id BIGINT NOT NULL REFERENCES pessoas (id),
            tipo TEXT NOT NULL,
            item_id BIGINT NOT NULL,
            descricao_item TEXT NOT NULL,
            valor NUMERIC(14,2) NOT NULL,
            mes_referencia INTEGER NOT NULL,
            ano_referencia INTEGER NOT NULL,
            UNIQUE (pessoa_id, tipo, item_id, mes_referencia, ano_referencia)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pessoas_descontos (
            id BIGSERIAL PRIMARY KEY,
            pessoa_id BIGINT NOT NULL REFERENCES pessoas (id),
            valor NUMERIC(14,2) NOT NULL DEFAULT 0,
            mes_referencia INTEGER NOT NULL,
            ano_referencia INTEGER NOT NULL,
            UNIQUE (pessoa_id, mes_referencia, ano_referencia)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pessoas_descontos_itens (
            id BIGSERIAL PRIMARY KEY,
            pessoa_id BIGINT NOT NULL REFERENCES pessoas (id),
            descricao TEXT NOT NULL,
            valor NUMERIC(14,2) NOT NULL DEFAULT 0,
            mes_referencia INTEGER NOT NULL,
            ano_referencia INTEGER NOT NULL
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS usuarios (
            id BIGSERIAL PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            ativo BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )

    # Indices de performance (PostgreSQL)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_contas_mes_ano ON contas_fixas (mes_referencia, ano_referencia);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_contas_nome_ref ON contas_fixas (nome, ano_referencia, mes_referencia);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cartao_avista_ref ON cartao_avista (mes_referencia, ano_referencia);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cartao_avista_pessoa_ref ON cartao_avista (pessoa_id, ano_referencia, mes_referencia);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cartao_parceladas_status ON cartao_parceladas (status);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cartao_parceladas_pessoa_status ON cartao_parceladas (pessoa_id, status);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_gastos_ref ON gastos_pix (mes_referencia, ano_referencia);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_gastos_pessoa_ref ON gastos_pix (pessoa_id, mes_referencia, ano_referencia);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pag_terc_pessoa_ref ON pagamentos_terceiros (pessoa_id, mes_referencia, ano_referencia);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pag_itens_pessoa_ref ON pagamentos_terceiros_itens (pessoa_id, mes_referencia, ano_referencia);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pag_itens_tipo_item_ref ON pagamentos_terceiros_itens (tipo, item_id, pessoa_id, mes_referencia, ano_referencia);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_contas_desconto_nome ON contas_fixas (desconto_pessoa_nome);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pessoas_desc_ref ON pessoas_descontos (pessoa_id, mes_referencia, ano_referencia);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pessoas_desc_itens_ref ON pessoas_descontos_itens (pessoa_id, mes_referencia, ano_referencia);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_receitas_lanc_saldo ON receitas_lancamentos (saldo_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_receitas_lanc_extra ON receitas_lancamentos (receita_extra_id);")


def _apply_migrations(cur: CursorCompat) -> None:
    if USE_POSTGRES:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'contas_fixas';
            """
        )
        cols = {str(r["column_name"]) for r in cur.fetchall()}
        if "desconto_pessoa_nome" not in cols:
            cur.execute("ALTER TABLE contas_fixas ADD COLUMN desconto_pessoa_nome TEXT;")
        if "desconto_origem" not in cols:
            cur.execute("ALTER TABLE contas_fixas ADD COLUMN desconto_origem TEXT;")
        if "desconto_receita_extra_id" not in cols:
            cur.execute("ALTER TABLE contas_fixas ADD COLUMN desconto_receita_extra_id BIGINT;")
        if "desconto_aplicado" not in cols:
            cur.execute("ALTER TABLE contas_fixas ADD COLUMN desconto_aplicado BOOLEAN NOT NULL DEFAULT FALSE;")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS pessoas_descontos (
                id BIGSERIAL PRIMARY KEY,
                pessoa_id BIGINT NOT NULL REFERENCES pessoas (id),
                valor NUMERIC(14,2) NOT NULL DEFAULT 0,
                mes_referencia INTEGER NOT NULL,
                ano_referencia INTEGER NOT NULL,
                UNIQUE (pessoa_id, mes_referencia, ano_referencia)
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pessoas_desc_ref ON pessoas_descontos (pessoa_id, mes_referencia, ano_referencia);")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS pessoas_descontos_itens (
                id BIGSERIAL PRIMARY KEY,
                pessoa_id BIGINT NOT NULL REFERENCES pessoas (id),
                descricao TEXT NOT NULL,
                valor NUMERIC(14,2) NOT NULL DEFAULT 0,
                mes_referencia INTEGER NOT NULL,
                ano_referencia INTEGER NOT NULL
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pessoas_desc_itens_ref ON pessoas_descontos_itens (pessoa_id, mes_referencia, ano_referencia);")
        return

    cur.execute("PRAGMA table_info(contas_fixas);")
    cols = {str(r["name"]) for r in cur.fetchall()}
    if "desconto_pessoa_nome" not in cols:
        cur.execute("ALTER TABLE contas_fixas ADD COLUMN desconto_pessoa_nome TEXT;")
    if "desconto_origem" not in cols:
        cur.execute("ALTER TABLE contas_fixas ADD COLUMN desconto_origem TEXT;")
    if "desconto_receita_extra_id" not in cols:
        cur.execute("ALTER TABLE contas_fixas ADD COLUMN desconto_receita_extra_id INTEGER;")
    if "desconto_aplicado" not in cols:
        cur.execute("ALTER TABLE contas_fixas ADD COLUMN desconto_aplicado INTEGER NOT NULL DEFAULT 0;")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pessoas_descontos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pessoa_id INTEGER NOT NULL,
            valor REAL NOT NULL DEFAULT 0,
            mes_referencia INTEGER NOT NULL,
            ano_referencia INTEGER NOT NULL,
            UNIQUE (pessoa_id, mes_referencia, ano_referencia),
            FOREIGN KEY (pessoa_id) REFERENCES pessoas (id)
        );
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pessoas_desc_ref ON pessoas_descontos (pessoa_id, mes_referencia, ano_referencia);")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pessoas_descontos_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pessoa_id INTEGER NOT NULL,
            descricao TEXT NOT NULL,
            valor REAL NOT NULL DEFAULT 0,
            mes_referencia INTEGER NOT NULL,
            ano_referencia INTEGER NOT NULL,
            FOREIGN KEY (pessoa_id) REFERENCES pessoas (id)
        );
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pessoas_desc_itens_ref ON pessoas_descontos_itens (pessoa_id, mes_referencia, ano_referencia);")


def init_db() -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        if USE_POSTGRES:
            _init_db_postgres(cur)
        else:
            _init_db_sqlite(cur)
        _apply_migrations(cur)
        conn.commit()
    finally:
        conn.close()


def ensure_seed_data() -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        for nome in ("Gabriela", "Kristian"):
            if USE_POSTGRES:
                cur.execute(
                    "INSERT INTO receitas_saldos (nome, saldo_atual) VALUES (?, 0) ON CONFLICT (nome) DO NOTHING;",
                    (nome,),
                )
            else:
                cur.execute(
                    "INSERT OR IGNORE INTO receitas_saldos (nome, saldo_atual) VALUES (?, 0);",
                    (nome,),
                )

        if USE_POSTGRES:
            cur.execute(
                """
                INSERT INTO cartao_config (id, limite_total, dia_fechamento, dia_vencimento, fatura_paga)
                VALUES (1, NULL, 10, 20, FALSE)
                ON CONFLICT (id) DO NOTHING;
                """
            )
        else:
            cur.execute("SELECT COUNT(*) AS c FROM cartao_config;")
            if cur.fetchone()["c"] == 0:
                cur.execute(
                    """
                    INSERT INTO cartao_config (id, limite_total, dia_fechamento, dia_vencimento, fatura_paga)
                    VALUES (1, NULL, 10, 20, 0);
                    """
                )

        admin_username = os.getenv("ADMIN_USERNAME", "admin")
        admin_password = os.getenv("ADMIN_PASSWORD", "admin123")
        if USE_POSTGRES:
            cur.execute(
                """
                INSERT INTO usuarios (username, password_hash, ativo)
                VALUES (?, ?, TRUE)
                ON CONFLICT (username) DO NOTHING;
                """,
                (admin_username, generate_password_hash(admin_password)),
            )
        else:
            cur.execute(
                """
                INSERT OR IGNORE INTO usuarios (username, password_hash, ativo)
                VALUES (?, ?, 1);
                """,
                (admin_username, generate_password_hash(admin_password)),
            )

        conn.commit()
    finally:
        conn.close()


def setup_database() -> None:
    init_db()
    ensure_seed_data()
