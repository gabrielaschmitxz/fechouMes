from __future__ import annotations

from datetime import date
from typing import Dict, List, Tuple

from finance_app.database import get_connection
from finance_app.models import CartaoConfig, CartaoParcelada, CartaoAvista


def _add_meses(mes: int, ano: int, delta: int) -> Tuple[int, int]:
    idx = (ano * 12 + (mes - 1)) + delta
    return (idx % 12) + 1, idx // 12


def _indice_competencia(mes: int, ano: int) -> int:
    return (int(ano) * 12) + (int(mes) - 1)


def _competencia_primeira_parcela(
    mes_referencia: int,
    ano_referencia: int,
    parcela_atual: int,
) -> Tuple[int, int]:
    idx_primeira = _indice_competencia(mes_referencia, ano_referencia) - (int(parcela_atual) - 1)
    return (idx_primeira % 12) + 1, idx_primeira // 12


def get_config() -> CartaoConfig:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, limite_total, dia_fechamento, dia_vencimento, fatura_paga FROM cartao_config WHERE id = 1;") # Removed get_cursor(conn) and used conn.cursor()
    row = cur.fetchone()
    conn.close()
    if not row:
        raise RuntimeError("Configuração do cartão não encontrada.")
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
    """Determina o mês/ano de referência da fatura atual com base no dia de fechamento."""
    if hoje is None:
        hoje = date.today()
    cfg = get_config()
    mes = hoje.month
    ano = hoje.year
    # Compras após o fechamento pertencem à próxima fatura
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


def listar_parceladas() -> List[CartaoParcelada]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, descricao, valor_parcela, total_parcelas, parcela_atual,
               mes_inicio, ano_inicio, status, pessoa_id
        FROM cartao_parceladas
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
    mes_referencia: int | None = None,
    ano_referencia: int | None = None,
) -> None:
    if mes_referencia is None or ano_referencia is None:
        mes_ref, ano_ref = mes_ano_fatura_atual()
    else:
        mes_ref, ano_ref = mes_referencia, ano_referencia
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


def mes_ano_fatura_em_aberto(hoje: date | None = None) -> Tuple[int, int]:
    mes_ref, ano_ref = mes_ano_fatura_atual(hoje=hoje)
    cfg = get_config()
    if cfg.fatura_paga:
        return _add_meses(mes_ref, ano_ref, 1)
    return mes_ref, ano_ref


def calcular_fatura_competencia(mes_ref: int, ano_ref: int) -> Dict[str, float]:
    """Retorna totais da competência informada."""
    idx_alvo = _indice_competencia(mes_ref, ano_ref)

    # Parceladas: na aba de cartão, mes_inicio/ano_inicio representam a competência da primeira parcela.
    parceladas = listar_parceladas()
    total_parceladas_meu = 0.0
    total_parceladas_terceiros = 0.0
    for p in parceladas:
        idx_inicio = _indice_competencia(int(p.mes_inicio), int(p.ano_inicio))
        parcela_num = idx_alvo - idx_inicio + 1
        if parcela_num < 1 or parcela_num > int(p.total_parcelas):
            continue
        if p.pessoa_id is None:
            total_parceladas_meu += float(p.valor_parcela)
        else:
            total_parceladas_terceiros += float(p.valor_parcela)

    # À vista: apenas mês/ano de referência
    avista = listar_avista_mes(mes_ref, ano_ref)
    total_avista_meu = sum(float(a.valor) for a in avista if a.pessoa_id is None)
    total_avista_terceiros = sum(float(a.valor) for a in avista if a.pessoa_id is not None)

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


def calcular_fatura_atual() -> Dict[str, float]:
    """Retorna totais da fatura em aberto no momento."""
    mes_ref, ano_ref = mes_ano_fatura_em_aberto()
    return calcular_fatura_competencia(mes_ref, ano_ref)


def marcar_fatura_como_paga() -> None:
    """Regras:
    - fatura_paga = True
    - avançar mês da fatura (implícito pela função mes_ano_fatura_atual ao longo do tempo)
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
    """Permite marcar novamente como não paga (caso de erro)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE cartao_config SET fatura_paga = FALSE WHERE id = 1;")
    conn.commit()
    conn.close()


def listar_todos_lancamentos() -> List[Dict[str, object]]:
    conn = get_connection()
    cur = conn.cursor()
    rows: List[Dict[str, object]] = []
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
        ORDER BY ano_referencia DESC, mes_referencia DESC, id DESC;
        """
    )
    rows.extend(dict(r) for r in cur.fetchall())

    cur.execute(
        """
        SELECT
            id,
            descricao,
            valor_parcela AS valor,
            total_parcelas,
            parcela_atual,
            mes_inicio,
            ano_inicio,
            status,
            pessoa_id
        FROM cartao_parceladas
        ORDER BY ano_inicio DESC, mes_inicio DESC, id DESC;
        """
    )
    for r in cur.fetchall():
        item = dict(r)
        total_parcelas = int(item.get("total_parcelas") or 1)
        parcela_atual = int(item.get("parcela_atual") or 1)
        status = str(item.get("status") or "")
        mes_referencia = int(item.get("mes_inicio") or 1)
        ano_referencia = int(item.get("ano_inicio") or date.today().year)
        parcela_referencia = max(1, min(parcela_atual, total_parcelas))
        mes_inicio, ano_inicio = _competencia_primeira_parcela(
            mes_referencia,
            ano_referencia,
            parcela_referencia,
        )

        for off in range(total_parcelas):
            parcela_exibicao = off + 1
            mes_ref, ano_ref = _add_meses(mes_inicio, ano_inicio, off)
            rows.append(
                {
                    "tipo": "parcelado",
                    "id": int(item["id"]),
                    "descricao": str(item["descricao"]),
                    "valor": float(item["valor"]),
                    "total_parcelas": total_parcelas,
                    "parcela_atual": parcela_atual,
                    "parcela_exibicao": parcela_exibicao,
                    "mes_ref": mes_ref,
                    "ano_ref": ano_ref,
                    "mes_inicio": mes_inicio,
                    "ano_inicio": ano_inicio,
                    "status": status,
                    "pessoa_id": item.get("pessoa_id"),
                }
            )
    conn.close()
    rows.sort(key=lambda x: (-int(x["ano_ref"]), -int(x["mes_ref"]), -int(x["id"])))
    return rows


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
    lancamento_id: int,
    descricao: str,
    valor: float,
    pessoa_id: int | None,
    mes_referencia: int,
    ano_referencia: int,
) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE cartao_avista
        SET descricao = ?, valor = ?, pessoa_id = ?, mes_referencia = ?, ano_referencia = ?
        WHERE id = ?;
        """,
        (descricao, valor, pessoa_id, mes_referencia, ano_referencia, lancamento_id),
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
    status: str | None,
    pessoa_id: int | None,
    mes_inicio: int,
    ano_inicio: int,
) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE cartao_parceladas
        SET descricao = ?, valor_parcela = ?, parcela_atual = ?, total_parcelas = ?, status = COALESCE(?, status), pessoa_id = ?, mes_inicio = ?, ano_inicio = ?
        WHERE id = ?;
        """,
        (
            descricao,
            valor_parcela,
            parcela_atual,
            total_parcelas,
            status,
            pessoa_id,
            mes_inicio,
            ano_inicio,
            lancamento_id,
        ),
    )
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok

