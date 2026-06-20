from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, List, Tuple, Optional
from datetime import date, datetime

from finance_app.database import USE_POSTGRES, get_connection
from finance_app.services import gastos_service
from finance_app.models import Pessoa


def listar_pessoas(only_ativas: bool = True, conn=None) -> List[Pessoa]:
    close_conn = conn is None
    conn_local = conn or get_connection()
    cur = conn_local.cursor()
    if only_ativas: # Removed get_cursor(conn) and used conn.cursor()
        cur.execute(
            "SELECT id, nome, ativo, padrao FROM pessoas WHERE ativo = TRUE ORDER BY LOWER(nome);"
        )
    else:
        cur.execute("SELECT id, nome, ativo, padrao FROM pessoas ORDER BY LOWER(nome);")
    rows = cur.fetchall()
    if close_conn:
        conn_local.close()
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


def _indice_inicio_lancamentos_pessoa(
    cur,
    pessoa_id: int,
    nome_pessoa: str | None,
    indice_fallback: int,
    parceladas_pessoa: List[object] | None = None,
    historico_parcelas: Dict[int, Dict[str, object]] | None = None,
) -> int:
    """Menor competência (índice) com lançamento ou pagamento da pessoa."""
    candidatos = [int(indice_fallback)]

    cur.execute(
        """
        SELECT MIN((ano_referencia * 12) + (mes_referencia - 1)) AS idx
        FROM cartao_avista
        WHERE pessoa_id = ?;
        """,
        (pessoa_id,),
    )
    row = cur.fetchone()
    if row and row["idx"] is not None:
        candidatos.append(int(row["idx"]))

    if parceladas_pessoa is None:
        cur.execute(
            """
            SELECT id, mes_inicio, ano_inicio, parcela_atual, total_parcelas
            FROM cartao_parceladas
            WHERE pessoa_id = ?;
            """,
            (pessoa_id,),
        )
        parceladas_pessoa = cur.fetchall()
    if parceladas_pessoa:
        if historico_parcelas is None:
            historico_parcelas = _carregar_historico_parceladas_pessoa(
                cur, pessoa_id, parceladas_pessoa
            )
        for row in parceladas_pessoa:
            item_id = int(row["id"])
            candidatos.append(
                _primeiro_idx_parcelada_item(row, historico_parcelas.get(item_id))
            )

    cur.execute(
        """
        SELECT MIN((ano_referencia * 12) + (mes_referencia)) AS idx
        FROM gastos_pix
        WHERE pessoa_id = ?;
        """,
        (pessoa_id,),
    )
    row = cur.fetchone()
    if row and row["idx"] is not None:
        candidatos.append(int(row["idx"]))

    cur.execute(
        """
        SELECT MIN((ano_referencia * 12) + (mes_referencia - 1)) AS idx
        FROM pagamentos_terceiros_itens
        WHERE pessoa_id = ?;
        """,
        (pessoa_id,),
    )
    row = cur.fetchone()
    if row and row["idx"] is not None:
        candidatos.append(int(row["idx"]))

    cur.execute(
        """
        SELECT MIN((ano_referencia * 12) + (mes_referencia - 1)) AS idx
        FROM pessoas_descontos_itens
        WHERE pessoa_id = ?;
        """,
        (pessoa_id,),
    )
    row = cur.fetchone()
    if row and row["idx"] is not None:
        candidatos.append(int(row["idx"]))

    if nome_pessoa:
        cur.execute(
            """
            SELECT nome, valor_padrao, mes_referencia, ano_referencia, vencimento_data, data_fim
            FROM contas_fixas
            WHERE LOWER(TRIM(COALESCE(desconto_pessoa_nome, ''))) = LOWER(TRIM(?))
              AND COALESCE(valor_padrao, 0) > 0;
            """,
            (nome_pessoa,),
        )
        contas_fixas_rows = cur.fetchall()
        inicio_serie_cf: Dict[Tuple[str, str, str], Tuple[int, int]] = {}
        for cf in contas_fixas_rows:
            chave_serie = _chave_serie_conta_fixa(cf["nome"], cf["data_fim"], cf["valor_padrao"])
            competencia_inicio = (int(cf["mes_referencia"]), int(cf["ano_referencia"]))
            atual = inicio_serie_cf.get(chave_serie)
            if atual is None or _indice_competencia(*competencia_inicio) < _indice_competencia(*atual):
                inicio_serie_cf[chave_serie] = competencia_inicio
        for cf in contas_fixas_rows:
            m_cf, a_cf = _competencia_conta_fixa(
                int(cf["mes_referencia"]),
                int(cf["ano_referencia"]),
                cf["vencimento_data"],
            )
            candidatos.append(_indice_competencia(m_cf, a_cf))
        for mes_ini, ano_ini in inicio_serie_cf.values():
            candidatos.append(_indice_competencia(mes_ini, ano_ini))

    return min(candidatos)


def _carregar_historico_parceladas_pessoa(
    cur,
    pessoa_id: int,
    parceladas_rows: List[object] | None = None,
) -> Dict[int, Dict[str, object]]:
    """Mapa item_id -> última parcela paga (histórico de pagamentos)."""
    if parceladas_rows is None:
        cur.execute(
            """
            SELECT id, mes_inicio, ano_inicio, parcela_atual, total_parcelas
            FROM cartao_parceladas
            WHERE pessoa_id = ?;
            """,
            (pessoa_id,),
        )
        parceladas_rows = cur.fetchall()

    historico: Dict[int, Dict[str, object]] = {}
    ids_parceladas = [int(r["id"]) for r in parceladas_rows]
    if ids_parceladas:
        filtros_ids = ", ".join(["?"] * len(ids_parceladas))
        cur.execute(
            f"""
            SELECT item_id, descricao_item
            FROM pagamentos_terceiros_itens
            WHERE pessoa_id = ?
              AND tipo = 'cartao_parcelada'
              AND item_id IN ({filtros_ids});
            """,
            tuple([pessoa_id, *ids_parceladas]),
        )
        for row in cur.fetchall():
            item_id = int(row["item_id"])
            parcela_num, _ = _extrair_parcela_descricao(row["descricao_item"])
            if parcela_num is None:
                continue
            info = historico.setdefault(item_id, {"ultima_parcela": None})
            if info["ultima_parcela"] is None or parcela_num > int(info["ultima_parcela"]):
                info["ultima_parcela"] = parcela_num

    for row in parceladas_rows:
        historico.setdefault(int(row["id"]), {"ultima_parcela": None})

    return historico


