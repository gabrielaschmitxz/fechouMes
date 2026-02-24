BEGIN;

CREATE TABLE IF NOT EXISTS receitas_saldos (
    id BIGSERIAL PRIMARY KEY,
    nome TEXT NOT NULL UNIQUE,
    saldo_atual NUMERIC(14, 2) NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS receitas_extras (
    id BIGSERIAL PRIMARY KEY,
    descricao TEXT NOT NULL UNIQUE,
    valor_padrao NUMERIC(14, 2),
    categoria TEXT NOT NULL DEFAULT 'extra',
    dia_recebimento INTEGER,
    data_recebimento DATE
);

CREATE TABLE IF NOT EXISTS receitas_lancamentos (
    id BIGSERIAL PRIMARY KEY,
    saldo_id BIGINT NOT NULL REFERENCES receitas_saldos (id),
    receita_extra_id BIGINT REFERENCES receitas_extras (id),
    tipo_origem TEXT NOT NULL,
    categoria TEXT NOT NULL,
    descricao TEXT,
    valor NUMERIC(14, 2) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    data_recebimento DATE
);

CREATE TABLE IF NOT EXISTS contas_fixas (
    id BIGSERIAL PRIMARY KEY,
    nome TEXT NOT NULL,
    categoria TEXT,
    valor_padrao NUMERIC(14, 2),
    vencimento_dia INTEGER,
    vencimento_data DATE,
    mes_referencia INTEGER NOT NULL,
    ano_referencia INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'Pendente',
    data_fim DATE
);

CREATE TABLE IF NOT EXISTS cartao_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    limite_total NUMERIC(14, 2),
    dia_fechamento INTEGER,
    dia_vencimento INTEGER,
    fatura_paga BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS cartao_parceladas (
    id BIGSERIAL PRIMARY KEY,
    descricao TEXT NOT NULL,
    valor_parcela NUMERIC(14, 2) NOT NULL,
    total_parcelas INTEGER NOT NULL,
    parcela_atual INTEGER NOT NULL DEFAULT 1,
    mes_inicio INTEGER NOT NULL,
    ano_inicio INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'Ativa',
    pessoa_id BIGINT
);

CREATE TABLE IF NOT EXISTS cartao_avista (
    id BIGSERIAL PRIMARY KEY,
    descricao TEXT NOT NULL,
    valor NUMERIC(14, 2) NOT NULL,
    mes_referencia INTEGER NOT NULL,
    ano_referencia INTEGER NOT NULL,
    pessoa_id BIGINT
);

CREATE TABLE IF NOT EXISTS pessoas (
    id BIGSERIAL PRIMARY KEY,
    nome TEXT NOT NULL UNIQUE,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    padrao BOOLEAN NOT NULL DEFAULT FALSE
);

ALTER TABLE cartao_parceladas
    ADD CONSTRAINT IF NOT EXISTS fk_cartao_parceladas_pessoa
    FOREIGN KEY (pessoa_id) REFERENCES pessoas (id);

ALTER TABLE cartao_avista
    ADD CONSTRAINT IF NOT EXISTS fk_cartao_avista_pessoa
    FOREIGN KEY (pessoa_id) REFERENCES pessoas (id);

CREATE TABLE IF NOT EXISTS gastos_pix (
    id BIGSERIAL PRIMARY KEY,
    descricao TEXT NOT NULL,
    valor NUMERIC(14, 2) NOT NULL,
    categoria TEXT,
    mes_referencia INTEGER NOT NULL,
    ano_referencia INTEGER NOT NULL,
    pessoa_id BIGINT REFERENCES pessoas (id),
    receita_extra_id BIGINT REFERENCES receitas_extras (id)
);

CREATE TABLE IF NOT EXISTS pagamentos_terceiros (
    id BIGSERIAL PRIMARY KEY,
    pessoa_id BIGINT NOT NULL REFERENCES pessoas (id),
    valor NUMERIC(14, 2) NOT NULL,
    descricao TEXT,
    mes_referencia INTEGER NOT NULL,
    ano_referencia INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS pagamentos_terceiros_itens (
    id BIGSERIAL PRIMARY KEY,
    pagamento_id BIGINT NOT NULL REFERENCES pagamentos_terceiros (id),
    pessoa_id BIGINT NOT NULL REFERENCES pessoas (id),
    tipo TEXT NOT NULL,
    item_id BIGINT NOT NULL,
    descricao_item TEXT NOT NULL,
    valor NUMERIC(14, 2) NOT NULL,
    mes_referencia INTEGER NOT NULL,
    ano_referencia INTEGER NOT NULL,
    UNIQUE (pessoa_id, tipo, item_id, mes_referencia, ano_referencia)
);

CREATE TABLE IF NOT EXISTS usuarios (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO cartao_config (id, limite_total, dia_fechamento, dia_vencimento, fatura_paga)
VALUES (1, NULL, 10, 20, FALSE)
ON CONFLICT (id) DO NOTHING;

COMMIT;
