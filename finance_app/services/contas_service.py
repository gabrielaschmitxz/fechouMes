from __future__ import annotations

from datetime import date
from typing import List, Tuple, Dict

from finance_app.database import get_connection
from finance_app.models import ContaFixa


def _normalizar_data_iso(data_str: str | None) -> str | None:
    valor = (data_str or "").strip()
    if not valor:
        return None
    try:
        date.fromisoformat(valor)
        return valor
    except ValueError:
        return None


def mes_ano_atual() -> Tuple[int, int]:
    hoje = date.today()
    return hoje.month, hoje.year


def gerar_contas_fixas_mes_atual() -> None:
    """Gera automaticamente, no inÃ­cio do mÃªs, as contas fixas baseadas no mÃªs anterior.

    Regra de data_fim: se a data_fim for anterior ao primeiro dia do mÃªs atual, nÃ£o gera.
    """
    mes_atual, ano_atual = mes_ano_atual()
    if mes_atual == 1:
        mes_anterior, ano_anterior = 12, ano_atual - 1
    else:
        mes_anterior, ano_anterior = mes_atual - 1, ano_atual

    conn = get_connection()
    cur = conn.cursor()

    # Verifica se jÃ¡ existem contas para o mÃªs atual
    cur.execute(
        """
        SELECT COUNT(*) AS c FROM contas_fixas
        WHERE mes_referencia = ? AND ano_referencia = ?;
        """,
        (mes_atual, ano_atual),
    )
    if cur.fetchone()["c"] > 0:
        conn.close()
        return

    # Pega a última versão de cada conta antes do mês atual.
    cur.execute(
        """
        SELECT c1.nome, c1.categoria, c1.valor_padrao, c1.vencimento_dia, c1.vencimento_data, c1.data_fim
        FROM contas_fixas c1
        INNER JOIN (
            SELECT nome, MAX(ano_referencia * 100 + mes_referencia) AS yyyymm
            FROM contas_fixas
            WHERE (ano_referencia * 100 + mes_referencia) < (? * 100 + ?)
            GROUP BY nome
        ) ult
            ON ult.nome = c1.nome
           AND (c1.ano_referencia * 100 + c1.mes_referencia) = ult.yyyymm;
        """,
        (ano_atual, mes_atual),
    )
    rows = cur.fetchall()

    for r in rows:
        data_fim = r["data_fim"]
        if data_fim:
            try:
                if isinstance(data_fim, str):
                    fim = date.fromisoformat(data_fim)
                else:
                    fim = data_fim
            except ValueError:
                fim = None
            if fim and fim < date(ano_atual, mes_atual, 1):
                # NÃ£o gerar para meses apÃ³s a data_fim
                continue

        cur.execute(
            """
            INSERT INTO contas_fixas
            (nome, categoria, valor_padrao, vencimento_dia, vencimento_data, mes_referencia, ano_referencia, status, data_fim)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'Pendente', ?);
            """,
            (
                r["nome"],
                r["categoria"],
                r["valor_padrao"],
                r["vencimento_dia"],
                r["vencimento_data"],
                mes_atual,
                ano_atual,
                data_fim,
            ),
        )

    conn.commit()
    conn.close()


def criar_conta_fixa(
    nome: str,
    categoria: str | None,
    valor_padrao: float | None,
    vencimento_data: str | None = None,
    vencimento_dia: int | None = None,
    mes: int | None = None,
    ano: int | None = None,
    data_fim: str | None = None,
) -> None:
    if mes is None or ano is None:
        mes, ano = mes_ano_atual()

    vencimento_data = _normalizar_data_iso(vencimento_data)
    data_fim = _normalizar_data_iso(data_fim)

    conn = get_connection()
    cur = conn.cursor()
    if vencimento_data:
        try:
            vencimento_dia = date.fromisoformat(vencimento_data).day
        except ValueError:
            vencimento_data = None
            vencimento_dia = None
    cur.execute(
        """
        INSERT INTO contas_fixas
        (nome, categoria, valor_padrao, vencimento_dia, vencimento_data, mes_referencia, ano_referencia, status, data_fim)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'Pendente', ?);
        """,
        (nome, categoria, valor_padrao, vencimento_dia, vencimento_data, mes, ano, data_fim),
    )
    conn.commit()
    conn.close()


def listar_contas_fixas(mes: int, ano: int) -> List[ContaFixa]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, nome, categoria, valor_padrao, vencimento_dia, vencimento_data,
               mes_referencia, ano_referencia, status, data_fim
        FROM contas_fixas
        WHERE mes_referencia = ? AND ano_referencia = ?
        ORDER BY COALESCE(vencimento_dia, 99), nome;
        """,
        (mes, ano),
    )
    rows = cur.fetchall()
    conn.close()
    return [ContaFixa(**dict(r)) for r in rows]


def atualizar_conta_fixa(
    conta_id: int,
    nome: str,
    categoria: str | None,
    valor_padrao: float | None,
    vencimento_data: str | None,
    data_fim: str | None,
) -> bool:
    vencimento_data = _normalizar_data_iso(vencimento_data)
    data_fim = _normalizar_data_iso(data_fim)

    vencimento_dia = None
    if vencimento_data:
        try:
            vencimento_dia = date.fromisoformat(vencimento_data).day
        except ValueError:
            vencimento_data = None
            vencimento_dia = None

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE contas_fixas
        SET nome = ?,
            categoria = ?,
            valor_padrao = ?,
            vencimento_data = ?,
            vencimento_dia = ?,
            data_fim = ?
        WHERE id = ?;
        """,
        (nome, categoria, valor_padrao, vencimento_data, vencimento_dia, data_fim, conta_id),
    )
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def excluir_conta_fixa(conta_id: int) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM contas_fixas WHERE id = ?;", (conta_id,))
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def marcar_conta_como_paga(conta_id: int) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE contas_fixas SET status = 'Pago' WHERE id = ?;",
        (conta_id,),
    )
    conn.commit()
    conn.close()


def calcular_totais_contas_fixas(mes: int, ano: int) -> Dict[str, float]:
    contas = listar_contas_fixas(mes, ano)
    total = sum(c.valor_padrao or 0 for c in contas)
    total_pendente = sum(
        (c.valor_padrao or 0) for c in contas if c.status == "Pendente"
    )
    total_pago = total - total_pendente
    return {
        "total": total,
        "total_pendente": total_pendente,
        "total_pago": total_pago,
    }

