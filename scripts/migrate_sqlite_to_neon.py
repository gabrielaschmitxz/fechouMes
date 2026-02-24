import os
import sqlite3
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv


load_dotenv()


SQLITE_PATH = Path("finance_app/database.db")
PG_DSN = os.getenv("DATABASE_URL", "").strip()


def fetchall_dict_sqlite(cur, query, params=()):
    cur.execute(query, params)
    rows = cur.fetchall()
    return [dict(r) for r in rows]


def norm_date(v):
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def get_or_create_pessoa(pg_cur, nome, ativo, padrao):
    pg_cur.execute(
        """
        INSERT INTO pessoas (nome, ativo, padrao)
        VALUES (%s, %s, %s)
        ON CONFLICT (nome) DO UPDATE
        SET ativo = EXCLUDED.ativo,
            padrao = EXCLUDED.padrao
        RETURNING id;
        """,
        (nome, bool(ativo), bool(padrao)),
    )
    return pg_cur.fetchone()["id"]


def get_or_create_saldo(pg_cur, nome, saldo_atual):
    pg_cur.execute(
        """
        INSERT INTO receitas_saldos (nome, saldo_atual)
        VALUES (%s, %s)
        ON CONFLICT (nome) DO UPDATE
        SET saldo_atual = EXCLUDED.saldo_atual
        RETURNING id;
        """,
        (nome, saldo_atual),
    )
    return pg_cur.fetchone()["id"]


def get_or_create_extra(pg_cur, descricao, valor_padrao, categoria, data_recebimento):
    pg_cur.execute(
        """
        INSERT INTO receitas_extras (descricao, valor_padrao, categoria, data_recebimento)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (descricao) DO UPDATE
        SET valor_padrao = EXCLUDED.valor_padrao,
            categoria = EXCLUDED.categoria,
            data_recebimento = EXCLUDED.data_recebimento
        RETURNING id;
        """,
        (descricao, valor_padrao, categoria, data_recebimento),
    )
    return pg_cur.fetchone()["id"]


def exists_with_keys(pg_cur, table, where_sql, params):
    pg_cur.execute(f"SELECT id FROM {table} WHERE {where_sql} LIMIT 1;", params)
    row = pg_cur.fetchone()
    return row["id"] if row else None


