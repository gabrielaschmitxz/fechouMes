import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "database.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    cur = conn.cursor()

    # receitas_saldos
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS receitas_saldos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE,
            saldo_atual REAL NOT NULL DEFAULT 0
        );
        """
    )

    # receitas_extras
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
    cur.execute("PRAGMA table_info(receitas_extras);")
    cols_extras = {row["name"] for row in cur.fetchall()}
    if "categoria" not in cols_extras:
        cur.execute(
            "ALTER TABLE receitas_extras ADD COLUMN categoria TEXT NOT NULL DEFAULT 'extra';"
        )
    if "dia_recebimento" not in cols_extras:
        cur.execute("ALTER TABLE receitas_extras ADD COLUMN dia_recebimento INTEGER;")
    if "data_recebimento" not in cols_extras:
        cur.execute("ALTER TABLE receitas_extras ADD COLUMN data_recebimento TEXT;")

    # receitas_lancamentos
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
    cur.execute("PRAGMA table_info(receitas_lancamentos);")
    cols_lanc = {row["name"] for row in cur.fetchall()}
    if "receita_extra_id" not in cols_lanc:
        cur.execute("ALTER TABLE receitas_lancamentos ADD COLUMN receita_extra_id INTEGER;")
    if "data_recebimento" not in cols_lanc:
        cur.execute("ALTER TABLE receitas_lancamentos ADD COLUMN data_recebimento TEXT;")

    # contas_fixas
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS contas_fixas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            categoria TEXT,
            valor_padrao REAL,
            vencimento_dia INTEGER,
            vencimento_data TEXT,
            mes_referencia INTEGER NOT NULL,
            ano_referencia INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pendente',
            data_fim TEXT
        );
        """
    )
    cur.execute("PRAGMA table_info(contas_fixas);")
    cols_contas = {row["name"] for row in cur.fetchall()}
    if "categoria" not in cols_contas:
        cur.execute("ALTER TABLE contas_fixas ADD COLUMN categoria TEXT;")
    if "vencimento_data" not in cols_contas:
        cur.execute("ALTER TABLE contas_fixas ADD COLUMN vencimento_data TEXT;")

    # cartao_config
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

    # cartao_parceladas
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

    # cartao_avista
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

    # gastos_pix
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
    cur.execute("PRAGMA table_info(gastos_pix);")
    cols_gastos = {row["name"] for row in cur.fetchall()}
    if "receita_extra_id" not in cols_gastos:
        cur.execute("ALTER TABLE gastos_pix ADD COLUMN receita_extra_id INTEGER;")

    # pessoas
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

    # Migração para bases antigas sem coluna padrao
    cur.execute("PRAGMA table_info(pessoas);")
    cols = {row["name"] for row in cur.fetchall()}
    if "padrao" not in cols:
        cur.execute("ALTER TABLE pessoas ADD COLUMN padrao INTEGER NOT NULL DEFAULT 0;")

    # pagamentos_terceiros
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

    # itens pagos de terceiros (para registrar quais contas foram quitadas)
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

    conn.commit()
    conn.close()


def ensure_seed_data() -> None:
    """Cria registros básicos (Gabriela, Kristian, config cartão) se não existirem."""
    conn = get_connection()
    cur = conn.cursor()

    # Saldos principais (não recria pessoas automaticamente)
    for nome in ("Gabriela", "Kristian"):
        cur.execute(
            "INSERT OR IGNORE INTO receitas_saldos (nome, saldo_atual) VALUES (?, 0);",
            (nome,),
        )

    # Config cartão default
    cur.execute("SELECT COUNT(*) AS c FROM cartao_config;")
    if cur.fetchone()["c"] == 0:
        cur.execute(
            """
            INSERT INTO cartao_config (id, limite_total, dia_fechamento, dia_vencimento, fatura_paga)
            VALUES (1, NULL, 10, 20, 0);
            """
        )

    conn.commit()
    conn.close()


def setup_database() -> None:
    """Função de conveniência para usar no início da aplicação."""
    init_db()
    ensure_seed_data()