def _primeiro_idx_parcelada_item(
    row: object,
    historico_item: Dict[str, object] | None,
) -> int:
    del historico_item
    return _indice_competencia(int(row["mes_inicio"]), int(row["ano_inicio"]))


def obter_indice_inicio_lancamentos_pessoa(
    pessoa_id: int,
    mes_fallback: int,
    ano_fallback: int,
    conn=None,
) -> int:
    close_conn = conn is None
    conn_local = conn or get_connection()
    cur = conn_local.cursor()
    nome = _obter_nome_pessoa(cur, pessoa_id)
    idx = _indice_inicio_lancamentos_pessoa(
        cur,
        pessoa_id,
        nome,
        _indice_competencia(mes_fallback, ano_fallback),
    )
    if close_conn:
        conn_local.close()
    return idx


def _add_meses(mes: int, ano: int, delta: int) -> Tuple[int, int]:
    idx = (ano * 12 + (mes - 1)) + delta
    return (idx % 12) + 1, idx // 12


def _indice_competencia(mes: int, ano: int) -> int:
    return (int(ano) * 12) + (int(mes) - 1)


def _parcela_num_cartao_parcelada(
    mes_inicio: int,
    ano_inicio: int,
    total_parcelas: int,
    mes_ref: int,
    ano_ref: int,
) -> int | None:
    parcela_num = _indice_competencia(mes_ref, ano_ref) - _indice_competencia(mes_inicio, ano_inicio) + 1
    if 1 <= parcela_num <= int(total_parcelas):
        return parcela_num
    return None


def _carregar_parcelas_pagas_por_item(cur, pessoa_id: int) -> Dict[int, set[int]]:
    """Parcelas quitadas por item_id (número da parcela extraído do pagamento)."""
    cur.execute(
        """
        SELECT item_id, descricao_item
        FROM pagamentos_terceiros_itens
        WHERE pessoa_id = ? AND tipo = 'cartao_parcelada';
        """,
        (pessoa_id,),
    )
    mapa: Dict[int, set[int]] = {}
    for row in cur.fetchall():
        parcela_num, _ = _extrair_parcela_descricao(row["descricao_item"])
        if parcela_num is None:
            continue
        mapa.setdefault(int(row["item_id"]), set()).add(int(parcela_num))
    return mapa


def _cartao_parcelada_esta_paga(
    parcelas_pagas: Dict[int, set[int]],
    pagos_keys: set,
    item_id: int,
    parcela_num: int,
    mes_ref: int,
    ano_ref: int,
) -> bool:
    if int(parcela_num) in parcelas_pagas.get(int(item_id), set()):
        return True
    return ("cartao_parcelada", int(item_id), int(mes_ref), int(ano_ref)) in pagos_keys


def _competencia_primeira_parcela(
    mes_referencia: int,
    ano_referencia: int,
    parcela_atual: int,
) -> Tuple[int, int]:
    idx_primeira = _indice_competencia(mes_referencia, ano_referencia) - (int(parcela_atual) - 1)
    return (idx_primeira % 12) + 1, idx_primeira // 12


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


def _parse_data_iso_flex(texto: object | None) -> date | None:
    if not texto:
        return None
    valor = str(texto).strip()
    if not valor:
        return None
    try:
        return date.fromisoformat(valor[:10])
    except Exception:
        pass
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(valor[:10], fmt).date()
        except Exception:
            continue
    return None


def _descricao_conta_fixa(
    nome: object | None,
    mes_competencia: int,
    ano_competencia: int,
    mes_inicio: int,
    ano_inicio: int,
    data_fim: object | None = None,
) -> str:
    descricao = f"Conta fixa: {str(nome or '').strip() or 'Conta fixa'}"
    dt_fim = _parse_data_iso_flex(data_fim)
    if dt_fim is None:
        return descricao
    idx_inicio = _indice_competencia(mes_inicio, ano_inicio)
    idx_fim = _indice_competencia(dt_fim.month, dt_fim.year)
    idx_atual = _indice_competencia(mes_competencia, ano_competencia)
    if idx_fim < idx_inicio or idx_atual < idx_inicio or idx_atual > idx_fim:
        return descricao
    parcela_atual = (idx_atual - idx_inicio) + 1
    total_parcelas = (idx_fim - idx_inicio) + 1
    return f"{descricao} ({parcela_atual}/{total_parcelas})"


def _chave_serie_conta_fixa(
    nome: object | None,
    data_fim: object | None,
    valor: object | None = None,
) -> Tuple[str, str, str]:
    nome_key = str(nome or "").strip().lower()
    data_fim_key = str(_parse_data_iso_flex(data_fim) or "").strip()
    valor_key = f"{float(valor or 0):.2f}"
    return nome_key, data_fim_key, valor_key


def _status_conta_fixa_pago(status: object | None) -> bool:
    return str(status or "").strip().lower() == "pago"


def _obter_inicio_serie_conta_fixa(
    cur,
    nome: object,
    data_fim: object,
    valor: object,
    mes_fallback: int,
    ano_fallback: int,
) -> Tuple[int, int]:
    chave = _chave_serie_conta_fixa(nome, data_fim, valor)
    cur.execute(
        """
        SELECT nome, data_fim, valor_padrao, mes_referencia, ano_referencia
        FROM contas_fixas
        WHERE LOWER(TRIM(nome)) = LOWER(TRIM(?));
        """,
        (str(nome or "").strip(),),
    )
    inicio: Tuple[int, int] | None = None
    for r in cur.fetchall():
        if _chave_serie_conta_fixa(r["nome"], r["data_fim"], r["valor_padrao"]) != chave:
            continue
        cand = (int(r["mes_referencia"]), int(r["ano_referencia"]))
        if inicio is None or _indice_competencia(*cand) < _indice_competencia(*inicio):
            inicio = cand
    return inicio if inicio is not None else (int(mes_fallback), int(ano_fallback))


def sincronizar_pagamento_pessoa_conta_fixa(conta_id: int, conn=None) -> bool:
    """Registra pagamento de terceiro ao marcar conta fixa como paga (espelha fluxo da tela Pessoas)."""
    close_conn = conn is None
    conn_local = conn or get_connection()
    cur = conn_local.cursor()

    cur.execute(
        """
        SELECT id, nome, valor_padrao, desconto_pessoa_nome,
               mes_referencia, ano_referencia, vencimento_data, data_fim, status
        FROM contas_fixas
        WHERE id = ?;
        """,
        (int(conta_id),),
    )
    row = cur.fetchone()
    if not row or not _status_conta_fixa_pago(row["status"]):
        if close_conn:
            conn_local.close()
        return False

    nome_pessoa = (row["desconto_pessoa_nome"] or "").strip()
    if not nome_pessoa:
        if close_conn:
            conn_local.close()
        return False

    cur.execute(
        """
        SELECT id FROM pessoas
        WHERE LOWER(TRIM(nome)) = LOWER(TRIM(?))
        LIMIT 1;
        """,
        (nome_pessoa,),
    )
    pessoa_row = cur.fetchone()
    if not pessoa_row:
        if close_conn:
            conn_local.close()
        return False

    pessoa_id = int(pessoa_row["id"])
    mes_db = int(row["mes_referencia"])
    ano_db = int(row["ano_referencia"])
    mes_cf, ano_cf = _competencia_conta_fixa(mes_db, ano_db, row["vencimento_data"])
    valor = float(row["valor_padrao"] or 0)

    cur.execute(
        """
        SELECT 1
        FROM pagamentos_terceiros_itens
        WHERE pessoa_id = ?
          AND tipo = 'conta_fixa'
          AND item_id = ?
          AND mes_referencia = ?
          AND ano_referencia = ?;
        """,
        (pessoa_id, int(conta_id), mes_cf, ano_cf),
    )
    if cur.fetchone():
        if close_conn:
            conn_local.close()
        return True

    mes_inicio, ano_inicio = _obter_inicio_serie_conta_fixa(
        cur, row["nome"], row["data_fim"], row["valor_padrao"], mes_db, ano_db
    )
    descricao_item = _descricao_conta_fixa(
        row["nome"], mes_cf, ano_cf, mes_inicio, ano_inicio, row["data_fim"]
    )
    descricao_pagamento = f"Conta fixa paga: {descricao_item}"

    if USE_POSTGRES:
        cur.execute(
            """
            INSERT INTO pagamentos_terceiros
            (pessoa_id, valor, descricao, mes_referencia, ano_referencia)
            VALUES (?, ?, ?, ?, ?)
            RETURNING id;
            """,
            (pessoa_id, valor, descricao_pagamento, mes_cf, ano_cf),
        )
        pagamento_id = int(cur.fetchone()["id"])
    else:
        cur.execute(
            """
            INSERT INTO pagamentos_terceiros
            (pessoa_id, valor, descricao, mes_referencia, ano_referencia)
            VALUES (?, ?, ?, ?, ?);
            """,
            (pessoa_id, valor, descricao_pagamento, mes_cf, ano_cf),
        )
        pagamento_id = int(cur.lastrowid)

    cur.execute(
        """
        INSERT INTO pagamentos_terceiros_itens
        (pagamento_id, pessoa_id, tipo, item_id, descricao_item, valor, mes_referencia, ano_referencia)
        VALUES (?, ?, 'conta_fixa', ?, ?, ?, ?, ?);
        """,
        (
            pagamento_id,
            pessoa_id,
            int(conta_id),
            descricao_item,
            valor,
            mes_cf,
            ano_cf,
        ),
    )

    if close_conn:
        conn_local.commit()
        conn_local.close()
    return True


def _remover_pagamento_terceiro_registrado(
    cur,
    pessoa_id: int,
    tipo: str,
    item_id: int,
    mes_referencia: int,
    ano_referencia: int,
) -> bool:
    cur.execute(
        """
        SELECT id, pagamento_id
        FROM pagamentos_terceiros_itens
        WHERE pessoa_id = ?
          AND tipo = ?
          AND item_id = ?
          AND mes_referencia = ?
          AND ano_referencia = ?;
        """,
        (pessoa_id, tipo, item_id, mes_referencia, ano_referencia),
    )
    row = cur.fetchone()
    if not row:
        return False

    item_pagamento_id = int(row["id"])
    pagamento_id = int(row["pagamento_id"])
    cur.execute(
        "DELETE FROM pagamentos_terceiros_itens WHERE id = ?;",
        (item_pagamento_id,),
    )
    cur.execute(
        """
        SELECT COALESCE(SUM(valor), 0) AS total, COUNT(*) AS qtd
        FROM pagamentos_terceiros_itens
        WHERE pagamento_id = ?;
        """,
        (pagamento_id,),
    )
    resumo = cur.fetchone()
    if int(resumo["qtd"] or 0) == 0:
        cur.execute("DELETE FROM pagamentos_terceiros WHERE id = ?;", (pagamento_id,))
    else:
        cur.execute(
            "UPDATE pagamentos_terceiros SET valor = ? WHERE id = ?;",
            (float(resumo["total"]), pagamento_id),
        )
    return True


def desfazer_pagamento_terceiro_item(
    pessoa_id: int,
    conta_token: str,
    mes_referencia: int,
    ano_referencia: int,
) -> bool:
    partes = str(conta_token or "").strip().split(":", 1)
    if len(partes) != 2:
        return False
    tipo = partes[0].strip()
    try:
        item_id = int(partes[1])
    except ValueError:
        return False
    if pessoa_id <= 0 or item_id <= 0 or not tipo:
        return False

    conn = get_connection()
    cur = conn.cursor()
    ok = _remover_pagamento_terceiro_registrado(
        cur,
        pessoa_id,
        tipo,
        item_id,
        mes_referencia,
        ano_referencia,
    )
    if ok and tipo == "conta_fixa":
        cur.execute(
            """
            UPDATE contas_fixas
            SET status = 'Pendente',
                desconto_aplicado = FALSE,
                desconto_origem = NULL,
                desconto_receita_extra_id = NULL
            WHERE id = ?;
            """,
            (item_id,),
        )
    if ok:
        conn.commit()
    conn.close()
    return ok


def desfazer_pagamento_conta_fixa_sincronizado(conta_id: int, conn=None) -> bool:
    """Remove registro em pagamentos de terceiros espelhado ao marcar conta fixa como paga."""
    close_conn = conn is None
    conn_local = conn or get_connection()
    cur = conn_local.cursor()

    cur.execute(
        """
        SELECT desconto_pessoa_nome, mes_referencia, ano_referencia, vencimento_data
        FROM contas_fixas
        WHERE id = ?;
        """,
        (int(conta_id),),
    )
    row = cur.fetchone()
    if not row:
        if close_conn:
            conn_local.close()
        return False

    nome_pessoa = (row["desconto_pessoa_nome"] or "").strip()
    if not nome_pessoa:
        if close_conn:
            conn_local.close()
        return True

    cur.execute(
        """
        SELECT id FROM pessoas
        WHERE LOWER(TRIM(nome)) = LOWER(TRIM(?))
        LIMIT 1;
        """,
        (nome_pessoa,),
    )
    pessoa_row = cur.fetchone()
    if not pessoa_row:
        if close_conn:
            conn_local.close()
        return True

    mes_cf, ano_cf = _competencia_conta_fixa(
        int(row["mes_referencia"]),
        int(row["ano_referencia"]),
        row["vencimento_data"],
    )
    ok = _remover_pagamento_terceiro_registrado(
        cur,
        int(pessoa_row["id"]),
        "conta_fixa",
        int(conta_id),
        mes_cf,
        ano_cf,
    )
    if close_conn:
        conn_local.commit()
        conn_local.close()
    return ok


def _descricao_pagamento_parcelada(texto: object | None) -> str:
    descricao = str(texto or "").strip()
    return descricao or "Cartão parcelado"


def _extrair_parcela_descricao(texto: object | None) -> Tuple[int | None, int | None]:
    descricao = str(texto or "")
    match = re.search(r"parcela\s+(\d+)\s*/\s*(\d+)", descricao, flags=re.IGNORECASE)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


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
    idx_ref = ano_referencia * 12 + (mes_referencia - 1)
    for r in cur.fetchall():
        idx_inicio = _indice_competencia(int(r["mes_inicio"]), int(r["ano_inicio"]))
        parcela_num = idx_ref - idx_inicio + 1
        total_parcelas = int(r["total_parcelas"])
        restantes = max(total_parcelas - int(r["parcela_atual"]) + 1, 0)
        if int(r["qtd_quitadas"]) >= restantes:
            continue
        if parcela_num < 1 or parcela_num > total_parcelas:
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

    nome_pessoa = _obter_nome_pessoa(cur, pessoa_id)
    if nome_pessoa:
        cur.execute(
            """
            SELECT
                'conta_fixa' AS tipo,
                cf.id AS item_id,
                cf.nome AS nome,
                COALESCE(cf.valor_padrao, 0) AS valor,
                cf.mes_referencia AS mes_referencia,
                cf.ano_referencia AS ano_referencia,
                cf.vencimento_data AS vencimento_data,
                cf.data_fim AS data_fim
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
        contas_fixas_rows = cur.fetchall()
        inicio_serie_por_chave: Dict[Tuple[str, str, str], Tuple[int, int]] = {}
        for r in contas_fixas_rows:
            chave_serie = _chave_serie_conta_fixa(r["nome"], r["data_fim"], r["valor"])
            competencia_inicio = (int(r["mes_referencia"]), int(r["ano_referencia"]))
            competencia_atual = inicio_serie_por_chave.get(chave_serie)
            if competencia_atual is None or _indice_competencia(*competencia_inicio) < _indice_competencia(*competencia_atual):
                inicio_serie_por_chave[chave_serie] = competencia_inicio
        for r in contas_fixas_rows:
            m_cf, a_cf = _competencia_conta_fixa(
                int(r["mes_referencia"]),
                int(r["ano_referencia"]),
                r["vencimento_data"],
            )
            if (m_cf, a_cf) == (mes_referencia, ano_referencia):
                mes_inicio_serie, ano_inicio_serie = inicio_serie_por_chave.get(
                    _chave_serie_conta_fixa(r["nome"], r["data_fim"], r["valor"]),
                    (int(r["mes_referencia"]), int(r["ano_referencia"])),
                )
                pendentes.append(
                    {
                        "tipo": str(r["tipo"]),
                        "item_id": int(r["item_id"]),
                        "descricao": _descricao_conta_fixa(
                            r["nome"],
                            mes_referencia,
                            ano_referencia,
                            mes_inicio_serie,
                            ano_inicio_serie,
                            r["data_fim"],
                        ),
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
    conn=None,
) -> List[Dict[str, float | int | str | bool]]:
    chave = f"{int(ano_referencia)}-{int(mes_referencia):02d}"
    mapa = listar_contas_status_pessoa_meses(
        pessoa_id,
        [(int(mes_referencia), int(ano_referencia))],
        mes_cartao_referencia,
        ano_cartao_referencia,
        conn=conn,
    )
    return mapa.get(chave, [])


def listar_contas_status_pessoa_meses(
    pessoa_id: int,
    referencias: List[Tuple[int, int]] | None = None,
    mes_cartao_referencia: int | None = None,
    ano_cartao_referencia: int | None = None,
    conn=None,
    *,
    idx_min: int | None = None,
    idx_max: int | None = None,
    parceladas_rows: List[object] | None = None,
    historico_parceladas: Dict[int, Dict[str, object]] | None = None,
) -> Dict[str, List[Dict[str, float | int | str | bool]]]:
    if idx_min is not None and idx_max is not None:
        if idx_max < idx_min:
            idx_min, idx_max = idx_max, idx_min
        refs_unicas = [
            ((i % 12) + 1, i // 12) for i in range(int(idx_min), int(idx_max) + 1)
        ]
    else:
        refs_unicas = sorted(
            {(int(m), int(a)) for (m, a) in (referencias or [])},
            key=lambda x: (x[1], x[0]),
        )
    if not refs_unicas:
        return {}

    mapa: Dict[str, List[Dict[str, float | int | str | bool]]] = defaultdict(list)
    refs_set = {(m, a) for (m, a) in refs_unicas}
    idx_min_calc = min(a * 12 + (m - 1) for (m, a) in refs_unicas)
    idx_max_calc = max(a * 12 + (m - 1) for (m, a) in refs_unicas)

    close_conn = conn is None
    conn_local = conn or get_connection()
    cur = conn_local.cursor()

    cur.execute(
        """
        SELECT tipo, item_id, mes_referencia, ano_referencia
        FROM pagamentos_terceiros_itens
        WHERE pessoa_id = ?
          AND ((ano_referencia * 12) + (mes_referencia - 1)) BETWEEN ? AND ?;
        """,
        (pessoa_id, idx_min_calc, idx_max_calc),
    )
    pagos_keys = {
        (str(r["tipo"]), int(r["item_id"]), int(r["mes_referencia"]), int(r["ano_referencia"]))
        for r in cur.fetchall()
    }

    if parceladas_rows is None:
        cur.execute(
            """
            SELECT id, descricao, valor_parcela, total_parcelas, parcela_atual, mes_inicio, ano_inicio, status
            FROM cartao_parceladas
            WHERE pessoa_id = ?;
            """,
            (pessoa_id,),
        )
        parceladas_ativas = cur.fetchall()
    else:
        parceladas_ativas = parceladas_rows
    if historico_parceladas is None:
        historico_parceladas = _carregar_historico_parceladas_pessoa(
            cur, pessoa_id, parceladas_ativas
        )

    parceladas_adicionadas: set[Tuple[int, int, int]] = set()
    parceladas_por_id = {int(r["id"]): r for r in parceladas_ativas}
    parcelas_pagas_por_item = _carregar_parcelas_pagas_por_item(cur, pessoa_id)
    for r in parceladas_ativas:
        item_id = int(r["id"])
        total_parcelas = int(r["total_parcelas"])
        idx_primeiro = _primeiro_idx_parcelada_item(
            r, historico_parceladas.get(item_id)
        )
        idx_parcela_fim = int(idx_primeiro) + total_parcelas - 1
        idx_inicio = max(idx_min_calc, int(idx_primeiro))
        idx_fim = min(idx_max_calc, idx_parcela_fim)
        for idx_ref in range(idx_inicio, idx_fim + 1):
            m_ref = (idx_ref % 12) + 1
            a_ref = idx_ref // 12
            parcela_num = idx_ref - int(idx_primeiro) + 1
            pago = _cartao_parcelada_esta_paga(
                parcelas_pagas_por_item,
                pagos_keys,
                item_id,
                parcela_num,
                m_ref,
                a_ref,
            )
            parceladas_adicionadas.add((item_id, m_ref, a_ref))
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

    cur.execute(
        """
        SELECT item_id, descricao_item, valor, mes_referencia, ano_referencia
        FROM pagamentos_terceiros_itens
        WHERE pessoa_id = ?
          AND tipo = 'cartao_parcelada'
          AND ((ano_referencia * 12) + (mes_referencia - 1)) BETWEEN ? AND ?;
        """,
        (pessoa_id, idx_min_calc, idx_max_calc),
    )
    for r in cur.fetchall():
        item_id = int(r["item_id"])
        m_ref = int(r["mes_referencia"])
        a_ref = int(r["ano_referencia"])
        if (item_id, m_ref, a_ref) in parceladas_adicionadas:
            continue
        row_parcelada = parceladas_por_id.get(item_id)
        if row_parcelada is not None and _parcela_num_cartao_parcelada(
            int(row_parcelada["mes_inicio"]),
            int(row_parcelada["ano_inicio"]),
            int(row_parcelada["total_parcelas"]),
            m_ref,
            a_ref,
        ) is None:
            continue
        mapa[f"{a_ref}-{m_ref:02d}"].append(
            {
                "tipo": "cartao_parcelada",
                "item_id": item_id,
                "descricao": _descricao_pagamento_parcelada(r["descricao_item"]),
                "valor": float(r["valor"]),
                "mes_referencia": m_ref,
                "ano_referencia": a_ref,
                "pago": True,
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
        (pessoa_id, idx_min_calc, idx_max_calc),
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

    # Gastos Pix nas competências carregadas.
    cur.execute(
        """
        SELECT id, descricao, valor, mes_referencia, ano_referencia
        FROM gastos_pix
        WHERE pessoa_id = ?
          AND ((ano_referencia * 12) + (mes_referencia - 1)) BETWEEN ? AND ?;
        """,
        (pessoa_id, idx_min_calc - 1, idx_max_calc),
    )
    for r in cur.fetchall():
        m_ref, a_ref = _add_meses(int(r["mes_referencia"]), int(r["ano_referencia"]), 1)
        chave = f"{a_ref}-{m_ref:02d}"
        if (m_ref, a_ref) not in refs_set:
            continue
        item_id = int(r["id"])
        mapa[chave].append(
            {
                "tipo": "gasto_pix",
                "item_id": item_id,
                "descricao": f"Gasto Pix: {r['descricao']}",
                "valor": float(r["valor"]),
                "mes_referencia": m_ref,
                "ano_referencia": a_ref,
                "pago": ("gasto_pix", item_id, m_ref, a_ref) in pagos_keys,
            }
        )

    # Contas fixas vinculadas à pessoa.
    nome_pessoa = _obter_nome_pessoa(cur, pessoa_id)
    if nome_pessoa:
        cur.execute(
            """
            SELECT id, nome, valor_padrao, mes_referencia, ano_referencia, vencimento_data, data_fim, status
            FROM contas_fixas
            WHERE LOWER(TRIM(COALESCE(desconto_pessoa_nome, ''))) = LOWER(TRIM(?))
              AND (
                    ((ano_referencia * 12) + (mes_referencia - 1)) BETWEEN ? AND ?
                 OR vencimento_data IS NOT NULL
              );
            """,
            (nome_pessoa, idx_min_calc - 1, idx_max_calc + 1),
        )
        contas_fixas_rows = cur.fetchall()
        inicio_serie_por_chave: Dict[Tuple[str, str, str], Tuple[int, int]] = {}
        for r in contas_fixas_rows:
            chave_serie = _chave_serie_conta_fixa(r["nome"], r["data_fim"], r["valor_padrao"])
            competencia_inicio = (int(r["mes_referencia"]), int(r["ano_referencia"]))
            competencia_atual = inicio_serie_por_chave.get(chave_serie)
            if competencia_atual is None or _indice_competencia(*competencia_inicio) < _indice_competencia(*competencia_atual):
                inicio_serie_por_chave[chave_serie] = competencia_inicio
        for r in contas_fixas_rows:
            m_cf, a_cf = _competencia_conta_fixa(
                int(r["mes_referencia"]),
                int(r["ano_referencia"]),
                r["vencimento_data"],
            )
            if (m_cf, a_cf) not in refs_set:
                continue
            chave = f"{a_cf}-{m_cf:02d}"
            item_id = int(r["id"])
            pago = bool(
                _status_conta_fixa_pago(r["status"])
                or ("conta_fixa", item_id, m_cf, a_cf) in pagos_keys
            )
            mes_inicio_serie, ano_inicio_serie = inicio_serie_por_chave.get(
                _chave_serie_conta_fixa(r["nome"], r["data_fim"], r["valor_padrao"]),
                (int(r["mes_referencia"]), int(r["ano_referencia"])),
            )
            mapa[chave].append(
                {
                    "tipo": "conta_fixa",
                    "item_id": item_id,
                    "descricao": _descricao_conta_fixa(
                        r["nome"],
                        m_cf,
                        a_cf,
                        mes_inicio_serie,
                        ano_inicio_serie,
                        r["data_fim"],
                    ),
                    "valor": float(r["valor_padrao"] or 0),
                    "mes_referencia": m_cf,
                    "ano_referencia": a_cf,
                    "pago": pago,
                }
            )

    if close_conn:
        conn_local.close()

    resultado: Dict[str, List[Dict[str, float | int | str | bool]]] = {}
    for chave, itens in mapa.items():
        if not itens:
            continue
        for item in itens:
            item["token"] = f"{item['tipo']}:{item['item_id']}"
            item["valor"] = float(item["valor"])
            item["mes_referencia"] = int(item["mes_referencia"])
            item["ano_referencia"] = int(item["ano_referencia"])
            item["pago"] = bool(item["pago"])
        resultado[chave] = sorted(itens, key=lambda x: str(x["descricao"]).lower())
    return resultado


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
    idx_ref = ano_referencia * 12 + (mes_referencia - 1)
    for r in cur.fetchall():
        parcela_atual = int(r["parcela_atual"])
        total_parcelas = int(r["total_parcelas"])
        restantes = max(total_parcelas - parcela_atual + 1, 0)
        if int(r["qtd_quitadas"]) >= restantes:
            continue
        idx_inicio = _indice_competencia(int(r["mes_inicio"]), int(r["ano_inicio"]))
        parcela_num = idx_ref - idx_inicio + 1
        if parcela_num < 1 or parcela_num > total_parcelas:
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

    nome_pessoa = _obter_nome_pessoa(cur, pessoa_id)
    if nome_pessoa:
        cur.execute(
            """
            SELECT
                'conta_fixa' AS tipo,
                cf.id AS item_id,
                cf.nome AS nome,
                COALESCE(cf.valor_padrao, 0) AS valor,
                cf.mes_referencia AS mes_referencia_db,
                cf.ano_referencia AS ano_referencia_db,
                cf.vencimento_data AS vencimento_data,
                cf.data_fim AS data_fim,
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
        contas_fixas_rows = cur.fetchall()
        inicio_serie_por_chave: Dict[Tuple[str, str, str], Tuple[int, int]] = {}
        for r in contas_fixas_rows:
            chave_serie = _chave_serie_conta_fixa(r["nome"], r["data_fim"], r["valor"])
            competencia_inicio = (int(r["mes_referencia_db"]), int(r["ano_referencia_db"]))
            competencia_atual = inicio_serie_por_chave.get(chave_serie)
            if competencia_atual is None or _indice_competencia(*competencia_inicio) < _indice_competencia(*competencia_atual):
                inicio_serie_por_chave[chave_serie] = competencia_inicio
        for r in contas_fixas_rows:
            m_cf, a_cf = _competencia_conta_fixa(
                int(r["mes_referencia_db"]),
                int(r["ano_referencia_db"]),
                r["vencimento_data"],
            )
            if (m_cf, a_cf) == (mes_referencia, ano_referencia):
                mes_inicio_serie, ano_inicio_serie = inicio_serie_por_chave.get(
                    _chave_serie_conta_fixa(r["nome"], r["data_fim"], r["valor"]),
                    (int(r["mes_referencia_db"]), int(r["ano_referencia_db"])),
                )
                contas.append(
                    {
                        "tipo": str(r["tipo"]),
                        "item_id": int(r["item_id"]),
                        "descricao": _descricao_conta_fixa(
                            r["nome"],
                            mes_referencia,
                            ano_referencia,
                            mes_inicio_serie,
                            ano_inicio_serie,
                            r["data_fim"],
                        ),
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
    conn=None,
) -> Dict[int, Dict[str, float]]:
    """Retorna dicionário {pessoa_id: {'total_mes': ..., 'total_pago': ..., 'saldo_pendente': ...}}."""
    close_conn = conn is None
    conn_local = conn or get_connection()
    cur = conn_local.cursor()
    cur.execute("SELECT id FROM pessoas;")
    pessoa_ids = [int(row["id"]) for row in cur.fetchall()]
    descontos_manuais = obter_descontos_manuais_por_pessoa(mes, ano, conn=conn_local)

    totals: Dict[int, Dict[str, float]] = {}
    chave_mes = f"{int(ano)}-{int(mes):02d}"
    for pessoa_id in pessoa_ids:
        contas = listar_contas_status_pessoa_meses(
            pessoa_id,
            [(mes, ano)],
            mes_cartao_referencia,
            ano_cartao_referencia,
            conn=conn_local,
        ).get(chave_mes, [])
        total_mes = sum(float(c["valor"]) for c in contas)
        total_pago = sum(float(c["valor"]) for c in contas if bool(c.get("pago")))
        total_mes -= float(descontos_manuais.get(pessoa_id, 0.0))
        if total_mes < 0:
            total_mes = 0.0
        if total_pago > total_mes:
            total_pago = total_mes
        totals[pessoa_id] = {
            "total_mes": total_mes,
            "total_pago": total_pago,
            "saldo_pendente": max(total_mes - total_pago, 0.0),
        }

    if close_conn:
        conn_local.close()
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
    inicio_idx = _indice_inicio_lancamentos_pessoa(
        cur,
        pessoa_id,
        nome_pessoa,
        _indice_competencia(mes_referencia, ano_referencia),
    )
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

    cur.execute(
        """
        SELECT descricao, valor, mes_referencia, ano_referencia
        FROM gastos_pix
        WHERE pessoa_id = ?
          AND ((ano_referencia * 12) + (mes_referencia - 1)) BETWEEN ? AND ?;
        """,
        (pessoa_id, inicio_idx - 1, fim_idx),
    )
    for r in cur.fetchall():
        mes_gasto, ano_gasto = _add_meses(int(r["mes_referencia"]), int(r["ano_referencia"]), 1)
        add_item(
            mes_gasto,
            ano_gasto,
            f"Gasto Pix: {r['descricao']}",
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
            cp.mes_inicio,
            cp.ano_inicio,
            cp.status,
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
        WHERE cp.pessoa_id = ?;
        """,
        (pessoa_id,),
    )
    parceladas_prev = cur.fetchall()
    historico_prev = _carregar_historico_parceladas_pessoa(
        cur, pessoa_id, parceladas_prev
    )
    for r in parceladas_prev:
        valor = float(r["valor_parcela"])
        total_parcelas = int(r["total_parcelas"])
        idx_primeiro = _primeiro_idx_parcelada_item(
            r, historico_prev.get(int(r["id"]))
        )
        for parcela_num in range(1, total_parcelas + 1):
            off = parcela_num - 1
            idx_comp = int(idx_primeiro) + off
            mes_i, ano_i = (idx_comp % 12) + 1, idx_comp // 12
            add_item(
                mes_i,
                ano_i,
                f"Cartão parcelado: {r['descricao']} (parcela {parcela_num}/{total_parcelas})",
                valor,
            )

    # Contas fixas vinculadas à pessoa: projeta recorrência mensal até data_fim,
    # respeitando alterações futuras já cadastradas para o mesmo nome.
    cur.execute(
        """
        SELECT nome, categoria, valor_padrao, mes_referencia, ano_referencia, vencimento_data, data_fim, status
        FROM contas_fixas
        WHERE LOWER(COALESCE(desconto_pessoa_nome, '')) = LOWER(?)
          AND COALESCE(valor_padrao, 0) > 0
          AND (
                ((ano_referencia * 12) + (mes_referencia - 1)) <= ?
             OR vencimento_data IS NOT NULL
          );
        """,
        (nome_pessoa, fim_idx + 1),
    )
    contas_por_nome: Dict[str, List[Dict[str, object]]] = {}
    for r in cur.fetchall():
        mes_c, ano_c = _competencia_conta_fixa(
            int(r["mes_referencia"]),
            int(r["ano_referencia"]),
            r["vencimento_data"],
        )
        contas_por_nome.setdefault(str(r["nome"]), []).append(
            {
                "nome": str(r["nome"]),
                "categoria": str(r["categoria"] or ""),
                "valor": float(r["valor_padrao"]),
                "mes_inicio": int(r["mes_referencia"]),
                "ano_inicio": int(r["ano_referencia"]),
                "mes": mes_c,
                "ano": ano_c,
                "data_fim": r["data_fim"],
                "status": str(r["status"]),
            }
        )

    for nome_conta, versoes in contas_por_nome.items():
        versoes.sort(key=lambda item: (_indice_competencia(int(item["mes"]), int(item["ano"])), str(item["nome"])))
        for idx, versao in enumerate(versoes):
            inicio_conta_idx = _indice_competencia(int(versao["mes"]), int(versao["ano"]))
            prox_idx = fim_idx + 1
            if idx + 1 < len(versoes):
                prox = versoes[idx + 1]
                prox_idx = _indice_competencia(int(prox["mes"]), int(prox["ano"]))

            fim_conta_idx = min(fim_idx, prox_idx - 1)
            data_fim = versao.get("data_fim")
            if data_fim:
                texto = str(data_fim).strip()
                try:
                    dt_fim = date.fromisoformat(texto[:10])
                    fim_conta_idx = min(fim_conta_idx, _indice_competencia(dt_fim.month, dt_fim.year))
                except Exception:
                    pass

            if fim_conta_idx < inicio_conta_idx:
                continue

            if str(versao.get("categoria") or "").strip().lower() == "gasto pix":
                fim_conta_idx = min(fim_conta_idx, inicio_conta_idx)

            for competencia_idx in range(inicio_conta_idx, fim_conta_idx + 1):
                ano_i = competencia_idx // 12
                mes_i = (competencia_idx % 12) + 1
                add_item(
                    mes_i,
                    ano_i,
                    _descricao_conta_fixa(
                        nome_conta,
                        mes_i,
                        ano_i,
                        int(versao["mes_inicio"]),
                        int(versao["ano_inicio"]),
                        versao.get("data_fim"),
                    ),
                    float(versao["valor"]),
                )

    if close_conn:
        conn_local.close()

    meses = sorted(mapa.values(), key=lambda x: (int(x["ano"]), int(x["mes"])))
    total_geral = sum(float(m["total"]) for m in meses)
    return {"meses": meses, "total_geral": total_geral}


def carregar_detalhe_pessoa_pagina(
    pessoa_id: int,
    mes: int,
    ano: int,
    mes_cartao_referencia: int | None = None,
    ano_cartao_referencia: int | None = None,
    conn=None,
) -> Dict[str, object]:
    """Carrega contas por mês, descontos e resumo de previsão para a aba da pessoa (uma passagem no banco)."""
    close_conn = conn is None
    conn_local = conn or get_connection()
    cur = conn_local.cursor()
    try:
        nome_pessoa = _obter_nome_pessoa(cur, pessoa_id)
        cur.execute(
            """
            SELECT id, descricao, valor_parcela, total_parcelas, parcela_atual, mes_inicio, ano_inicio, status
            FROM cartao_parceladas
            WHERE pessoa_id = ?;
            """,
            (pessoa_id,),
        )
        parceladas_rows = cur.fetchall()
        historico_parceladas = _carregar_historico_parceladas_pessoa(
            cur, pessoa_id, parceladas_rows
        )
        inicio_idx = _indice_inicio_lancamentos_pessoa(
            cur,
            pessoa_id,
            nome_pessoa,
            _indice_competencia(mes, ano),
            parceladas_pessoa=parceladas_rows,
            historico_parcelas=historico_parceladas,
        )
        idx_filtro = _indice_competencia(mes, ano)
        idx_max = idx_filtro + 11

        mapa_mes = listar_contas_status_pessoa_meses(
            pessoa_id,
            mes_cartao_referencia=mes_cartao_referencia,
            ano_cartao_referencia=ano_cartao_referencia,
            conn=conn_local,
            idx_min=inicio_idx,
            idx_max=idx_max,
            parceladas_rows=parceladas_rows,
            historico_parceladas=historico_parceladas,
        )

        mes_inicio_hist = (inicio_idx % 12) + 1
        ano_inicio_hist = inicio_idx // 12
        mes_fim = (idx_max % 12) + 1
        ano_fim = idx_max // 12
        descontos_por_mes = listar_descontos_manuais_pessoa_intervalo(
            pessoa_id,
            mes_inicio_hist,
            ano_inicio_hist,
            mes_fim,
            ano_fim,
            conn=conn_local,
        )

        chave_mes_atual = f"{ano}-{mes:02d}"
        meses_com_dados: List[Dict[str, object]] = []
        for chave_mes, contas_chave in sorted(
            mapa_mes.items(),
            key=lambda kv: (int(kv[0].split("-")[0]), int(kv[0].split("-")[1])),
        ):
            if not contas_chave:
                continue
            ano_chave, mes_chave = chave_mes.split("-")
            meses_com_dados.append(
                {
                    "mes": int(mes_chave),
                    "ano": int(ano_chave),
                    "total": sum(float(item.get("valor", 0.0)) for item in contas_chave),
                    "itens": [
                        {
                            "descricao": str(item.get("descricao", "")),
                            "valor": float(item.get("valor", 0.0)),
                        }
                        for item in contas_chave
                    ],
                }
            )

        chave_mes_ativo = chave_mes_atual
        if not any(
            f"{int(m['ano'])}-{int(m['mes']):02d}" == chave_mes_ativo for m in meses_com_dados
        ):
            if meses_com_dados:
                ultimo = meses_com_dados[-1]
                chave_mes_ativo = f"{int(ultimo['ano'])}-{int(ultimo['mes']):02d}"
            else:
                chave_mes_ativo = None

        total_contas_previsto = sum(float(m.get("total", 0.0)) for m in meses_com_dados)
        total_descontos_previsto = sum(
            float(d.get("valor", 0.0))
            for itens_desc in descontos_por_mes.values()
            for d in itens_desc
        )

        mapa_descontos_mes: Dict[str, List[Dict[str, float | int | str]]] = {}
        for mref in meses_com_dados:
            chave = f"{int(mref['ano'])}-{int(mref['mes']):02d}"
            mapa_descontos_mes[chave] = descontos_por_mes.get(chave, [])

        previsao = {
            "meses": meses_com_dados,
            "total_geral": total_contas_previsto,
            "total_geral_liquido": max(total_contas_previsto - total_descontos_previsto, 0.0),
            "chave_mes_ativo": chave_mes_ativo,
        }
        return {
            "previsao": previsao,
            "contas_status_por_mes": mapa_mes,
            "descontos_itens_por_mes": mapa_descontos_mes,
        }
    finally:
        if close_conn:
            conn_local.close()

