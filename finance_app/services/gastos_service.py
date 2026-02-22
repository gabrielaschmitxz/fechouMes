from __future__ import annotations

from datetime import date
from typing import Dict, List, Tuple

from finance_app.database import get_connection
from finance_app.models import GastoPix


def mes_ano_atual(hoje: date | None = None) -> Tuple[int, int]:
    if hoje is None:
        hoje = date.today()
    return hoje.month, hoje.year


def registrar_gasto_pix(
    descricao: str,
    valor: float,
    categoria: str,
    pessoa_id: int | None,
    receita_extra_id: int | None = None,
    mes: int | None = None,
    ano: int | None = None,
) -> None:
    if mes is None or ano is None:
        mes, ano = mes_ano_atual()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO gastos_pix (descricao, valor, categoria, mes_referencia, ano_referencia, pessoa_id, receita_extra_id)
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """,
        (descricao, valor, categoria, mes, ano, pessoa_id, receita_extra_id),
    )
    conn.commit()
    conn.close()


def listar_gastos_pix(mes: int, ano: int) -> List[GastoPix]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, descricao, valor, categoria, mes_referencia, ano_referencia, pessoa_id, receita_extra_id
        FROM gastos_pix
        WHERE mes_referencia = ? AND ano_referencia = ?
        ORDER BY id DESC;
        """,
        (mes, ano),
    )
    rows = cur.fetchall()
    conn.close()
    return [GastoPix(**dict(r)) for r in rows]


def calcular_totais_gastos_pix(mes: int, ano: int) -> Dict[str, float]:
    gastos = listar_gastos_pix(mes, ano)
    total_meu = sum(g.valor for g in gastos if g.pessoa_id is None)
    total_terceiros = sum(g.valor for g in gastos if g.pessoa_id is not None)
    return {
        "total_meu": total_meu,
        "total_terceiros": total_terceiros,
        "total_geral": total_meu + total_terceiros,
    }


def calcular_totais_gastos_pix_por_pessoa(mes: int, ano: int) -> Dict[int, float]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT pessoa_id, COALESCE(SUM(valor), 0) AS total
        FROM gastos_pix
        WHERE pessoa_id IS NOT NULL
          AND mes_referencia = ? AND ano_referencia = ?
        GROUP BY pessoa_id;
        """,
        (mes, ano),
    )
    rows = cur.fetchall()
    conn.close()
    return {int(r["pessoa_id"]): float(r["total"]) for r in rows}


def atualizar_gasto_pix(
    gasto_id: int,
    descricao: str,
    valor: float,
    pessoa_id: int | None,
) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE gastos_pix
        SET descricao = ?, valor = ?, pessoa_id = ?
        WHERE id = ?;
        """,
        (descricao, valor, pessoa_id, gasto_id),
    )
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def excluir_gasto_pix(gasto_id: int) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM gastos_pix WHERE id = ?;", (gasto_id,))
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok

