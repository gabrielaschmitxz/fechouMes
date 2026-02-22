from __future__ import annotations

from datetime import date
from typing import Dict, List, Tuple

from finance_app.database import get_connection
from finance_app.models import CartaoConfig, CartaoParcelada, CartaoAvista


def get_config() -> CartaoConfig:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, limite_total, dia_fechamento, dia_vencimento, fatura_paga FROM cartao_config WHERE id = 1;") # Removed get_cursor(conn) and used conn.cursor()
    row = cur.fetchone()
    conn.close()
    if not row:
        raise RuntimeError("ConfiguraÃ§Ã£o do cartÃ£o nÃ£o encontrada.")
    data = dict(row)
    data["fatura_paga"] = bool(data["fatura_paga"])
    return CartaoConfig(**data)


def atualizar_config(limite_total: float, dia_fechamento: int, dia_vencimento: int) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE cartao_config
        SET limite_total = ?, dia_fechamento = ?, dia_vencimento = ?
        WHERE id = 1;
        """,
        (limite_total, dia_fechamento, dia_vencimento),
    )
    conn.commit()
    conn.close()


def mes_ano_fatura_atual(hoje: date | None = None) -> Tuple[int, int]:
    """Determina o mÃªs/ano de referÃªncia da fatura atual com base no dia de fechamento."""
    if hoje is None:
        hoje = date.today()
    cfg = get_config()
    mes = hoje.month
    ano = hoje.year
    # Compras apÃ³s o fechamento pertencem Ã  prÃ³xima fatura
    if hoje.day > cfg.dia_fechamento:
        if mes == 12:
            mes = 1
            ano += 1
        else:
            mes += 1
    return mes, ano


def listar_parceladas_ativas() -> List[CartaoParcelada]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, descricao, valor_parcela, total_parcelas, parcela_atual,
               mes_inicio, ano_inicio, status, pessoa_id
        FROM cartao_parceladas
        WHERE status = 'Ativa'
        ORDER BY id;
        """
    )
    rows = cur.fetchall()
    conn.close()
    return [CartaoParcelada(**dict(r)) for r in rows]


def criar_parcelada(
    descricao: str,
    valor_total: float,
    total_parcelas: int,
    mes_inicio: int,
    ano_inicio: int,
    pessoa_id: int | None,
    parcela_atual: int = 1,
) -> None:
    valor_parcela = valor_total / total_parcelas if total_parcelas else valor_total
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO cartao_parceladas
        (descricao, valor_parcela, total_parcelas, parcela_atual, mes_inicio, ano_inicio, status, pessoa_id)
        VALUES (?, ?, ?, ?, ?, ?, 'Ativa', ?);
        """,
        (descricao, valor_parcela, total_parcelas, parcela_atual, mes_inicio, ano_inicio, pessoa_id),
    )
    conn.commit()
    conn.close()


def registrar_compra_avista(
    descricao: str,
    valor: float,
    pessoa_id: int | None,
) -> None:
    mes_ref, ano_ref = mes_ano_fatura_atual()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO cartao_avista (descricao, valor, mes_referencia, ano_referencia, pessoa_id)
        VALUES (?, ?, ?, ?, ?);
        """,
        (descricao, valor, mes_ref, ano_ref, pessoa_id),
    )
    conn.commit()
    conn.close()


