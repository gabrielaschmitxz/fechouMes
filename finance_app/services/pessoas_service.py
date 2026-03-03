from __future__ import annotations

from typing import Dict, List, Tuple, Optional
from datetime import date, datetime

from finance_app.database import USE_POSTGRES, get_connection
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


def salvar_desconto_manual_pessoa(
    pessoa_id: int,
    valor: float,
    mes_referencia: int,
    ano_referencia: int,
) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO pessoas_descontos (pessoa_id, valor, mes_referencia, ano_referencia)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (pessoa_id, mes_referencia, ano_referencia)
        DO UPDATE SET valor = EXCLUDED.valor;
        """,
        (pessoa_id, float(valor), mes_referencia, ano_referencia),
    )
    conn.commit()
    conn.close()


def adicionar_desconto_manual_pessoa(
    pessoa_id: int,
    descricao: str,
    valor: float,
    mes_referencia: int,
    ano_referencia: int,
) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO pessoas_descontos_itens (pessoa_id, descricao, valor, mes_referencia, ano_referencia)
        VALUES (?, ?, ?, ?, ?);
        """,
        (pessoa_id, descricao, float(valor), mes_referencia, ano_referencia),
    )
    conn.commit()
    conn.close()


def listar_descontos_manuais_pessoa(
    pessoa_id: int, mes: int, ano: int
) -> List[Dict[str, float | int | str]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, descricao, COALESCE(valor, 0) AS valor
        FROM pessoas_descontos_itens
        WHERE pessoa_id = ? AND mes_referencia = ? AND ano_referencia = ?
        ORDER BY id DESC;
        """,
        (pessoa_id, mes, ano),
    )
    rows = cur.fetchall()
    conn.close()
    return [
        {"id": int(r["id"]), "descricao": str(r["descricao"]), "valor": float(r["valor"])}
        for r in rows
    ]


def listar_descontos_manuais_pessoa_intervalo(
    pessoa_id: int,
    mes_inicio: int,
    ano_inicio: int,
    mes_fim: int,
    ano_fim: int,
    conn=None,
) -> Dict[str, List[Dict[str, float | int | str]]]:
    """Retorna descontos por mês no formato {'YYYY-MM': [itens...]}."""
    idx_inicio = (ano_inicio * 12) + (mes_inicio - 1)
    idx_fim = (ano_fim * 12) + (mes_fim - 1)
    if idx_fim < idx_inicio:
        idx_inicio, idx_fim = idx_fim, idx_inicio

    close_conn = conn is None
    conn_local = conn or get_connection()
    cur = conn_local.cursor()
    ano_inicio_i = idx_inicio // 12
    mes_inicio_i = (idx_inicio % 12) + 1
    ano_fim_i = idx_fim // 12
    mes_fim_i = (idx_fim % 12) + 1
    if ano_inicio_i == ano_fim_i:
        cur.execute(
            """
            SELECT
                id,
                descricao,
                COALESCE(valor, 0) AS valor,
                mes_referencia,
                ano_referencia
            FROM pessoas_descontos_itens
            WHERE pessoa_id = ?
              AND ano_referencia = ?
              AND mes_referencia BETWEEN ? AND ?
            ORDER BY ano_referencia, mes_referencia, id DESC;
            """,
            (pessoa_id, ano_inicio_i, mes_inicio_i, mes_fim_i),
        )
    else:
        cur.execute(
            """
            SELECT
                id,
                descricao,
                COALESCE(valor, 0) AS valor,
                mes_referencia,
                ano_referencia
            FROM pessoas_descontos_itens
            WHERE pessoa_id = ?
              AND (
                    (ano_referencia = ? AND mes_referencia >= ?)
                 OR (ano_referencia = ? AND mes_referencia <= ?)
                 OR (ano_referencia > ? AND ano_referencia < ?)
              )
            ORDER BY ano_referencia, mes_referencia, id DESC;
            """,
            (
                pessoa_id,
                ano_inicio_i,
                mes_inicio_i,
                ano_fim_i,
                mes_fim_i,
                ano_inicio_i,
                ano_fim_i,
            ),
        )
    rows = cur.fetchall()
    if close_conn:
        conn_local.close()

    resultado: Dict[str, List[Dict[str, float | int | str]]] = {}
    for r in rows:
        mes_ref = int(r["mes_referencia"])
        ano_ref = int(r["ano_referencia"])
        chave = f"{ano_ref}-{mes_ref:02d}"
        resultado.setdefault(chave, []).append(
            {
                "id": int(r["id"]),
                "descricao": str(r["descricao"]),
                "valor": float(r["valor"]),
            }
        )
    return resultado


def excluir_desconto_manual_pessoa(desconto_id: int, pessoa_id: int) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM pessoas_descontos_itens WHERE id = ? AND pessoa_id = ?;",
        (desconto_id, pessoa_id),
    )
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def atualizar_desconto_manual_pessoa(
    desconto_id: int,
    pessoa_id: int,
    descricao: str,
    valor: float,
) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE pessoas_descontos_itens
        SET descricao = ?, valor = ?
        WHERE id = ? AND pessoa_id = ?;
        """,
        (descricao, float(valor), desconto_id, pessoa_id),
    )
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def obter_descontos_manuais_por_pessoa(mes: int, ano: int, conn=None) -> Dict[int, float]:
    close_conn = conn is None
    conn_local = conn or get_connection()
    cur = conn_local.cursor()
    totais: Dict[int, float] = {}

    cur.execute(
        """
        SELECT pessoa_id, COALESCE(SUM(valor), 0) AS valor
        FROM (
            SELECT pessoa_id, COALESCE(valor, 0) AS valor
            FROM pessoas_descontos
            WHERE mes_referencia = ? AND ano_referencia = ?
            UNION ALL
            SELECT pessoa_id, COALESCE(valor, 0) AS valor
            FROM pessoas_descontos_itens
            WHERE mes_referencia = ? AND ano_referencia = ?
        ) d
        GROUP BY pessoa_id;
        """,
        (mes, ano, mes, ano),
    )
    for r in cur.fetchall():
        pid = int(r["pessoa_id"])
        totais[pid] = float(r["valor"])

    if close_conn:
        conn_local.close()
    return totais


def atualizar_padrao_pessoa(pessoa_id: int, padrao: bool) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE pessoas SET padrao = ? WHERE id = ?;",
        (padrao, pessoa_id),
    )
    conn.commit()
    conn.close()


def _obter_nome_pessoa(cur, pessoa_id: int) -> str | None:
    cur.execute("SELECT nome FROM pessoas WHERE id = ?;", (pessoa_id,))
    row = cur.fetchone()
    if not row:
        return None
    nome = row["nome"]
    return str(nome) if nome else None


def _add_meses(mes: int, ano: int, delta: int) -> Tuple[int, int]:
    idx = (ano * 12 + (mes - 1)) + delta
    return (idx % 12) + 1, idx // 12


def _competencia_pix_proximo_mes(mes: int, ano: int) -> Tuple[int, int]:
    return _add_meses(mes, ano, 1)


def _competencia_conta_fixa(
    mes_referencia: int,
    ano_referencia: int,
    vencimento_data: object | None,
) -> Tuple[int, int]:
    if vencimento_data:
        texto = str(vencimento_data).strip()
        if texto:
            try:
                dt = date.fromisoformat(texto[:10])
                return dt.month, dt.year
            except Exception:
                pass
            for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
                try:
                    dt = datetime.strptime(texto[:10], fmt).date()
                    return dt.month, dt.year
                except Exception:
                    continue
    return int(mes_referencia), int(ano_referencia)


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
            cp.descricao AS descricao_base,
            cp.valor_parcela AS valor,
            cp.total_parcelas AS total_parcelas,
            cp.parcela_atual AS parcela_atual,
            cp.mes_inicio AS mes_inicio,
            cp.ano_inicio AS ano_inicio,
            COALESCE(q.qtd_quitadas, 0) AS qtd_quitadas
        FROM cartao_parceladas cp
        LEFT JOIN (
            SELECT
                pessoa_id,
                item_id,
                COUNT(DISTINCT (ano_referencia * 100 + mes_referencia)) AS qtd_quitadas
            FROM pagamentos_terceiros_itens
            WHERE tipo = 'cartao_parcelada'
            GROUP BY pessoa_id, item_id
        ) q
            ON q.pessoa_id = cp.pessoa_id
           AND q.item_id = cp.id
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
    base_mes = mes_cartao_referencia if mes_cartao_referencia is not None else mes_referencia
    base_ano = ano_cartao_referencia if ano_cartao_referencia is not None else ano_referencia
    idx_base = base_ano * 12 + (base_mes - 1)
    idx_ref = ano_referencia * 12 + (mes_referencia - 1)
    delta = idx_ref - idx_base
    for r in cur.fetchall():
        parcela_num = int(r["parcela_atual"]) + delta
        total_parcelas = int(r["total_parcelas"])
        restantes = max(total_parcelas - int(r["parcela_atual"]) + 1, 0)
        if int(r["qtd_quitadas"]) >= restantes:
            continue
        if parcela_num < int(r["parcela_atual"]) or parcela_num > total_parcelas:
            continue
        pendentes.append(
            {
                "tipo": "cartao_parcelada",
                "item_id": int(r["item_id"]),
                "descricao": f"Cartão parcelado: {r['descricao_base']} (parcela {parcela_num}/{total_parcelas})",
                "valor": float(r["valor"]),
            }
        )

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
          AND (
                (gp.mes_referencia < 12 AND gp.mes_referencia + 1 = ? AND gp.ano_referencia = ?)
             OR (gp.mes_referencia = 12 AND 1 = ? AND gp.ano_referencia + 1 = ?)
          )
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
        (
            pessoa_id,
            mes_referencia,
            ano_referencia,
            mes_referencia,
            ano_referencia,
            pessoa_id,
            mes_referencia,
            ano_referencia,
        ),
    )
    pendentes.extend(dict(r) for r in cur.fetchall())

    nome_pessoa = _obter_nome_pessoa(cur, pessoa_id)
    if nome_pessoa:
        cur.execute(
            """
            SELECT
                'conta_fixa' AS tipo,
                cf.id AS item_id,
                ('Conta fixa: ' || cf.nome) AS descricao,
                COALESCE(cf.valor_padrao, 0) AS valor,
                cf.mes_referencia AS mes_referencia,
                cf.ano_referencia AS ano_referencia,
                cf.vencimento_data AS vencimento_data
            FROM contas_fixas cf
            WHERE LOWER(TRIM(COALESCE(cf.desconto_pessoa_nome, ''))) = LOWER(TRIM(?))
              AND cf.status = 'Pendente'
              AND NOT EXISTS (
                  SELECT 1
                  FROM pagamentos_terceiros_itens pi
                  WHERE pi.pessoa_id = ?
                    AND pi.tipo = 'conta_fixa'
                    AND pi.item_id = cf.id
                    AND pi.mes_referencia = ?
                    AND pi.ano_referencia = ?
              );
            """,
            (
                nome_pessoa,
                pessoa_id,
                mes_referencia,
                ano_referencia,
            ),
        )
        for r in cur.fetchall():
            m_cf, a_cf = _competencia_conta_fixa(
                int(r["mes_referencia"]),
                int(r["ano_referencia"]),
                r["vencimento_data"],
            )
            if (m_cf, a_cf) == (mes_referencia, ano_referencia):
                pendentes.append(
                    {
                        "tipo": str(r["tipo"]),
                        "item_id": int(r["item_id"]),
                        "descricao": str(r["descricao"]),
                        "valor": float(r["valor"]),
                    }
                )

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
    chave = f"{int(ano_referencia)}-{int(mes_referencia):02d}"
    mapa = listar_contas_status_pessoa_meses(
        pessoa_id,
        [(int(mes_referencia), int(ano_referencia))],
        mes_cartao_referencia,
        ano_cartao_referencia,
    )
    return mapa.get(chave, [])


def listar_contas_status_pessoa_meses(
    pessoa_id: int,
    referencias: List[Tuple[int, int]],
    mes_cartao_referencia: int | None = None,
    ano_cartao_referencia: int | None = None,
    conn=None,
) -> Dict[str, List[Dict[str, float | int | str | bool]]]:
    refs_unicas: List[Tuple[int, int]] = sorted({(int(m), int(a)) for (m, a) in referencias}, key=lambda x: (x[1], x[0]))
    if not refs_unicas:
        return {}

    mapa: Dict[str, List[Dict[str, float | int | str | bool]]] = {
        f"{a}-{m:02d}": [] for (m, a) in refs_unicas
    }
    refs_set = {(m, a) for (m, a) in refs_unicas}
    idx_min = min(a * 12 + (m - 1) for (m, a) in refs_unicas)
    idx_max = max(a * 12 + (m - 1) for (m, a) in refs_unicas)

    close_conn = conn is None
    conn_local = conn or get_connection()
    cur = conn_local.cursor()

    # Pagamentos por item/competência para marcar status pago (somente refs carregadas).
    filtros_ref = " OR ".join(
        ["(mes_referencia = ? AND ano_referencia = ?)"] * len(refs_unicas)
    )
    params_ref: List[int] = [pessoa_id]
    for m_ref, a_ref in refs_unicas:
        params_ref.extend([m_ref, a_ref])
    cur.execute(
        f"""
        SELECT tipo, item_id, mes_referencia, ano_referencia
        FROM pagamentos_terceiros_itens
        WHERE pessoa_id = ?
          AND ({filtros_ref});
        """,
        tuple(params_ref),
    )
    pagos_keys = {
        (str(r["tipo"]), int(r["item_id"]), int(r["mes_referencia"]), int(r["ano_referencia"]))
        for r in cur.fetchall()
    }

    # Parceladas ativas para a pessoa.
    cur.execute(
        """
        SELECT id, descricao, valor_parcela, total_parcelas, parcela_atual, mes_inicio, ano_inicio
        FROM cartao_parceladas
        WHERE pessoa_id = ? AND status = 'Ativa';
        """,
        (pessoa_id,),
    )
    parceladas_ativas = cur.fetchall()
    quitadas_por_item: Dict[int, int] = {}
    if parceladas_ativas:
        ids_parceladas = [int(r["id"]) for r in parceladas_ativas]
        filtros_ids = ", ".join(["?"] * len(ids_parceladas))
        cur.execute(
            f"""
            SELECT item_id, COUNT(DISTINCT (ano_referencia * 100 + mes_referencia)) AS qtd_quitadas
            FROM pagamentos_terceiros_itens
            WHERE pessoa_id = ? AND tipo = 'cartao_parcelada' AND item_id IN ({filtros_ids})
            GROUP BY item_id;
            """,
            tuple([pessoa_id, *ids_parceladas]),
        )
        quitadas_por_item = {int(r["item_id"]): int(r["qtd_quitadas"]) for r in cur.fetchall()}

    base_mes = mes_cartao_referencia if mes_cartao_referencia is not None else refs_unicas[0][0]
    base_ano = ano_cartao_referencia if ano_cartao_referencia is not None else refs_unicas[0][1]
    idx_base = base_ano * 12 + (base_mes - 1)
    for r in parceladas_ativas:
        item_id = int(r["id"])
        parcela_atual = int(r["parcela_atual"])
        total_parcelas = int(r["total_parcelas"])
        restantes = max(total_parcelas - parcela_atual + 1, 0)
        if int(quitadas_por_item.get(item_id, 0)) >= restantes:
            continue
        for m_ref, a_ref in refs_unicas:
            idx_ref = a_ref * 12 + (m_ref - 1)
            delta = idx_ref - idx_base
            parcela_num = parcela_atual + delta
            if parcela_num < parcela_atual or parcela_num > total_parcelas:
                continue
            pago = ("cartao_parcelada", item_id, m_ref, a_ref) in pagos_keys
            mapa[f"{a_ref}-{m_ref:02d}"].append(
                {
                    "tipo": "cartao_parcelada",
                    "item_id": item_id,
                    "descricao": f"Cartão parcelado: {r['descricao']} (parcela {parcela_num}/{total_parcelas})",
                    "valor": float(r["valor_parcela"]),
                    "mes_referencia": m_ref,
                    "ano_referencia": a_ref,
                    "pago": pago,
                }
            )

    # Cartão à vista nas competências carregadas.
    cur.execute(
        """
        SELECT id, descricao, valor, mes_referencia, ano_referencia
        FROM cartao_avista
        WHERE pessoa_id = ?
          AND ((ano_referencia * 12) + (mes_referencia - 1)) BETWEEN ? AND ?;
        """,
        (pessoa_id, idx_min, idx_max),
    )
    for r in cur.fetchall():
        m_ref = int(r["mes_referencia"])
        a_ref = int(r["ano_referencia"])
        chave = f"{a_ref}-{m_ref:02d}"
        if (m_ref, a_ref) not in refs_set:
            continue
        item_id = int(r["id"])
        mapa[chave].append(
            {
                "tipo": "cartao_avista",
                "item_id": item_id,
                "descricao": f"Cartão à vista: {r['descricao']}",
                "valor": float(r["valor"]),
                "mes_referencia": m_ref,
                "ano_referencia": a_ref,
                "pago": ("cartao_avista", item_id, m_ref, a_ref) in pagos_keys,
            }
        )

    # Pix/Débito: competência no mês seguinte.
    cur.execute(
        """
        SELECT id, descricao, valor, mes_referencia, ano_referencia
        FROM gastos_pix
        WHERE pessoa_id = ?
          AND ((ano_referencia * 12) + (mes_referencia - 1)) BETWEEN ? AND ?;
        """,
        (pessoa_id, idx_min - 1, idx_max - 1),
    )
    for r in cur.fetchall():
        m_comp, a_comp = _competencia_pix_proximo_mes(int(r["mes_referencia"]), int(r["ano_referencia"]))
        if (m_comp, a_comp) not in refs_set:
            continue
        chave = f"{a_comp}-{m_comp:02d}"
        item_id = int(r["id"])
        mapa[chave].append(
            {
                "tipo": "gasto_pix",
                "item_id": item_id,
                "descricao": f"Gasto Pix/Débito: {r['descricao']}",
                "valor": float(r["valor"]),
                "mes_referencia": m_comp,
                "ano_referencia": a_comp,
                "pago": ("gasto_pix", item_id, m_comp, a_comp) in pagos_keys,
            }
        )

    # Contas fixas vinculadas à pessoa.
    nome_pessoa = _obter_nome_pessoa(cur, pessoa_id)
    if nome_pessoa:
        cur.execute(
            """
            SELECT id, nome, valor_padrao, mes_referencia, ano_referencia, vencimento_data, status
            FROM contas_fixas
            WHERE LOWER(TRIM(COALESCE(desconto_pessoa_nome, ''))) = LOWER(TRIM(?))
              AND (
                    ((ano_referencia * 12) + (mes_referencia - 1)) BETWEEN ? AND ?
                 OR vencimento_data IS NOT NULL
              );
            """,
            (nome_pessoa, idx_min - 1, idx_max + 1),
        )
        for r in cur.fetchall():
            m_cf, a_cf = _competencia_conta_fixa(
                int(r["mes_referencia"]),
                int(r["ano_referencia"]),
                r["vencimento_data"],
            )
            if (m_cf, a_cf) not in refs_set:
                continue
            chave = f"{a_cf}-{m_cf:02d}"
            item_id = int(r["id"])
            pago = bool(str(r["status"]) == "Pago" or ("conta_fixa", item_id, m_cf, a_cf) in pagos_keys)
            mapa[chave].append(
                {
                    "tipo": "conta_fixa",
                    "item_id": item_id,
                    "descricao": f"Conta fixa: {r['nome']}",
                    "valor": float(r["valor_padrao"] or 0),
                    "mes_referencia": m_cf,
                    "ano_referencia": a_cf,
                    "pago": pago,
                }
            )

    if close_conn:
        conn_local.close()

    for chave, itens in mapa.items():
        for item in itens:
            item["token"] = f"{item['tipo']}:{item['item_id']}"
            item["valor"] = float(item["valor"])
            item["mes_referencia"] = int(item["mes_referencia"])
            item["ano_referencia"] = int(item["ano_referencia"])
            item["pago"] = bool(item["pago"])
        mapa[chave] = sorted(itens, key=lambda x: str(x["descricao"]).lower())
    return mapa


def _listar_contas_status_pessoa_legacy(
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
            cp.descricao AS descricao_base,
            cp.valor_parcela AS valor,
            cp.total_parcelas AS total_parcelas,
            cp.parcela_atual AS parcela_atual,
            cp.mes_inicio AS mes_inicio,
            cp.ano_inicio AS ano_inicio,
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
            ) AS pago,
            COALESCE(q.qtd_quitadas, 0) AS qtd_quitadas
        FROM cartao_parceladas cp
        LEFT JOIN (
            SELECT
                pessoa_id,
                item_id,
                COUNT(DISTINCT (ano_referencia * 100 + mes_referencia)) AS qtd_quitadas
            FROM pagamentos_terceiros_itens
            WHERE tipo = 'cartao_parcelada'
            GROUP BY pessoa_id, item_id
        ) q
            ON q.pessoa_id = cp.pessoa_id
           AND q.item_id = cp.id
        WHERE cp.pessoa_id = ?
          AND cp.status = 'Ativa';
        """,
        (
            mes_referencia,
            ano_referencia,
            pessoa_id,
            mes_referencia,
            ano_referencia,
            pessoa_id,
        ),
    )
    base_mes = mes_cartao_referencia if mes_cartao_referencia is not None else mes_referencia
    base_ano = ano_cartao_referencia if ano_cartao_referencia is not None else ano_referencia
    idx_base = base_ano * 12 + (base_mes - 1)
    idx_ref = ano_referencia * 12 + (mes_referencia - 1)
    delta = idx_ref - idx_base
    for r in cur.fetchall():
        parcela_atual = int(r["parcela_atual"])
        total_parcelas = int(r["total_parcelas"])
        restantes = max(total_parcelas - parcela_atual + 1, 0)
        if int(r["qtd_quitadas"]) >= restantes:
            continue
        parcela_num = parcela_atual + delta
        if parcela_num < parcela_atual or parcela_num > total_parcelas:
            continue
        contas.append(
            {
                "tipo": "cartao_parcelada",
                "item_id": int(r["item_id"]),
                "descricao": f"Cartão parcelado: {r['descricao_base']} (parcela {parcela_num}/{total_parcelas})",
                "valor": float(r["valor"]),
                "mes_referencia": int(r["mes_referencia"]),
                "ano_referencia": int(r["ano_referencia"]),
                "pago": bool(r["pago"]),
            }
        )

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
            CASE WHEN gp.mes_referencia = 12 THEN 1 ELSE gp.mes_referencia + 1 END AS mes_referencia,
            CASE WHEN gp.mes_referencia = 12 THEN gp.ano_referencia + 1 ELSE gp.ano_referencia END AS ano_referencia,
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
          AND (
                (gp.mes_referencia < 12 AND gp.mes_referencia + 1 = ? AND gp.ano_referencia = ?)
             OR (gp.mes_referencia = 12 AND 1 = ? AND gp.ano_referencia + 1 = ?)
          );
        """,
        (
            pessoa_id,
            mes_referencia,
            ano_referencia,
            pessoa_id,
            mes_referencia,
            ano_referencia,
            mes_referencia,
            ano_referencia,
        ),
    )
    contas.extend(dict(r) for r in cur.fetchall())

    nome_pessoa = _obter_nome_pessoa(cur, pessoa_id)
    if nome_pessoa:
        cur.execute(
            """
            SELECT
                'conta_fixa' AS tipo,
                cf.id AS item_id,
                ('Conta fixa: ' || cf.nome) AS descricao,
                COALESCE(cf.valor_padrao, 0) AS valor,
                cf.mes_referencia AS mes_referencia_db,
                cf.ano_referencia AS ano_referencia_db,
                cf.vencimento_data AS vencimento_data,
                (cf.status = 'Pago' OR EXISTS (
                    SELECT 1
                    FROM pagamentos_terceiros_itens pi
                    WHERE pi.pessoa_id = ?
                      AND pi.tipo = 'conta_fixa'
                      AND pi.item_id = cf.id
                      AND pi.mes_referencia = ?
                      AND pi.ano_referencia = ?
                )) AS pago
            FROM contas_fixas cf
            WHERE LOWER(TRIM(COALESCE(cf.desconto_pessoa_nome, ''))) = LOWER(TRIM(?));
            """,
            (
                pessoa_id,
                mes_referencia,
                ano_referencia,
                nome_pessoa,
            ),
        )
        for r in cur.fetchall():
            m_cf, a_cf = _competencia_conta_fixa(
                int(r["mes_referencia_db"]),
                int(r["ano_referencia_db"]),
                r["vencimento_data"],
            )
            if (m_cf, a_cf) == (mes_referencia, ano_referencia):
                contas.append(
                    {
                        "tipo": str(r["tipo"]),
                        "item_id": int(r["item_id"]),
                        "descricao": str(r["descricao"]),
                        "valor": float(r["valor"]),
                        "mes_referencia": mes_referencia,
                        "ano_referencia": ano_referencia,
                        "pago": bool(r["pago"]),
                    }
                )

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
    if USE_POSTGRES:
        cur.execute(
            """
            INSERT INTO pagamentos_terceiros
            (pessoa_id, valor, descricao, mes_referencia, ano_referencia)
            VALUES (?, ?, ?, ?, ?)
            RETURNING id;
            """,
            (pessoa_id, total, descricao, mes_referencia, ano_referencia),
        )
        pagamento_id = int(cur.fetchone()["id"])
    else:
        cur.execute(
            """
            INSERT INTO pagamentos_terceiros
            (pessoa_id, valor, descricao, mes_referencia, ano_referencia)
            VALUES (?, ?, ?, ?, ?);
            """,
            (pessoa_id, total, descricao, mes_referencia, ano_referencia),
        )
        pagamento_id = int(cur.lastrowid)

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
        if str(item["tipo"]) == "conta_fixa":
            cur.execute(
                "UPDATE contas_fixas SET status = 'Pago' WHERE id = ?;",
                (int(item["item_id"]),),
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


def calcular_totais_por_pessoa(
    mes: int,
    ano: int,
    mes_cartao_referencia: int | None = None,
    ano_cartao_referencia: int | None = None,
) -> Dict[int, Dict[str, float]]:
    """Retorna dicionÃ¡rio {pessoa_id: {'total_mes': ..., 'total_pago': ..., 'saldo_pendente': ...}}."""
    conn = get_connection()
    cur = conn.cursor()

    totals: Dict[int, Dict[str, float]] = {}

    competencias_cartao = {(mes, ano)}
    if (
        mes_cartao_referencia is not None
        and ano_cartao_referencia is not None
        and (mes_cartao_referencia, ano_cartao_referencia) != (mes, ano)
    ):
        competencias_cartao.add((mes_cartao_referencia, ano_cartao_referencia))
    idx_ref = int(ano) * 12 + (int(mes) - 1)

    # Chaves pagas do mês alvo (reutilizado no cálculo de pago).
    cur.execute(
        """
        SELECT pessoa_id, tipo, item_id
        FROM pagamentos_terceiros_itens
        WHERE mes_referencia = ? AND ano_referencia = ?;
        """,
        (mes, ano),
    )
    pagos_mes_keys = {
        (int(r["pessoa_id"]), str(r["tipo"]), int(r["item_id"]))
        for r in cur.fetchall()
    }

    # Parceladas ativas (carrega uma vez e reutiliza no cálculo de total e pago).
    cur.execute(
        """
        SELECT
            cp.id,
            cp.pessoa_id,
            cp.valor_parcela,
            cp.total_parcelas,
            cp.parcela_atual,
            cp.mes_inicio,
            cp.ano_inicio
        FROM cartao_parceladas cp
        WHERE cp.pessoa_id IS NOT NULL
          AND cp.status = 'Ativa';
        """
    )
    parceladas_ativas = cur.fetchall()
    quitadas_por_item_pessoa: Dict[Tuple[int, int], int] = {}
    if parceladas_ativas:
        ids_parceladas = [int(r["id"]) for r in parceladas_ativas]
        filtros_ids = ", ".join(["?"] * len(ids_parceladas))
        cur.execute(
            f"""
            SELECT pessoa_id, item_id, COUNT(DISTINCT (ano_referencia * 100 + mes_referencia)) AS qtd_quitadas
            FROM pagamentos_terceiros_itens
            WHERE tipo = 'cartao_parcelada'
              AND item_id IN ({filtros_ids})
            GROUP BY pessoa_id, item_id;
            """,
            tuple(ids_parceladas),
        )
        quitadas_por_item_pessoa = {
            (int(r["pessoa_id"]), int(r["item_id"])): int(r["qtd_quitadas"])
            for r in cur.fetchall()
        }

    # Parceladas: soma apenas quando houver parcela correspondente ao(s) mês(es) em foco.
    for row in parceladas_ativas:
        pessoa_id = row["pessoa_id"]
        if pessoa_id is None:
            continue
        parcela_atual = int(row["parcela_atual"])
        total_parcelas = int(row["total_parcelas"])
        restantes = max(total_parcelas - parcela_atual + 1, 0)
        if int(quitadas_por_item_pessoa.get((int(pessoa_id), int(row["id"])), 0)) >= restantes:
            continue
        idx_inicio = int(row["ano_inicio"]) * 12 + (int(row["mes_inicio"]) - 1)

        conta_no_mes = False
        for mes_ref, ano_ref in competencias_cartao:
            idx_ref = int(ano_ref) * 12 + (int(mes_ref) - 1)
            delta = idx_ref - idx_inicio
            parcela_num = parcela_atual + delta
            if parcela_atual <= parcela_num <= total_parcelas:
                conta_no_mes = True
                break

        if conta_no_mes:
            totals.setdefault(pessoa_id, {"total_mes": 0.0, "total_pago": 0.0})
            totals[pessoa_id]["total_mes"] += float(row["valor_parcela"])
    filtros_cartao = " OR ".join(
        ["(mes_referencia = ? AND ano_referencia = ?)"] * len(competencias_cartao)
    )
    params_cartao: List[int] = []
    for mes_ref, ano_ref in sorted(competencias_cartao):
        params_cartao.extend([mes_ref, ano_ref])
    cur.execute(
        f"""
        SELECT id, pessoa_id, valor, mes_referencia, ano_referencia
        FROM cartao_avista
        WHERE pessoa_id IS NOT NULL
          AND ({filtros_cartao});
        """,
        tuple(params_cartao),
    )
    avista_rows = cur.fetchall()
    for row in avista_rows:
        pessoa_id = row["pessoa_id"]
        totals.setdefault(pessoa_id, {"total_mes": 0.0, "total_pago": 0.0})
        totals[pessoa_id]["total_mes"] += float(row["valor"])

    cur.execute(
        """
        SELECT id, pessoa_id, valor, mes_referencia, ano_referencia
        FROM gastos_pix
        WHERE pessoa_id IS NOT NULL
          AND (
                (mes_referencia < 12 AND mes_referencia + 1 = ? AND ano_referencia = ?)
             OR (mes_referencia = 12 AND 1 = ? AND ano_referencia + 1 = ?)
          );
        """,
        (mes, ano, mes, ano),
    )
    pix_rows = cur.fetchall()
    for row in pix_rows:
        pessoa_id = row["pessoa_id"]
        totals.setdefault(pessoa_id, {"total_mes": 0.0, "total_pago": 0.0})
        totals[pessoa_id]["total_mes"] += float(row["valor"])
    cur.execute(
        """
        SELECT
            p.id AS pessoa_id,
            COALESCE(cf.valor_padrao, 0) AS valor_padrao,
            cf.id AS conta_id,
            cf.mes_referencia,
            cf.ano_referencia,
            cf.vencimento_data,
            cf.status
        FROM pessoas p
        JOIN contas_fixas cf
          ON LOWER(TRIM(COALESCE(cf.desconto_pessoa_nome, ''))) = LOWER(TRIM(p.nome))
        WHERE COALESCE(cf.valor_padrao, 0) > 0
          AND (
                ((cf.ano_referencia * 12) + (cf.mes_referencia - 1)) BETWEEN ? AND ?
             OR cf.vencimento_data IS NOT NULL
          );
        """
        ,
        (idx_ref - 1, idx_ref + 1),
    )
    contas_fixas_vinculadas = cur.fetchall()
    for row in contas_fixas_vinculadas:
        mes_cf, ano_cf = _competencia_conta_fixa(
            int(row["mes_referencia"]),
            int(row["ano_referencia"]),
            row["vencimento_data"],
        )
        if (mes_cf, ano_cf) != (mes, ano):
            continue
        pessoa_id = row["pessoa_id"]
        totals.setdefault(pessoa_id, {"total_mes": 0.0, "total_pago": 0.0})
        totals[pessoa_id]["total_mes"] += float(row["valor_padrao"])

    descontos_manuais = obter_descontos_manuais_por_pessoa(mes, ano, conn=conn)
    for pessoa_id, valor_desc in descontos_manuais.items():
        totals.setdefault(pessoa_id, {"total_mes": 0.0, "total_pago": 0.0})
        totals[pessoa_id]["total_mes"] -= float(valor_desc)
        if float(totals[pessoa_id]["total_mes"]) < 0:
            totals[pessoa_id]["total_mes"] = 0.0

    # Total pago em lote para evitar N consultas (uma por pessoa) na tela de cadastro.
    total_pago_por_pessoa: Dict[int, float] = {}
    base_mes = mes_cartao_referencia if mes_cartao_referencia is not None else mes
    base_ano = ano_cartao_referencia if ano_cartao_referencia is not None else ano
    idx_base = int(base_ano) * 12 + (int(base_mes) - 1)

    def _add_pago(pid: int, valor: float) -> None:
        total_pago_por_pessoa[pid] = float(total_pago_por_pessoa.get(pid, 0.0)) + float(valor)

    for row in avista_rows:
        pid = int(row["pessoa_id"])
        item_id = int(row["id"])
        if int(row["mes_referencia"]) == int(mes) and int(row["ano_referencia"]) == int(ano):
            if (pid, "cartao_avista", item_id) in pagos_mes_keys:
                _add_pago(pid, float(row["valor"]))

    for row in pix_rows:
        pid = int(row["pessoa_id"])
        item_id = int(row["id"])
        if (pid, "gasto_pix", item_id) in pagos_mes_keys:
            _add_pago(pid, float(row["valor"]))

    # Parceladas pagas no mês alvo (reaproveita carga de parceladas + mapa de quitadas).
    for row in parceladas_ativas:
        pid = int(row["pessoa_id"])
        item_id = int(row["id"])
        if (pid, "cartao_parcelada", item_id) not in pagos_mes_keys:
            continue
        parcela_atual = int(row["parcela_atual"])
        total_parcelas = int(row["total_parcelas"])
        restantes = max(total_parcelas - parcela_atual + 1, 0)
        if int(quitadas_por_item_pessoa.get((pid, item_id), 0)) >= restantes:
            continue
        delta = idx_ref - idx_base
        parcela_num = parcela_atual + delta
        if parcela_num < parcela_atual or parcela_num > total_parcelas:
            continue
        _add_pago(pid, float(row["valor_parcela"]))

    # Conta fixa paga no mês alvo (status ou item pago), respeitando competência por vencimento.
    for row in contas_fixas_vinculadas:
        mes_cf, ano_cf = _competencia_conta_fixa(
            int(row["mes_referencia"]),
            int(row["ano_referencia"]),
            row["vencimento_data"],
        )
        if (mes_cf, ano_cf) != (mes, ano):
            continue
        pid = int(row["pessoa_id"])
        conta_id = int(row["conta_id"])
        status_pago = str(row["status"]) == "Pago"
        pago_por_item = (pid, "conta_fixa", conta_id) in pagos_mes_keys
        if status_pago or pago_por_item:
            _add_pago(pid, float(row["valor_padrao"]))

    conn.close()

    for pessoa_id, total_pago_real in total_pago_por_pessoa.items():
        totals.setdefault(pessoa_id, {"total_mes": 0.0, "total_pago": 0.0})
        totals[pessoa_id]["total_pago"] = float(total_pago_real)

    # Calcula saldo pendente
    for pessoa_id, info in totals.items():
        if float(info["total_pago"]) > float(info["total_mes"]):
            info["total_pago"] = float(info["total_mes"])
        info["saldo_pendente"] = max(float(info["total_mes"]) - float(info["total_pago"]), 0.0)

    return totals


def calcular_totais_gerais_terceiros(
    mes: int,
    ano: int,
    mes_cartao_referencia: int | None = None,
    ano_cartao_referencia: int | None = None,
) -> Tuple[float, float, float]:
    totais = calcular_totais_por_pessoa(mes, ano, mes_cartao_referencia, ano_cartao_referencia)
    total_mes = sum(info["total_mes"] for info in totais.values())
    total_pago = sum(info["total_pago"] for info in totais.values())
    saldo_pendente = total_mes - total_pago
    return total_mes, total_pago, saldo_pendente


def listar_previsao_contas_por_mes_pessoa(
    pessoa_id: int,
    mes_referencia: int,
    ano_referencia: int,
    mes_cartao_referencia: int | None = None,
    ano_cartao_referencia: int | None = None,
    meses_a_frente: int = 12,
    conn=None,
) -> Dict[str, object]:
    """Resumo de contas por mês (inclui meses futuros para ajudar quitação total)."""
    close_conn = conn is None
    conn_local = conn or get_connection()
    cur = conn_local.cursor()
    nome_pessoa = _obter_nome_pessoa(cur, pessoa_id)
    if not nome_pessoa:
        if close_conn:
            conn_local.close()
        return {"meses": [], "total_geral": 0.0}

    base_mes = mes_cartao_referencia if mes_cartao_referencia is not None else mes_referencia
    base_ano = ano_cartao_referencia if ano_cartao_referencia is not None else ano_referencia
    inicio_idx = ano_referencia * 12 + (mes_referencia - 1)
    fim_mes, fim_ano = _add_meses(base_mes, base_ano, meses_a_frente)
    fim_idx = fim_ano * 12 + (fim_mes - 1)

    mapa: Dict[Tuple[int, int], Dict[str, object]] = {}

    def add_item(mes: int, ano: int, descricao: str, valor: float) -> None:
        idx = ano * 12 + (mes - 1)
        if idx < inicio_idx or idx > fim_idx:
            return
        chave = (ano, mes)
        bucket = mapa.setdefault(chave, {"mes": mes, "ano": ano, "total": 0.0, "itens": []})
        bucket["total"] = float(bucket["total"]) + float(valor)
        bucket["itens"].append({"descricao": descricao, "valor": float(valor)})

    # Cartão à vista (faixa mês atual -> meses futuros)
    cur.execute(
        """
        SELECT descricao, valor, mes_referencia, ano_referencia
        FROM cartao_avista
        WHERE pessoa_id = ?
          AND ((ano_referencia * 12) + (mes_referencia - 1)) BETWEEN ? AND ?;
        """,
        (pessoa_id, inicio_idx, fim_idx),
    )
    for r in cur.fetchall():
        add_item(
            int(r["mes_referencia"]),
            int(r["ano_referencia"]),
            f"Cartão à vista: {r['descricao']}",
            float(r["valor"]),
        )

    # Gastos pix por competência
    cur.execute(
        """
        SELECT descricao, valor, mes_referencia, ano_referencia
        FROM gastos_pix
        WHERE pessoa_id = ?
          AND ((ano_referencia * 12) + (mes_referencia - 1)) BETWEEN ? AND ?;
        """,
        (pessoa_id, inicio_idx - 1, fim_idx - 1),
    )
    for r in cur.fetchall():
        mes_comp, ano_comp = _competencia_pix_proximo_mes(
            int(r["mes_referencia"]),
            int(r["ano_referencia"]),
        )
        add_item(
            mes_comp,
            ano_comp,
            f"Gasto Pix/Débito: {r['descricao']}",
            float(r["valor"]),
        )

    # Parceladas: projeta parcelas restantes mês a mês
    cur.execute(
        """
        SELECT
            cp.id,
            cp.descricao,
            cp.valor_parcela,
            cp.total_parcelas,
            cp.parcela_atual,
            COALESCE(q.qtd_quitadas, 0) AS qtd_quitadas
        FROM cartao_parceladas cp
        LEFT JOIN (
            SELECT
                pessoa_id,
                item_id,
                COUNT(DISTINCT (ano_referencia * 100 + mes_referencia)) AS qtd_quitadas
            FROM pagamentos_terceiros_itens
            WHERE tipo = 'cartao_parcelada'
            GROUP BY pessoa_id, item_id
        ) q
            ON q.pessoa_id = cp.pessoa_id
           AND q.item_id = cp.id
        WHERE cp.pessoa_id = ? AND cp.status = 'Ativa';
        """,
        (pessoa_id,),
    )
    for r in cur.fetchall():
        valor = float(r["valor_parcela"])
        total_parcelas = int(r["total_parcelas"])
        parcela_atual = int(r["parcela_atual"])
        restantes = max(total_parcelas - parcela_atual + 1, 0)
        if int(r["qtd_quitadas"]) >= restantes:
            continue
        for off in range(restantes):
            mes_i, ano_i = _add_meses(base_mes, base_ano, off)
            parcela_num = parcela_atual + off
            add_item(
                mes_i,
                ano_i,
                f"Cartão parcelado: {r['descricao']} (parcela {parcela_num}/{total_parcelas})",
                valor,
            )

    # Contas fixas vinculadas à pessoa (usa vencimento_data quando existir)
    cur.execute(
        """
        SELECT nome, valor_padrao, mes_referencia, ano_referencia, vencimento_data, status
        FROM contas_fixas
        WHERE LOWER(COALESCE(desconto_pessoa_nome, '')) = LOWER(?)
          AND COALESCE(valor_padrao, 0) > 0
          AND status = 'Pendente'
          AND (
                ((ano_referencia * 12) + (mes_referencia - 1)) BETWEEN ? AND ?
             OR vencimento_data IS NOT NULL
          );
        """,
        (nome_pessoa, inicio_idx - 1, fim_idx + 1),
    )
    for r in cur.fetchall():
        mes_c = int(r["mes_referencia"])
        ano_c = int(r["ano_referencia"])
        venc = r.get("vencimento_data") if hasattr(r, "get") else r["vencimento_data"]
        if venc:
            try:
                dt = date.fromisoformat(str(venc))
                mes_c, ano_c = dt.month, dt.year
            except Exception:
                pass
        add_item(mes_c, ano_c, f"Conta fixa: {r['nome']}", float(r["valor_padrao"]))

    if close_conn:
        conn_local.close()

    meses = sorted(mapa.values(), key=lambda x: (int(x["ano"]), int(x["mes"])))
    total_geral = sum(float(m["total"]) for m in meses)
    return {"meses": meses, "total_geral": total_geral}

