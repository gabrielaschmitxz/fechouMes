from __future__ import annotations

from calendar import monthrange
from datetime import date
from typing import List, Tuple, Dict

from finance_app.database import get_connection
from finance_app.models import ContaFixa

_CATEGORIAS_CASA_RECORRENTES = {"energia", "gás", "gas", "aluguel", "telefone", "internet"}

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


def _indice_competencia(mes: int, ano: int) -> int:
    return (int(ano) * 12) + (int(mes) - 1)


def _competencias_ate_data_fim(mes: int, ano: int, data_fim: str | None) -> List[Tuple[int, int]]:
    if not data_fim:
        return [(int(mes), int(ano))]
    try:
        dt_fim = date.fromisoformat(data_fim)
    except ValueError:
        return [(int(mes), int(ano))]

    idx_inicio = _indice_competencia(mes, ano)
    idx_fim = _indice_competencia(dt_fim.month, dt_fim.year)
    if idx_fim < idx_inicio:
        return [(int(mes), int(ano))]

    competencias: List[Tuple[int, int]] = []
    for idx in range(idx_inicio, idx_fim + 1):
        competencias.append(((idx % 12) + 1, idx // 12))
    return competencias


def _vencimento_data_competencia(vencimento_data: str | None, mes: int, ano: int) -> str | None:
    if not vencimento_data:
        return None
    try:
        dt_base = date.fromisoformat(vencimento_data)
    except ValueError:
        return None
    dia = min(dt_base.day, monthrange(int(ano), int(mes))[1])
    return date(int(ano), int(mes), dia).isoformat()


def _categoria_casa_recorrente(categoria: str | None) -> bool:
    return (categoria or "").strip().lower() in _CATEGORIAS_CASA_RECORRENTES


def _valor_conta_casa_competencia(
    categoria: str | None,
    valor_padrao: float | None,
    mes: int | None = None,
    ano: int | None = None,
) -> float | None:
    categoria_normalizada = (categoria or "").strip().lower()
    if categoria_normalizada in {"gás", "gas"}:
        return 0.0
    if (
        categoria_normalizada == "energia"
        and mes is not None
        and ano is not None
        and _indice_competencia(int(mes), int(ano)) >= _indice_competencia(5, 2026)
    ):
        return 0.0
    return valor_padrao


def _remover_duplicatas_contas_casa_competencia(cur, mes: int, ano: int) -> None:
    cur.execute(
        """
        SELECT MIN(id) AS id_manter, nome, COALESCE(categoria, '') AS categoria,
               COALESCE(desconto_pessoa_nome, '') AS desconto_pessoa_nome,
               COALESCE(CAST(vencimento_data AS TEXT), '') AS vencimento_data,
               COALESCE(valor_padrao, 0) AS valor_padrao,
               COUNT(*) AS qtd
        FROM contas_fixas
        WHERE mes_referencia = ? AND ano_referencia = ?
          AND LOWER(COALESCE(categoria, '')) IN ('energia', 'gás', 'gas', 'aluguel', 'telefone', 'internet')
        GROUP BY nome, COALESCE(categoria, ''), COALESCE(desconto_pessoa_nome, ''),
                 COALESCE(CAST(vencimento_data AS TEXT), ''), COALESCE(valor_padrao, 0)
        HAVING COUNT(*) > 1;
        """,
        (int(mes), int(ano)),
    )
    grupos = cur.fetchall()
    for grupo in grupos:
        cur.execute(
            """
            DELETE FROM contas_fixas
            WHERE mes_referencia = ? AND ano_referencia = ?
              AND id <> ?
              AND nome = ?
              AND COALESCE(categoria, '') = ?
              AND COALESCE(desconto_pessoa_nome, '') = ?
              AND COALESCE(CAST(vencimento_data AS TEXT), '') = ?
              AND COALESCE(valor_padrao, 0) = ?;
            """,
            (
                int(mes),
                int(ano),
                int(grupo["id_manter"]),
                grupo["nome"],
                grupo["categoria"],
                grupo["desconto_pessoa_nome"],
                grupo["vencimento_data"],
                grupo["valor_padrao"],
            ),
        )


def _inserir_conta_fixa(
    cur,
    nome: str,
    categoria: str | None,
    valor_padrao: float | None,
    desconto_pessoa_nome: str | None,
    desconto_origem: str | None,
    desconto_receita_extra_id: int | None,
    vencimento_data: str | None,
    vencimento_dia: int | None,
    mes: int,
    ano: int,
    data_fim: str | None,
    status: str = "Pendente",
) -> None:
    cur.execute(
        """
        INSERT INTO contas_fixas
        (nome, categoria, valor_padrao, desconto_pessoa_nome, desconto_origem, desconto_receita_extra_id, desconto_aplicado,
         vencimento_dia, vencimento_data, mes_referencia, ano_referencia, status, data_fim)
        VALUES (?, ?, ?, ?, ?, ?, FALSE, ?, ?, ?, ?, ?, ?);
        """,
        (
            nome,
            categoria,
            valor_padrao,
            desconto_pessoa_nome,
            desconto_origem,
            desconto_receita_extra_id,
            vencimento_dia,
            vencimento_data,
            int(mes),
            int(ano),
            status,
            data_fim,
        ),
    )
def gerar_contas_fixas_mes_atual(conn=None) -> None:
    """Gera automaticamente, no início do mês, as contas fixas baseadas no mês anterior.

    Regra de data_fim: se a data_fim for anterior ao primeiro dia do mês atual, não gera.
    """
    mes_atual, ano_atual = mes_ano_atual()
    if mes_atual == 1:
        mes_anterior, ano_anterior = 12, ano_atual - 1
    else:
        mes_anterior, ano_anterior = mes_atual - 1, ano_atual

    close_conn = conn is None
    conn_local = conn or get_connection()
    cur = conn_local.cursor()

    # Verifica se já existem contas para o mês atual
    cur.execute(
        """
        SELECT COUNT(*) AS c FROM contas_fixas
        WHERE mes_referencia = ? AND ano_referencia = ?;
        """,
        (mes_atual, ano_atual),
    )
    if cur.fetchone()["c"] > 0:
        if close_conn:
            conn_local.close()
        return

    # Pega a última versão de cada conta antes do mês atual.
    cur.execute(
        """
        SELECT c1.nome, c1.categoria, c1.valor_padrao, c1.desconto_pessoa_nome,
               c1.vencimento_dia, c1.vencimento_data, c1.data_fim
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
                # Não gerar para meses após a data_fim
                continue

        cur.execute(
            """
            INSERT INTO contas_fixas
            (nome, categoria, valor_padrao, desconto_pessoa_nome, desconto_origem, desconto_receita_extra_id, desconto_aplicado,
             vencimento_dia, vencimento_data, mes_referencia, ano_referencia, status, data_fim)
            VALUES (?, ?, ?, ?, ?, ?, FALSE, ?, ?, ?, ?, 'Pendente', ?);
            """,
            (
                r["nome"],
                r["categoria"],
                r["valor_padrao"],
                r["desconto_pessoa_nome"],
                None,
                None,
                r["vencimento_dia"],
                r["vencimento_data"],
                mes_atual,
                ano_atual,
                data_fim,
            ),
        )

    conn_local.commit()
    if close_conn:
        conn_local.close()


def garantir_contas_casa_competencia(mes: int, ano: int, conn=None) -> None:
    close_conn = conn is None
    conn_local = conn or get_connection()
    cur = conn_local.cursor()
    idx_alvo = _indice_competencia(mes, ano)
    cur.execute(
        """
        SELECT c1.nome, c1.categoria, c1.valor_padrao, c1.desconto_pessoa_nome,
               c1.vencimento_dia, c1.vencimento_data, c1.data_fim
        FROM contas_fixas c1
        INNER JOIN (
            SELECT nome, MAX(ano_referencia * 12 + (mes_referencia - 1)) AS idx_ref
            FROM contas_fixas
            WHERE (ano_referencia * 12 + (mes_referencia - 1)) <= ?
              AND LOWER(COALESCE(categoria, '')) IN ('energia', 'gás', 'gas', 'aluguel', 'telefone', 'internet')
            GROUP BY nome
        ) ult
            ON ult.nome = c1.nome
           AND ((c1.ano_referencia * 12) + (c1.mes_referencia - 1)) = ult.idx_ref
        ORDER BY c1.nome;
        """,
        (idx_alvo,),
    )
    rows = cur.fetchall()

    for r in rows:
        nome = r["nome"]
        categoria = r["categoria"]
        if not _categoria_casa_recorrente(categoria):
            continue
        cur.execute(
            """
            SELECT 1
            FROM contas_fixas
            WHERE nome = ? AND mes_referencia = ? AND ano_referencia = ?
            LIMIT 1;
            """,
            (nome, int(mes), int(ano)),
        )
        if cur.fetchone():
            continue

        data_fim = r["data_fim"]
        if data_fim:
            try:
                fim = date.fromisoformat(str(data_fim))
            except ValueError:
                fim = None
            if fim and _indice_competencia(fim.month, fim.year) < idx_alvo:
                continue

        vencimento_base = r["vencimento_data"]
        if vencimento_base is not None:
            vencimento_base = str(vencimento_base)
        vencimento_comp = _vencimento_data_competencia(vencimento_base, mes, ano)
        valor_comp = _valor_conta_casa_competencia(categoria, r["valor_padrao"], mes, ano)
        _inserir_conta_fixa(
            cur,
            nome,
            categoria,
            valor_comp,
            r["desconto_pessoa_nome"],
            None,
            None,
            vencimento_comp,
            date.fromisoformat(vencimento_comp).day if vencimento_comp else r["vencimento_dia"],
            mes,
            ano,
            data_fim,
        )

    cur.execute(
        """
        SELECT 1
        FROM contas_fixas
        WHERE mes_referencia = ? AND ano_referencia = ?
          AND LOWER(COALESCE(categoria, '')) IN ('gás', 'gas')
        LIMIT 1;
        """,
        (int(mes), int(ano)),
    )
    if not cur.fetchone():
        _inserir_conta_fixa(
            cur,
            "Gás",
            "Gás",
            0.0,
            None,
            None,
            None,
            None,
            None,
            mes,
            ano,
            None,
        )

    _remover_duplicatas_contas_casa_competencia(cur, mes, ano)

    conn_local.commit()
    if close_conn:
        conn_local.close()


def criar_conta_fixa(
    nome: str,
    categoria: str | None,
    valor_padrao: float | None,
    desconto_pessoa_nome: str | None = None,
    desconto_origem: str | None = None,
    desconto_receita_extra_id: int | None = None,
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
    desconto_pessoa_nome = (desconto_pessoa_nome or "").strip() or None
    desconto_origem = None
    desconto_receita_extra_id = None

    conn = get_connection()
    cur = conn.cursor()
    if vencimento_data:
        try:
            vencimento_dia = date.fromisoformat(vencimento_data).day
        except ValueError:
            vencimento_data = None
            vencimento_dia = None
    for mes_ref, ano_ref in _competencias_ate_data_fim(mes, ano, data_fim):
        vencimento_comp = _vencimento_data_competencia(vencimento_data, mes_ref, ano_ref)
        cur.execute(
            """
            SELECT 1
            FROM contas_fixas
            WHERE nome = ? AND mes_referencia = ? AND ano_referencia = ?
            LIMIT 1;
            """,
            (nome, int(mes_ref), int(ano_ref)),
        )
        if cur.fetchone():
            continue
        _inserir_conta_fixa(
            cur,
            nome,
            categoria,
            valor_padrao,
            desconto_pessoa_nome,
            desconto_origem,
            desconto_receita_extra_id,
            vencimento_comp,
            date.fromisoformat(vencimento_comp).day if vencimento_comp else vencimento_dia,
            mes_ref,
            ano_ref,
            data_fim,
        )
    conn.commit()
    conn.close()


def listar_contas_fixas(mes: int, ano: int, conn=None) -> List[ContaFixa]:
    close_conn = conn is None
    conn_local = conn or get_connection()
    cur = conn_local.cursor()
    cur.execute(
        """
        SELECT id, nome, categoria, valor_padrao, desconto_pessoa_nome, desconto_origem, desconto_receita_extra_id, desconto_aplicado,
               vencimento_dia, vencimento_data,
               mes_referencia, ano_referencia, status, data_fim
        FROM contas_fixas
        WHERE mes_referencia = ? AND ano_referencia = ?
        ORDER BY COALESCE(vencimento_dia, 99), nome;
        """,
        (mes, ano),
    )
    rows = cur.fetchall()
    if close_conn:
        conn_local.close()
    contas: List[ContaFixa] = []
    for r in rows:
        data = dict(r)
        data["desconto_aplicado"] = bool(data.get("desconto_aplicado"))
        contas.append(ContaFixa(**data))
    return contas


def atualizar_conta_fixa(
    conta_id: int,
    nome: str,
    categoria: str | None,
    valor_padrao: float | None,
    desconto_pessoa_nome: str | None,
    desconto_origem: str | None,
    desconto_receita_extra_id: int | None,
    vencimento_data: str | None,
    data_fim: str | None,
    mes_referencia: int | None = None,
    ano_referencia: int | None = None,
) -> bool:
    vencimento_data = _normalizar_data_iso(vencimento_data)
    data_fim = _normalizar_data_iso(data_fim)
    desconto_pessoa_nome = (desconto_pessoa_nome or "").strip() or None
    desconto_origem = None
    desconto_receita_extra_id = None

    vencimento_dia = None
    if vencimento_data:
        try:
            vencimento_dia = date.fromisoformat(vencimento_data).day
        except ValueError:
            vencimento_data = None
            vencimento_dia = None

    conn = get_connection()
    cur = conn.cursor()
    if mes_referencia is None or ano_referencia is None:
        cur.execute(
            "SELECT mes_referencia, ano_referencia FROM contas_fixas WHERE id = ?;",
            (conta_id,),
        )
        row_atual = cur.fetchone()
        if row_atual:
            mes_referencia = int(row_atual["mes_referencia"])
            ano_referencia = int(row_atual["ano_referencia"])
        else:
            mes_referencia, ano_referencia = mes_ano_atual()
    cur.execute(
        """
        UPDATE contas_fixas
        SET nome = ?,
            categoria = ?,
            valor_padrao = ?,
            desconto_pessoa_nome = ?,
            desconto_origem = ?,
            desconto_receita_extra_id = ?,
            vencimento_data = ?,
            vencimento_dia = ?,
            data_fim = ?,
            mes_referencia = ?,
            ano_referencia = ?
        WHERE id = ?;
        """,
        (
            nome,
            categoria,
            valor_padrao,
            desconto_pessoa_nome,
            desconto_origem,
            desconto_receita_extra_id,
            vencimento_data,
            vencimento_dia,
            data_fim,
            int(mes_referencia),
            int(ano_referencia),
            conta_id,
        ),
    )
    ok = cur.rowcount > 0
    if ok and data_fim:
        for mes_ref, ano_ref in _competencias_ate_data_fim(int(mes_referencia), int(ano_referencia), data_fim):
            if int(mes_ref) == int(mes_referencia) and int(ano_ref) == int(ano_referencia):
                continue
            cur.execute(
                """
                SELECT id
                FROM contas_fixas
                WHERE nome = ? AND mes_referencia = ? AND ano_referencia = ?
                LIMIT 1;
                """,
                (nome, int(mes_ref), int(ano_ref)),
            )
            row_existente = cur.fetchone()
            if row_existente:
                continue
            vencimento_comp = _vencimento_data_competencia(vencimento_data, mes_ref, ano_ref)
            _inserir_conta_fixa(
                cur,
                nome,
                categoria,
                valor_padrao,
                desconto_pessoa_nome,
                desconto_origem,
                desconto_receita_extra_id,
                vencimento_comp,
                date.fromisoformat(vencimento_comp).day if vencimento_comp else vencimento_dia,
                mes_ref,
                ano_ref,
                data_fim,
            )
    conn.commit()
    conn.close()
    return ok


def excluir_conta_fixa(conta_id: int) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, nome, categoria, desconto_pessoa_nome, vencimento_dia, vencimento_data,
               valor_padrao, mes_referencia, ano_referencia, data_fim
        FROM contas_fixas
        WHERE id = ?;
        """,
        (conta_id,),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return False

    data = dict(row)
    if data.get("data_fim"):
        cur.execute(
            """
            DELETE FROM contas_fixas
            WHERE nome = ?
              AND COALESCE(categoria, '') = COALESCE(?, '')
              AND COALESCE(desconto_pessoa_nome, '') = COALESCE(?, '')
              AND COALESCE(vencimento_dia, 0) = COALESCE(?, 0)
              AND COALESCE(valor_padrao, 0) = COALESCE(?, 0)
              AND COALESCE(CAST(data_fim AS TEXT), '') = COALESCE(CAST(? AS TEXT), '')
              AND (ano_referencia * 12 + mes_referencia) >= (? * 12 + ?);
            """,
            (
                data["nome"],
                data.get("categoria"),
                data.get("desconto_pessoa_nome"),
                data.get("vencimento_dia"),
                data.get("valor_padrao"),
                data.get("data_fim"),
                int(data["ano_referencia"]),
                int(data["mes_referencia"]),
            ),
        )
    else:
        cur.execute("DELETE FROM contas_fixas WHERE id = ?;", (conta_id,))

    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def obter_conta_fixa_por_id(conta_id: int, conn=None) -> ContaFixa | None:
    close_conn = conn is None
    conn_local = conn or get_connection()
    cur = conn_local.cursor()
    cur.execute(
        """
        SELECT id, nome, categoria, valor_padrao, desconto_pessoa_nome, desconto_origem, desconto_receita_extra_id, desconto_aplicado,
               vencimento_dia, vencimento_data, mes_referencia, ano_referencia, status, data_fim
        FROM contas_fixas
        WHERE id = ?;
        """,
        (conta_id,),
    )
    row = cur.fetchone()
    if close_conn:
        conn_local.close()
    if not row:
        return None
    data = dict(row)
    data["desconto_aplicado"] = bool(data.get("desconto_aplicado"))
    return ContaFixa(**data)


def marcar_conta_como_paga(conta_id: int) -> bool:
    from finance_app.services import pessoas_service

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE contas_fixas
        SET status = 'Pago',
            desconto_aplicado = TRUE,
            desconto_origem = NULL,
            desconto_receita_extra_id = NULL
        WHERE id = ? AND status <> 'Pago';
        """,
        (conta_id,),
    )
    ok = cur.rowcount > 0
    if ok:
        pessoas_service.sincronizar_pagamento_pessoa_conta_fixa(conta_id, conn=conn)
    conn.commit()
    conn.close()
    return ok


def desfazer_conta_como_paga(conta_id: int) -> bool:
    from finance_app.services import pessoas_service

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT status FROM contas_fixas WHERE id = ?;", (conta_id,))
    row = cur.fetchone()
    if not row or str(row["status"]) != "Pago":
        conn.close()
        return False

    pessoas_service.desfazer_pagamento_conta_fixa_sincronizado(conta_id, conn=conn)
    cur.execute(
        """
        UPDATE contas_fixas
        SET status = 'Pendente',
            desconto_aplicado = FALSE,
            desconto_origem = NULL,
            desconto_receita_extra_id = NULL
        WHERE id = ?;
        """,
        (conta_id,),
    )
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def calcular_totais_contas_fixas(
    mes: int,
    ano: int,
    contas: List[ContaFixa] | None = None,
    conn=None,
) -> Dict[str, float]:
    if contas is None:
        contas = listar_contas_fixas(mes, ano, conn=conn)
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

