from __future__ import annotations

from typing import Dict, List, Tuple, Optional

from finance_app.database import get_connection
from finance_app.models import Pessoa


def listar_pessoas(only_ativas: bool = True) -> List[Pessoa]:
    conn = get_connection()
    cur = conn.cursor()
    if only_ativas: # Removed get_cursor(conn) and used conn.cursor()
        cur.execute(
            "SELECT id, nome, ativo, padrao FROM pessoas WHERE ativo = TRUE ORDER BY LOWER(nome);"
        )
    else:
        cur.execute("SELECT id, nome, ativo, padrao FROM pessoas ORDER BY LOWER(nome);")
    rows = cur.fetchall()
    conn.close()
    return [
        Pessoa(id=r["id"], nome=r["nome"], ativo=bool(r["ativo"]), padrao=bool(r["padrao"]))
        for r in rows
    ]


def criar_pessoa(nome: str) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO pessoas (nome, ativo, padrao)
        VALUES (?, TRUE, FALSE)
        ON CONFLICT (nome) DO NOTHING;
        """,
        (nome,),
    )
    conn.commit()
    conn.close()


def ativar_desativar_pessoa(pessoa_id: int, ativo: bool) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE pessoas SET ativo = ? WHERE id = ?;",
        (ativo, pessoa_id),
    )
    conn.commit()
    conn.close()


def excluir_pessoa(pessoa_id: int) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM pessoas WHERE id = ?;", (pessoa_id,))
    conn.commit()
    conn.close()


def atualizar_pessoa(pessoa_id: int, nome: str, ativo: bool) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE pessoas SET nome = ?, ativo = ? WHERE id = ?;",
        (nome, ativo, pessoa_id),
    )
    conn.commit()
    conn.close()



def registrar_pagamento_terceiro(
    pessoa_id: int,
    valor: float,
    descricao: str,
    mes_referencia: int,
    ano_referencia: int,
) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO pagamentos_terceiros
        (pessoa_id, valor, descricao, mes_referencia, ano_referencia)
        VALUES (?, ?, ?, ?, ?);
        """,
        (pessoa_id, valor, descricao, mes_referencia, ano_referencia),
    )
    conn.commit()
    conn.close()


def atualizar_padrao_pessoa(pessoa_id: int, padrao: bool) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE pessoas SET padrao = ? WHERE id = ?;",
        (padrao, pessoa_id),
    )
    conn.commit()
    conn.close()


def listar_contas_pendentes_pessoa(
    pessoa_id: int,
    mes_referencia: int,
    ano_referencia: int,
    mes_cartao_referencia: int | None = None,
    ano_cartao_referencia: int | None = None,
) -> List[Dict[str, float | int | str]]:
    conn = get_connection()
    cur = conn.cursor()

    pendentes: List[Dict[str, float | int | str]] = []

    cur.execute(
        """
        SELECT
            'cartao_parcelada' AS tipo,
            cp.id AS item_id,
            ('Cartão parcelado: ' || cp.descricao || ' (parcela ' || cp.parcela_atual || '/' || cp.total_parcelas || ')') AS descricao,
            cp.valor_parcela AS valor
        FROM cartao_parceladas cp
        WHERE cp.pessoa_id = ?
          AND cp.status = 'Ativa'
          AND NOT EXISTS (
              SELECT 1
              FROM pagamentos_terceiros_itens pi
              WHERE pi.pessoa_id = ?
                AND pi.tipo = 'cartao_parcelada'
                AND pi.item_id = cp.id
                AND pi.mes_referencia = ?
                AND pi.ano_referencia = ?
          );
        """,
        (pessoa_id, pessoa_id, mes_referencia, ano_referencia),
    )
    pendentes.extend(dict(r) for r in cur.fetchall())

    competencias_cartao = {(mes_referencia, ano_referencia)}
    if (
        mes_cartao_referencia is not None
        and ano_cartao_referencia is not None
        and (mes_cartao_referencia, ano_cartao_referencia) != (mes_referencia, ano_referencia)
    ):
        competencias_cartao.add((mes_cartao_referencia, ano_cartao_referencia))
    filtros_cartao = " OR ".join(
        ["(ca.mes_referencia = ? AND ca.ano_referencia = ?)"] * len(competencias_cartao)
    )
    params_cartao: List[int] = [pessoa_id]
    for mes_ref, ano_ref in sorted(competencias_cartao):
        params_cartao.extend([mes_ref, ano_ref])
    params_cartao.append(pessoa_id)
    cur.execute(
        f"""
        SELECT
            'cartao_avista' AS tipo,
            ca.id AS item_id,
            ('Cartão à vista: ' || ca.descricao) AS descricao,
            ca.valor AS valor,
            ca.mes_referencia AS mes_referencia,
            ca.ano_referencia AS ano_referencia
        FROM cartao_avista ca
        WHERE ca.pessoa_id = ?
          AND ({filtros_cartao})
          AND NOT EXISTS (
              SELECT 1
              FROM pagamentos_terceiros_itens pi
              WHERE pi.pessoa_id = ?
                AND pi.tipo = 'cartao_avista'
                AND pi.item_id = ca.id
                AND pi.mes_referencia = ca.mes_referencia
                AND pi.ano_referencia = ca.ano_referencia
          );
        """,
        tuple(params_cartao),
    )
    pendentes.extend(dict(r) for r in cur.fetchall())

    cur.execute(
        """
        SELECT
            'gasto_pix' AS tipo,
            gp.id AS item_id,
            ('Gasto Pix/Débito: ' || gp.descricao) AS descricao,
            gp.valor AS valor
        FROM gastos_pix gp
        WHERE gp.pessoa_id = ?
          AND gp.mes_referencia = ?
          AND gp.ano_referencia = ?
          AND NOT EXISTS (
              SELECT 1
              FROM pagamentos_terceiros_itens pi
              WHERE pi.pessoa_id = ?
                AND pi.tipo = 'gasto_pix'
                AND pi.item_id = gp.id
                AND pi.mes_referencia = ?
                AND pi.ano_referencia = ?
          );
        """,
        (pessoa_id, mes_referencia, ano_referencia, pessoa_id, mes_referencia, ano_referencia),
    )
    pendentes.extend(dict(r) for r in cur.fetchall())

    conn.close()

    for item in pendentes:
        item["token"] = f"{item['tipo']}:{item['item_id']}"
        item["valor"] = float(item["valor"])

    return sorted(pendentes, key=lambda x: str(x["descricao"]).lower())


def listar_contas_status_pessoa(
    pessoa_id: int,
    mes_referencia: int,
    ano_referencia: int,
    mes_cartao_referencia: int | None = None,
    ano_cartao_referencia: int | None = None,
) -> List[Dict[str, float | int | str | bool]]:
    conn = get_connection()
    cur = conn.cursor()

    contas: List[Dict[str, float | int | str | bool]] = []

    cur.execute(
        """
        SELECT
            'cartao_parcelada' AS tipo,
            cp.id AS item_id,
            ('Cartão parcelado: ' || cp.descricao || ' (parcela ' || cp.parcela_atual || '/' || cp.total_parcelas || ')') AS descricao,
            cp.valor_parcela AS valor,
            ? AS mes_referencia,
            ? AS ano_referencia,
            EXISTS (
                SELECT 1
                FROM pagamentos_terceiros_itens pi
                WHERE pi.pessoa_id = ?
                  AND pi.tipo = 'cartao_parcelada'
                  AND pi.item_id = cp.id
                  AND pi.mes_referencia = ?
                  AND pi.ano_referencia = ?
            ) AS pago
        FROM cartao_parceladas cp
        WHERE cp.pessoa_id = ?
          AND cp.status = 'Ativa';
        """,
        (mes_referencia, ano_referencia, pessoa_id, mes_referencia, ano_referencia, pessoa_id),
    )
    contas.extend(dict(r) for r in cur.fetchall())

    competencias_cartao = {(mes_referencia, ano_referencia)}
    if (
        mes_cartao_referencia is not None
        and ano_cartao_referencia is not None
        and (mes_cartao_referencia, ano_cartao_referencia) != (mes_referencia, ano_referencia)
    ):
        competencias_cartao.add((mes_cartao_referencia, ano_cartao_referencia))
    filtros_cartao = " OR ".join(
        ["(ca.mes_referencia = ? AND ca.ano_referencia = ?)"] * len(competencias_cartao)
    )
    params_cartao: List[int] = [pessoa_id]
    for mes_ref, ano_ref in sorted(competencias_cartao):
        params_cartao.extend([mes_ref, ano_ref])
    params_cartao.append(pessoa_id)
    cur.execute(
        f"""
        SELECT
            'cartao_avista' AS tipo,
            ca.id AS item_id,
            ('Cartão à vista: ' || ca.descricao) AS descricao,
            ca.valor AS valor,
            ca.mes_referencia AS mes_referencia,
            ca.ano_referencia AS ano_referencia,
            EXISTS (
                SELECT 1
                FROM pagamentos_terceiros_itens pi
                WHERE pi.pessoa_id = ?
                  AND pi.tipo = 'cartao_avista'
                  AND pi.item_id = ca.id
                  AND pi.mes_referencia = ca.mes_referencia
                  AND pi.ano_referencia = ca.ano_referencia
            ) AS pago
        FROM cartao_avista ca
        WHERE ca.pessoa_id = ?
          AND ({filtros_cartao});
        """,
        tuple([params_cartao[-1]] + params_cartao[:-1]),
    )
    contas.extend(dict(r) for r in cur.fetchall())

    cur.execute(
        """
        SELECT
            'gasto_pix' AS tipo,
            gp.id AS item_id,
            ('Gasto Pix/Débito: ' || gp.descricao) AS descricao,
            gp.valor AS valor,
            gp.mes_referencia AS mes_referencia,
            gp.ano_referencia AS ano_referencia,
            EXISTS (
                SELECT 1
                FROM pagamentos_terceiros_itens pi
                WHERE pi.pessoa_id = ?
                  AND pi.tipo = 'gasto_pix'
                  AND pi.item_id = gp.id
                  AND pi.mes_referencia = ?
                  AND pi.ano_referencia = ?
            ) AS pago
        FROM gastos_pix gp
        WHERE gp.pessoa_id = ?
          AND gp.mes_referencia = ?
          AND gp.ano_referencia = ?;
        """,
        (pessoa_id, mes_referencia, ano_referencia, pessoa_id, mes_referencia, ano_referencia),
    )
    contas.extend(dict(r) for r in cur.fetchall())

    conn.close()

    for item in contas:
        item["token"] = f"{item['tipo']}:{item['item_id']}"
        item["valor"] = float(item["valor"])
        item["mes_referencia"] = int(item.get("mes_referencia", mes_referencia))
        item["ano_referencia"] = int(item.get("ano_referencia", ano_referencia))
        item["pago"] = bool(item["pago"])

    return sorted(contas, key=lambda x: str(x["descricao"]).lower())


def registrar_pagamento_terceiro_por_itens(
    pessoa_id: int,
    itens_tokens: List[str],
    mes_referencia: int,
    ano_referencia: int,
    mes_cartao_referencia: int | None = None,
    ano_cartao_referencia: int | None = None,
) -> float:
    contas = listar_contas_status_pessoa(
        pessoa_id,
        mes_referencia,
        ano_referencia,
        mes_cartao_referencia,
        ano_cartao_referencia,
    )
    mapa = {str(c["token"]): c for c in contas if not bool(c["pago"])}
    selecionadas = [mapa[t] for t in itens_tokens if t in mapa]

    if not selecionadas:
        return 0.0

    total = sum(float(c["valor"]) for c in selecionadas)
    descricao = f"Pagamento de {len(selecionadas)} conta(s) selecionada(s)"

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO pagamentos_terceiros
        (pessoa_id, valor, descricao, mes_referencia, ano_referencia)
        VALUES (?, ?, ?, ?, ?);
        """,
        (pessoa_id, total, descricao, mes_referencia, ano_referencia),
    )
    pagamento_id = cur.lastrowid

    for item in selecionadas:
        item_mes = int(item.get("mes_referencia", mes_referencia))
        item_ano = int(item.get("ano_referencia", ano_referencia))
        cur.execute(
            """
            INSERT INTO pagamentos_terceiros_itens
            (pagamento_id, pessoa_id, tipo, item_id, descricao_item, valor, mes_referencia, ano_referencia)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                pagamento_id,
                pessoa_id,
                str(item["tipo"]),
                int(item["item_id"]),
                str(item["descricao"]),
                float(item["valor"]),
                item_mes,
                item_ano,
            ),
        )

    conn.commit()
    conn.close()
    return total


def get_pessoa_by_id(pessoa_id: int) -> Optional[Pessoa]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, nome, ativo, padrao FROM pessoas WHERE id = ?;", (pessoa_id,)
    )
    row = cur.fetchone()
    conn.close()
    return (
        Pessoa(id=row["id"], nome=row["nome"], ativo=bool(row["ativo"]), padrao=bool(row["padrao"]))
        if row
        else None
    )


def calcular_totais_por_pessoa(mes: int, ano: int) -> Dict[int, Dict[str, float]]:
    """Retorna dicionÃ¡rio {pessoa_id: {'total_mes': ..., 'total_pago': ..., 'saldo_pendente': ...}}."""
    conn = get_connection()
    cur = conn.cursor()

    # Total de despesas atribuÃ­das Ã  pessoa (parceladas + Ã  vista + pix)
    cur.execute(
        """
        SELECT pessoa_id, COALESCE(SUM(valor_parcela), 0) AS total_parceladas
        FROM cartao_parceladas
        WHERE pessoa_id IS NOT NULL AND status = 'Ativa'
        GROUP BY pessoa_id;
        """
    )
    totals: Dict[int, Dict[str, float]] = {}
    for row in cur.fetchall():
        pessoa_id = row["pessoa_id"]
        totals.setdefault(pessoa_id, {"total_mes": 0.0, "total_pago": 0.0})
        totals[pessoa_id]["total_mes"] += float(row["total_parceladas"])

    cur.execute(
        """
        SELECT pessoa_id, COALESCE(SUM(valor), 0) AS total_avista
        FROM cartao_avista
        WHERE pessoa_id IS NOT NULL
          AND mes_referencia = ? AND ano_referencia = ?
        GROUP BY pessoa_id;
        """,
        (mes, ano),
    )
    for row in cur.fetchall():
        pessoa_id = row["pessoa_id"]
        totals.setdefault(pessoa_id, {"total_mes": 0.0, "total_pago": 0.0})
        totals[pessoa_id]["total_mes"] += float(row["total_avista"])

    cur.execute(
        """
        SELECT pessoa_id, COALESCE(SUM(valor), 0) AS total_pix
        FROM gastos_pix
        WHERE pessoa_id IS NOT NULL
          AND mes_referencia = ? AND ano_referencia = ?
        GROUP BY pessoa_id;
        """,
        (mes, ano),
    )
    for row in cur.fetchall():
        pessoa_id = row["pessoa_id"]
        totals.setdefault(pessoa_id, {"total_mes": 0.0, "total_pago": 0.0})
        totals[pessoa_id]["total_mes"] += float(row["total_pix"])

    # Pagamentos jÃ¡ realizados
    cur.execute(
        """
        SELECT pessoa_id, COALESCE(SUM(valor), 0) AS total_pago
        FROM pagamentos_terceiros
        WHERE mes_referencia = ? AND ano_referencia = ?
        GROUP BY pessoa_id;
        """,
        (mes, ano),
    )
    for row in cur.fetchall():
        pessoa_id = row["pessoa_id"]
        totals.setdefault(pessoa_id, {"total_mes": 0.0, "total_pago": 0.0})
        totals[pessoa_id]["total_pago"] = float(row["total_pago"])

    conn.close()

    # Calcula saldo pendente
    for pessoa_id, info in totals.items():
        info["saldo_pendente"] = info["total_mes"] - info["total_pago"]

    return totals


def calcular_totais_gerais_terceiros(mes: int, ano: int) -> Tuple[float, float, float]:
    totais = calcular_totais_por_pessoa(mes, ano)
    total_mes = sum(info["total_mes"] for info in totais.values())
    total_pago = sum(info["total_pago"] for info in totais.values())
    saldo_pendente = total_mes - total_pago
    return total_mes, total_pago, saldo_pendente