def main():
    if not SQLITE_PATH.exists():
        raise SystemExit(f"SQLite não encontrado: {SQLITE_PATH}")
    if not PG_DSN:
        raise SystemExit("DATABASE_URL não definido (Neon).")

    sq_conn = sqlite3.connect(str(SQLITE_PATH))
    sq_conn.row_factory = sqlite3.Row
    sq_cur = sq_conn.cursor()

    pg_conn = psycopg2.connect(PG_DSN, cursor_factory=RealDictCursor)
    pg_cur = pg_conn.cursor()

    # Mapas de IDs origem->destino
    pessoa_id_map = {}
    saldo_id_map = {}
    extra_id_map = {}
    pagamento_id_map = {}

    migrated = {
        "pessoas": 0,
        "usuarios": 0,
        "receitas_saldos": 0,
        "receitas_extras": 0,
        "receitas_lancamentos": 0,
        "contas_fixas": 0,
        "cartao_config": 0,
        "cartao_parceladas": 0,
        "cartao_avista": 0,
        "gastos_pix": 0,
        "pagamentos_terceiros": 0,
        "pagamentos_terceiros_itens": 0,
    }

    try:
        # pessoas
        pessoas = fetchall_dict_sqlite(sq_cur, "SELECT id, nome, ativo, padrao FROM pessoas;")
        for r in pessoas:
            new_id = get_or_create_pessoa(pg_cur, r["nome"], r["ativo"], r["padrao"])
            pessoa_id_map[r["id"]] = new_id
            migrated["pessoas"] += 1

        # usuarios
        usuarios = fetchall_dict_sqlite(
            sq_cur,
            "SELECT username, password_hash, ativo FROM usuarios;",
        )
        for r in usuarios:
            pg_cur.execute(
                """
                INSERT INTO usuarios (username, password_hash, ativo)
                VALUES (%s, %s, %s)
                ON CONFLICT (username) DO UPDATE
                SET password_hash = EXCLUDED.password_hash,
                    ativo = EXCLUDED.ativo;
                """,
                (r["username"], r["password_hash"], bool(r["ativo"])),
            )
            migrated["usuarios"] += 1

        # receitas_saldos
        saldos = fetchall_dict_sqlite(sq_cur, "SELECT id, nome, saldo_atual FROM receitas_saldos;")
        for r in saldos:
            new_id = get_or_create_saldo(pg_cur, r["nome"], r["saldo_atual"])
            saldo_id_map[r["id"]] = new_id
            migrated["receitas_saldos"] += 1

        # receitas_extras
        extras = fetchall_dict_sqlite(
            sq_cur,
            "SELECT id, descricao, valor_padrao, categoria, data_recebimento FROM receitas_extras;",
        )
        for r in extras:
            new_id = get_or_create_extra(
                pg_cur,
                r["descricao"],
                r["valor_padrao"],
                r["categoria"] or "extra",
                norm_date(r["data_recebimento"]),
            )
            extra_id_map[r["id"]] = new_id
            migrated["receitas_extras"] += 1

        # receitas_lancamentos
        lancs = fetchall_dict_sqlite(
            sq_cur,
            """
            SELECT id, saldo_id, receita_extra_id, tipo_origem, categoria, descricao, valor, created_at, data_recebimento
            FROM receitas_lancamentos;
            """,
        )
        for r in lancs:
            saldo_id = saldo_id_map.get(r["saldo_id"])
            if not saldo_id:
                continue
            extra_id = extra_id_map.get(r["receita_extra_id"]) if r["receita_extra_id"] else None

            dup_id = exists_with_keys(
                pg_cur,
                "receitas_lancamentos",
                """
                saldo_id = %s
                AND COALESCE(receita_extra_id, -1) = COALESCE(%s, -1)
                AND tipo_origem = %s
                AND categoria = %s
                AND COALESCE(descricao, '') = COALESCE(%s, '')
                AND valor = %s
                AND COALESCE(data_recebimento::text, '') = COALESCE(%s, '')
                """,
                (
                    saldo_id,
                    extra_id,
                    r["tipo_origem"],
                    r["categoria"],
                    r["descricao"],
                    r["valor"],
                    norm_date(r["data_recebimento"]),
                ),
            )
            if dup_id:
                continue

            pg_cur.execute(
                """
                INSERT INTO receitas_lancamentos
                (saldo_id, receita_extra_id, tipo_origem, categoria, descricao, valor, created_at, data_recebimento)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                """,
                (
                    saldo_id,
                    extra_id,
                    r["tipo_origem"],
                    r["categoria"],
                    r["descricao"],
                    r["valor"],
                    r["created_at"],
                    r["data_recebimento"],
                ),
            )
            migrated["receitas_lancamentos"] += 1

        # contas_fixas
        contas = fetchall_dict_sqlite(
            sq_cur,
            """
            SELECT nome, categoria, valor_padrao, vencimento_dia, vencimento_data, mes_referencia, ano_referencia, status, data_fim
            FROM contas_fixas;
            """,
        )
        for r in contas:
            dup_id = exists_with_keys(
                pg_cur,
                "contas_fixas",
                """
                nome = %s
                AND COALESCE(categoria, '') = COALESCE(%s, '')
                AND COALESCE(valor_padrao, 0) = COALESCE(%s, 0)
                AND COALESCE(vencimento_data::text, '') = COALESCE(%s, '')
                AND mes_referencia = %s
                AND ano_referencia = %s
                AND status = %s
                """,
                (
                    r["nome"],
                    r["categoria"],
                    r["valor_padrao"],
                    norm_date(r["vencimento_data"]),
                    r["mes_referencia"],
                    r["ano_referencia"],
                    r["status"],
                ),
            )
            if dup_id:
                continue
            pg_cur.execute(
                """
                INSERT INTO contas_fixas
                (nome, categoria, valor_padrao, vencimento_dia, vencimento_data, mes_referencia, ano_referencia, status, data_fim)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
                """,
                (
                    r["nome"],
                    r["categoria"],
                    r["valor_padrao"],
                    r["vencimento_dia"],
                    norm_date(r["vencimento_data"]),
                    r["mes_referencia"],
                    r["ano_referencia"],
                    r["status"],
                    norm_date(r["data_fim"]),
                ),
            )
            migrated["contas_fixas"] += 1

        # cartao_config
        cfgs = fetchall_dict_sqlite(
            sq_cur,
            "SELECT id, limite_total, dia_fechamento, dia_vencimento, fatura_paga FROM cartao_config;",
        )
        for r in cfgs:
            pg_cur.execute(
                """
                INSERT INTO cartao_config (id, limite_total, dia_fechamento, dia_vencimento, fatura_paga)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE
                SET limite_total = EXCLUDED.limite_total,
                    dia_fechamento = EXCLUDED.dia_fechamento,
                    dia_vencimento = EXCLUDED.dia_vencimento,
                    fatura_paga = EXCLUDED.fatura_paga;
                """,
                (r["id"], r["limite_total"], r["dia_fechamento"], r["dia_vencimento"], bool(r["fatura_paga"])),
            )
            migrated["cartao_config"] += 1

        # cartao_parceladas
        parceladas = fetchall_dict_sqlite(
            sq_cur,
            """
            SELECT descricao, valor_parcela, total_parcelas, parcela_atual, mes_inicio, ano_inicio, status, pessoa_id
            FROM cartao_parceladas;
            """,
        )
        for r in parceladas:
            pessoa_id = pessoa_id_map.get(r["pessoa_id"]) if r["pessoa_id"] else None
            dup_id = exists_with_keys(
                pg_cur,
                "cartao_parceladas",
                """
                descricao = %s
                AND valor_parcela = %s
                AND total_parcelas = %s
                AND parcela_atual = %s
                AND mes_inicio = %s
                AND ano_inicio = %s
                AND status = %s
                AND COALESCE(pessoa_id, -1) = COALESCE(%s, -1)
                """,
                (
                    r["descricao"],
                    r["valor_parcela"],
                    r["total_parcelas"],
                    r["parcela_atual"],
                    r["mes_inicio"],
                    r["ano_inicio"],
                    r["status"],
                    pessoa_id,
                ),
            )
            if dup_id:
                continue
            pg_cur.execute(
                """
                INSERT INTO cartao_parceladas
                (descricao, valor_parcela, total_parcelas, parcela_atual, mes_inicio, ano_inicio, status, pessoa_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                """,
                (
                    r["descricao"],
                    r["valor_parcela"],
                    r["total_parcelas"],
                    r["parcela_atual"],
                    r["mes_inicio"],
                    r["ano_inicio"],
                    r["status"],
                    pessoa_id,
                ),
            )
            migrated["cartao_parceladas"] += 1

        # cartao_avista
        avista = fetchall_dict_sqlite(
            sq_cur,
            "SELECT descricao, valor, mes_referencia, ano_referencia, pessoa_id FROM cartao_avista;",
        )
        for r in avista:
            pessoa_id = pessoa_id_map.get(r["pessoa_id"]) if r["pessoa_id"] else None
            dup_id = exists_with_keys(
                pg_cur,
                "cartao_avista",
                """
                descricao = %s
                AND valor = %s
                AND mes_referencia = %s
                AND ano_referencia = %s
                AND COALESCE(pessoa_id, -1) = COALESCE(%s, -1)
                """,
                (r["descricao"], r["valor"], r["mes_referencia"], r["ano_referencia"], pessoa_id),
            )
            if dup_id:
                continue
            pg_cur.execute(
                """
                INSERT INTO cartao_avista (descricao, valor, mes_referencia, ano_referencia, pessoa_id)
                VALUES (%s, %s, %s, %s, %s);
                """,
                (r["descricao"], r["valor"], r["mes_referencia"], r["ano_referencia"], pessoa_id),
            )
            migrated["cartao_avista"] += 1

        # gastos_pix
        gastos = fetchall_dict_sqlite(
            sq_cur,
            """
            SELECT descricao, valor, categoria, mes_referencia, ano_referencia, pessoa_id, receita_extra_id
            FROM gastos_pix;
            """,
        )
        for r in gastos:
            pessoa_id = pessoa_id_map.get(r["pessoa_id"]) if r["pessoa_id"] else None
            extra_id = extra_id_map.get(r["receita_extra_id"]) if r["receita_extra_id"] else None
            dup_id = exists_with_keys(
                pg_cur,
                "gastos_pix",
                """
                descricao = %s
                AND valor = %s
                AND COALESCE(categoria, '') = COALESCE(%s, '')
                AND mes_referencia = %s
                AND ano_referencia = %s
                AND COALESCE(pessoa_id, -1) = COALESCE(%s, -1)
                AND COALESCE(receita_extra_id, -1) = COALESCE(%s, -1)
                """,
                (
                    r["descricao"],
                    r["valor"],
                    r["categoria"],
                    r["mes_referencia"],
                    r["ano_referencia"],
                    pessoa_id,
                    extra_id,
                ),
            )
            if dup_id:
                continue
            pg_cur.execute(
                """
                INSERT INTO gastos_pix
                (descricao, valor, categoria, mes_referencia, ano_referencia, pessoa_id, receita_extra_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s);
                """,
                (
                    r["descricao"],
                    r["valor"],
                    r["categoria"],
                    r["mes_referencia"],
                    r["ano_referencia"],
                    pessoa_id,
                    extra_id,
                ),
            )
            migrated["gastos_pix"] += 1

        # pagamentos_terceiros
        pags = fetchall_dict_sqlite(
            sq_cur,
            "SELECT id, pessoa_id, valor, descricao, mes_referencia, ano_referencia FROM pagamentos_terceiros;",
        )
        for r in pags:
            pessoa_id = pessoa_id_map.get(r["pessoa_id"])
            if not pessoa_id:
                continue
            dup_id = exists_with_keys(
                pg_cur,
                "pagamentos_terceiros",
                """
                pessoa_id = %s
                AND valor = %s
                AND COALESCE(descricao, '') = COALESCE(%s, '')
                AND mes_referencia = %s
                AND ano_referencia = %s
                """,
                (pessoa_id, r["valor"], r["descricao"], r["mes_referencia"], r["ano_referencia"]),
            )
            if dup_id:
                pagamento_id_map[r["id"]] = dup_id
                continue
            pg_cur.execute(
                """
                INSERT INTO pagamentos_terceiros
                (pessoa_id, valor, descricao, mes_referencia, ano_referencia)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (pessoa_id, r["valor"], r["descricao"], r["mes_referencia"], r["ano_referencia"]),
            )
            pagamento_id_map[r["id"]] = pg_cur.fetchone()["id"]
            migrated["pagamentos_terceiros"] += 1

        # pagamentos_terceiros_itens
        itens = fetchall_dict_sqlite(
            sq_cur,
            """
            SELECT pagamento_id, pessoa_id, tipo, item_id, descricao_item, valor, mes_referencia, ano_referencia
            FROM pagamentos_terceiros_itens;
            """,
        )
        for r in itens:
            pessoa_id = pessoa_id_map.get(r["pessoa_id"])
            pagamento_id = pagamento_id_map.get(r["pagamento_id"])
            if not pessoa_id or not pagamento_id:
                continue
            dup_id = exists_with_keys(
                pg_cur,
                "pagamentos_terceiros_itens",
                """
                pessoa_id = %s
                AND tipo = %s
                AND item_id = %s
                AND mes_referencia = %s
                AND ano_referencia = %s
                """,
                (pessoa_id, r["tipo"], r["item_id"], r["mes_referencia"], r["ano_referencia"]),
            )
            if dup_id:
                continue
            pg_cur.execute(
                """
                INSERT INTO pagamentos_terceiros_itens
                (pagamento_id, pessoa_id, tipo, item_id, descricao_item, valor, mes_referencia, ano_referencia)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                """,
                (
                    pagamento_id,
                    pessoa_id,
                    r["tipo"],
                    r["item_id"],
                    r["descricao_item"],
                    r["valor"],
                    r["mes_referencia"],
                    r["ano_referencia"],
                ),
            )
            migrated["pagamentos_terceiros_itens"] += 1

        pg_conn.commit()
    except Exception:
        pg_conn.rollback()
        raise
    finally:
        sq_conn.close()
        pg_cur.close()
        pg_conn.close()

    print("Migração concluída (sem duplicar):")
    for k, v in migrated.items():
        print(f"- {k}: {v}")


if __name__ == "__main__":
    main()