def listar_avista_mes(mes: int, ano: int) -> List[CartaoAvista]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, descricao, valor, mes_referencia, ano_referencia, pessoa_id
        FROM cartao_avista
        WHERE mes_referencia = ? AND ano_referencia = ?
        ORDER BY id;
        """,
        (mes, ano),
    )
    rows = cur.fetchall()
    conn.close()
    return [CartaoAvista(**dict(r)) for r in rows]


def calcular_fatura_atual() -> Dict[str, float]:
    """Retorna totais: {'parceladas_meu', 'parceladas_terceiros', 'avista_meu', 'avista_terceiros', 'total_meu', 'total_terceiros', 'total_geral'}"""
    mes_ref, ano_ref = mes_ano_fatura_atual()

    # Parceladas: todas ativas contam para a fatura atual
    parceladas = listar_parceladas_ativas()
    total_parceladas_meu = sum(p.valor_parcela for p in parceladas if p.pessoa_id is None)
    total_parceladas_terceiros = sum(
        p.valor_parcela for p in parceladas if p.pessoa_id is not None
    )

    # Ã€ vista: apenas mÃªs/ano de referÃªncia
    avista = listar_avista_mes(mes_ref, ano_ref)
    total_avista_meu = sum(a.valor for a in avista if a.pessoa_id is None)
    total_avista_terceiros = sum(a.valor for a in avista if a.pessoa_id is not None)

    total_meu = total_parceladas_meu + total_avista_meu
    total_terceiros = total_parceladas_terceiros + total_avista_terceiros
    total_geral = total_meu + total_terceiros

    return {
        "mes_referencia": mes_ref,
        "ano_referencia": ano_ref,
        "parceladas_meu": total_parceladas_meu,
        "parceladas_terceiros": total_parceladas_terceiros,
        "avista_meu": total_avista_meu,
        "avista_terceiros": total_avista_terceiros,
        "total_meu": total_meu,
        "total_terceiros": total_terceiros,
        "total_geral": total_geral,
    }


def marcar_fatura_como_paga() -> None:
    """Regras:
    - fatura_paga = True
    - avanÃ§ar mÃªs da fatura (implÃ­cito pela funÃ§Ã£o mes_ano_fatura_atual ao longo do tempo)
    - incrementar parcela_atual +1 em todas parceladas ativas
    - se parcela_atual > total_parcelas -> status = 'Finalizada'
    """
    conn = get_connection()
    cur = conn.cursor()

    # Atualiza flag de fatura paga
    cur.execute("UPDATE cartao_config SET fatura_paga = TRUE WHERE id = 1;")

    # Atualiza parcelas
    cur.execute(
        """
        UPDATE cartao_parceladas
        SET parcela_atual = parcela_atual + 1
        WHERE status = 'Ativa';
        """
    )

    # Finaliza as que passaram do total
    cur.execute(
        """
        UPDATE cartao_parceladas
        SET status = 'Finalizada'
        WHERE parcela_atual > total_parcelas AND status = 'Ativa';
        """
    )

    conn.commit()
    conn.close()


def reabrir_fatura_atual() -> None:
    """Permite marcar novamente como nÃ£o paga (caso de erro)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE cartao_config SET fatura_paga = FALSE WHERE id = 1;")
    conn.commit()
    conn.close()


def listar_todos_lancamentos() -> List[Dict[str, object]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            'avista' AS tipo,
            id,
            descricao,
            valor AS valor,
            NULL AS total_parcelas,
            NULL AS parcela_atual,
            mes_referencia AS mes_ref,
            ano_referencia AS ano_ref,
            'Lançado' AS status,
            pessoa_id
        FROM cartao_avista
        UNION ALL
        SELECT
            'parcelado' AS tipo,
            id,
            descricao,
            valor_parcela AS valor,
            total_parcelas,
            parcela_atual,
            mes_inicio AS mes_ref,
            ano_inicio AS ano_ref,
            status,
            pessoa_id
        FROM cartao_parceladas
        ORDER BY ano_ref DESC, mes_ref DESC, id DESC;
        """
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def excluir_avista(lancamento_id: int) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM cartao_avista WHERE id = ?;", (lancamento_id,))
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def excluir_parcelada(lancamento_id: int) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM cartao_parceladas WHERE id = ?;", (lancamento_id,))
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def atualizar_avista(
    lancamento_id: int, descricao: str, valor: float, pessoa_id: int | None
) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE cartao_avista
        SET descricao = ?, valor = ?, pessoa_id = ?
        WHERE id = ?;
        """,
        (descricao, valor, pessoa_id, lancamento_id),
    )
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def atualizar_parcelada(
    lancamento_id: int,
    descricao: str,
    valor_parcela: float,
    parcela_atual: int,
    total_parcelas: int,
    status: str,
    pessoa_id: int | None,
) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE cartao_parceladas
        SET descricao = ?, valor_parcela = ?, parcela_atual = ?, total_parcelas = ?, status = ?, pessoa_id = ?
        WHERE id = ?;
        """,
        (
            descricao,
            valor_parcela,
            parcela_atual,
            total_parcelas,
            status,
            pessoa_id,
            lancamento_id,
        ),
    )
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok

