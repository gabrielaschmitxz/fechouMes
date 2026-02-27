from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Tuple

from finance_app.database import get_connection
from finance_app.models import ReceitaSaldo, ReceitaExtra, ReceitaLancamento


def listar_saldos() -> List[ReceitaSaldo]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, nome, saldo_atual FROM receitas_saldos ORDER BY nome;")
    rows = cur.fetchall()
    conn.close()
    return [ReceitaSaldo(**dict(r)) for r in rows]


def garantir_saldos_por_nomes(nomes: List[str]) -> None:
    nomes_limpos = [n.strip() for n in nomes if n and n.strip()]
    if not nomes_limpos:
        return
    conn = get_connection()
    cur = conn.cursor()
    for nome in nomes_limpos:
        cur.execute(
            """
            INSERT INTO receitas_saldos (nome, saldo_atual)
            VALUES (?, 0)
            ON CONFLICT(nome) DO NOTHING;
            """,
            (nome,),
        )
    conn.commit()
    conn.close()


def obter_saldo_por_nome(nome: str) -> Optional[ReceitaSaldo]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, nome, saldo_atual FROM receitas_saldos WHERE nome = ?;",
        (nome,),
    )
    row = cur.fetchone()
    conn.close()
    return ReceitaSaldo(**dict(row)) if row else None


def atualizar_saldo(saldo_id: int, delta: float) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE receitas_saldos SET saldo_atual = saldo_atual + ? WHERE id = ?;",
        (delta, saldo_id),
    )
    conn.commit()
    conn.close()


def _registrar_lancamento(
    saldo_id: int,
    tipo_origem: str,
    categoria: str,
    valor: float,
    descricao: Optional[str] = None,
    receita_extra_id: Optional[int] = None,
    data_recebimento: Optional[str] = None,
) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO receitas_lancamentos
        (saldo_id, receita_extra_id, tipo_origem, categoria, descricao, valor, data_recebimento)
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """,
        (saldo_id, receita_extra_id, tipo_origem, categoria, descricao, valor, data_recebimento),
    )
    conn.commit()
    conn.close()


def registrar_salario_recebido(
    nome_pessoa: str,
    valor: float,
    categoria: str = "salario",
    data_recebimento: Optional[str] = None,
) -> None:
    saldo = obter_saldo_por_nome(nome_pessoa)
    if not saldo:
        raise ValueError(f"Pessoa '{nome_pessoa}' nÃ£o encontrada em receitas_saldos.")
    atualizar_saldo(saldo.id, valor)
    _registrar_lancamento(
        saldo.id,
        tipo_origem="salario",
        categoria=categoria,
        valor=valor,
        descricao=f"Lançamento de {categoria}",
        data_recebimento=data_recebimento,
    )


def listar_receitas_extras() -> List[ReceitaExtra]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, descricao, valor_padrao, categoria, data_recebimento FROM receitas_extras ORDER BY descricao;"
    )
    rows = cur.fetchall()
    conn.close()
    return [ReceitaExtra(**dict(r)) for r in rows]


def criar_ou_atualizar_receita_extra(
    descricao: str,
    valor_padrao: Optional[float],
    categoria: str = "extra",
    data_recebimento: Optional[str] = None,
) -> ReceitaExtra:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO receitas_extras (descricao, valor_padrao, categoria, data_recebimento)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(descricao) DO UPDATE SET
            valor_padrao = excluded.valor_padrao,
            categoria = excluded.categoria,
            data_recebimento = excluded.data_recebimento;
        """,
        (descricao, valor_padrao, categoria, data_recebimento),
    )
    conn.commit()
    cur.execute(
        "SELECT id, descricao, valor_padrao, categoria, data_recebimento FROM receitas_extras WHERE descricao = ?;",
        (descricao,),
    )
    row = cur.fetchone()
    conn.close()
    return ReceitaExtra(**dict(row))


def atualizar_receita_extra(
    extra_id: int,
    descricao: str,
    valor_padrao: Optional[float],
    categoria: str,
    data_recebimento: Optional[str],
) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM receitas_extras WHERE id = ?;", (extra_id,))
    if not cur.fetchone():
        conn.close()
        return False
    cur.execute(
        """
        UPDATE receitas_extras
        SET descricao = ?, valor_padrao = ?, categoria = ?, data_recebimento = ?
        WHERE id = ?;
        """,
        (descricao, valor_padrao, categoria, data_recebimento, extra_id),
    )
    conn.commit()
    conn.close()
    return True


def excluir_receita_extra(extra_id: int) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM receitas_extras WHERE id = ?;", (extra_id,))
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def obter_receita_extra_por_id(extra_id: int) -> Optional[ReceitaExtra]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, descricao, valor_padrao, categoria, data_recebimento
        FROM receitas_extras
        WHERE id = ?;
        """,
        (extra_id,),
    )
    row = cur.fetchone()
    conn.close()
    return ReceitaExtra(**dict(row)) if row else None


def registrar_extra_recebido(
    saldo_id: int,
    valor: float,
    descricao: Optional[str] = None,
    categoria: str = "extra",
    receita_extra_id: Optional[int] = None,
    data_recebimento: Optional[str] = None,
) -> None:
    atualizar_saldo(saldo_id, valor)
    _registrar_lancamento(
        saldo_id,
        tipo_origem="extra",
        categoria=categoria,
        valor=valor,
        descricao=descricao or "Receita",
        receita_extra_id=receita_extra_id,
        data_recebimento=data_recebimento,
    )


def registrar_receita_agendada(
    saldo_id: int,
    categoria: str,
    valor: float,
    descricao: Optional[str],
    data_prevista: str,
    receita_extra_id: Optional[int] = None,
) -> None:
    _registrar_lancamento(
        saldo_id,
        tipo_origem="agendado",
        categoria=categoria,
        valor=valor,
        descricao=f"{descricao or 'Receita'} (previsto em {data_prevista})",
        receita_extra_id=receita_extra_id,
        data_recebimento=data_prevista,
    )


def processar_receitas_agendadas_vencidas(data_base: Optional[date] = None) -> int:
    """Converte lançamentos agendados (data <= hoje) para recebidos e aplica no saldo."""
    hoje = data_base or date.today()
    hoje_iso = hoje.isoformat()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, saldo_id, valor
        FROM receitas_lancamentos
        WHERE tipo_origem = 'agendado'
          AND data_recebimento IS NOT NULL
          AND data_recebimento <= ?;
        """,
        (hoje_iso,),
    )
    rows = cur.fetchall()
    if not rows:
        conn.close()
        return 0

    for r in rows:
        cur.execute(
            "UPDATE receitas_saldos SET saldo_atual = saldo_atual + ? WHERE id = ?;",
            (float(r["valor"]), int(r["saldo_id"])),
        )
        cur.execute(
            "UPDATE receitas_lancamentos SET tipo_origem = 'extra' WHERE id = ?;",
            (int(r["id"]),),
        )
    conn.commit()
    conn.close()
    return len(rows)


def registrar_abatimento_beneficio(
    nome_pessoa: str,
    receita_extra_id: int,
    valor: float,
    descricao_gasto: str,
) -> bool:
    if valor <= 0:
        return False
    saldo = obter_saldo_por_nome(nome_pessoa)
    beneficio = obter_receita_extra_por_id(receita_extra_id)
    if not saldo or not beneficio or beneficio.categoria != "beneficio":
        return False
    valor_abatimento = abs(float(valor))
    atualizar_saldo(saldo.id, -valor_abatimento)
    _registrar_lancamento(
        saldo.id,
        tipo_origem="gasto_beneficio",
        categoria="beneficio",
        valor=-valor_abatimento,
        descricao=f"Abatimento de benefício: {beneficio.descricao} - {descricao_gasto}",
        receita_extra_id=beneficio.id,
        data_recebimento=None,
    )
    return True


def calcular_totais_recebidos_por_extra() -> Dict[int, float]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT receita_extra_id, COALESCE(SUM(valor), 0) AS total
        FROM receitas_lancamentos
        WHERE receita_extra_id IS NOT NULL
          AND tipo_origem <> 'agendado'
          AND valor > 0
        GROUP BY receita_extra_id;
        """
    )
    rows = cur.fetchall()
    conn.close()
    return {int(r["receita_extra_id"]): float(r["total"]) for r in rows}


def listar_lancamentos_por_saldo(saldo_id: int) -> List[ReceitaLancamento]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, saldo_id, tipo_origem, categoria, descricao, valor, created_at, data_recebimento
        FROM receitas_lancamentos
        WHERE saldo_id = ?
        ORDER BY id DESC;
        """,
        (saldo_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return [ReceitaLancamento(**dict(r)) for r in rows]


def listar_lancamentos_por_receita_extra(extra_id: int) -> List[ReceitaLancamento]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, saldo_id, tipo_origem, categoria, descricao, valor, created_at, data_recebimento
        FROM receitas_lancamentos
        WHERE receita_extra_id = ?
        ORDER BY id DESC;
        """,
        (extra_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return [ReceitaLancamento(**dict(r)) for r in rows]


def listar_resumo_beneficios_por_saldo(saldo_id: int) -> List[Dict[str, object]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT rl.id, rl.receita_extra_id, rl.descricao, rl.valor, rl.tipo_origem, rl.created_at,
               re.descricao AS nome_beneficio
        FROM receitas_lancamentos rl
        JOIN receitas_extras re ON re.id = rl.receita_extra_id
        WHERE rl.saldo_id = ?
          AND re.categoria = 'beneficio'
        ORDER BY rl.id ASC;
        """,
        (saldo_id,),
    )
    rows = cur.fetchall()
    conn.close()

    agrupado: Dict[int, Dict[str, object]] = {}
    for r in rows:
        rid = int(r["receita_extra_id"])
        item = agrupado.setdefault(
            rid,
            {
                "receita_extra_id": rid,
                "nome": str(r["nome_beneficio"]),
                "total": 0.0,
                "total_gasto": 0.0,
                "gastos": [],
            },
        )
        valor = float(r["valor"])
        if str(r["tipo_origem"]) != "agendado":
            item["total"] = float(item["total"]) + valor
        if valor < 0:
            gasto_val = abs(valor)
            item["total_gasto"] = float(item["total_gasto"]) + gasto_val
            item["gastos"].append(
                {
                    "descricao": str(r["descricao"] or ""),
                    "valor": gasto_val,
                    "created_at": str(r["created_at"]),
                }
            )

    resultado = list(agrupado.values())
    resultado.sort(key=lambda x: str(x["nome"]).lower())
    return resultado


def excluir_lancamento_receita(lancamento_id: int) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, saldo_id, valor, tipo_origem
        FROM receitas_lancamentos
        WHERE id = ?;
        """,
        (lancamento_id,),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return False

    saldo_id = int(row["saldo_id"])
    valor = float(row["valor"])
    tipo_origem = str(row["tipo_origem"])

    if tipo_origem != "agendado":
        cur.execute(
            "UPDATE receitas_saldos SET saldo_atual = saldo_atual - ? WHERE id = ?;",
            (valor, saldo_id),
        )
    cur.execute("DELETE FROM receitas_lancamentos WHERE id = ?;", (lancamento_id,))
    conn.commit()
    conn.close()
    return True


def atualizar_lancamento_receita(
    lancamento_id: int,
    categoria: str,
    descricao: Optional[str],
    valor_novo: float,
) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, saldo_id, valor, tipo_origem
        FROM receitas_lancamentos
        WHERE id = ?;
        """,
        (lancamento_id,),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return False

    saldo_id = int(row["saldo_id"])
    valor_antigo = float(row["valor"])
    tipo_origem = str(row["tipo_origem"])
    delta = valor_novo - valor_antigo

    cur.execute(
        """
        UPDATE receitas_lancamentos
        SET categoria = ?, descricao = ?, valor = ?
        WHERE id = ?;
        """,
        (categoria, descricao, valor_novo, lancamento_id),
    )
    if tipo_origem != "agendado":
        cur.execute(
            "UPDATE receitas_saldos SET saldo_atual = saldo_atual + ? WHERE id = ?;",
            (delta, saldo_id),
        )
    conn.commit()
    conn.close()
    return True


def calcular_totais_lancamentos_por_categoria(saldo_id: int) -> Dict[str, float]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT categoria, COALESCE(SUM(valor), 0) AS total
        FROM receitas_lancamentos
        WHERE saldo_id = ?
          AND tipo_origem <> 'agendado'
        GROUP BY categoria;
        """,
        (saldo_id,),
    )
    rows = cur.fetchall()
    conn.close()
    totais = {"salario": 0.0, "beneficio": 0.0, "bonus": 0.0, "extra": 0.0}
    for r in rows:
        cat = str(r["categoria"])
        if cat in totais:
            totais[cat] = float(r["total"])
        else:
            totais[cat] = float(r["total"])
    # Regra solicitada: extras e bônus compõem o total de salário.
    totais["salario"] = totais.get("salario", 0.0) + totais.get("extra", 0.0) + totais.get("bonus", 0.0)
    return totais


def calcular_totais_receitas() -> Tuple[float, float, float, float]:
    """Retorna (saldo_gabriela, saldo_kristian, extras, total_geral)."""
    conn = get_connection()
    cur = conn.cursor()
    hoje_iso = date.today().isoformat()

    cur.execute(
        """
        SELECT COALESCE(SUM(rl.valor), 0) AS total
        FROM receitas_lancamentos rl
        JOIN receitas_saldos rs ON rs.id = rl.saldo_id
        WHERE rs.nome = 'Gabriela'
          AND rl.tipo_origem <> 'agendado'
          AND (rl.data_recebimento IS NULL OR rl.data_recebimento <= ?);
        """,
        (hoje_iso,),
    )
    saldo_gabriela = float(cur.fetchone()["total"])

    cur.execute(
        """
        SELECT COALESCE(SUM(rl.valor), 0) AS total
        FROM receitas_lancamentos rl
        JOIN receitas_saldos rs ON rs.id = rl.saldo_id
        WHERE rs.nome = 'Kristian'
          AND rl.tipo_origem <> 'agendado'
          AND (rl.data_recebimento IS NULL OR rl.data_recebimento <= ?);
        """,
        (hoje_iso,),
    )
    saldo_kristian = float(cur.fetchone()["total"])

    cur.execute(
        """
        SELECT COALESCE(SUM(valor), 0) AS total
        FROM receitas_lancamentos
        WHERE tipo_origem <> 'agendado'
          AND (data_recebimento IS NULL OR data_recebimento <= ?);
        """,
        (hoje_iso,),
    )
    total_saldos = float(cur.fetchone()["total"])

    extras = max(total_saldos - (saldo_gabriela + saldo_kristian), 0.0)
    total_geral = total_saldos

    conn.close()
    return saldo_gabriela, saldo_kristian, extras, total_geral


def calcular_resumo_receitas_padrao(nomes_padrao: List[str]) -> Tuple[List[Dict[str, float | str]], float]:
    nomes = [n.strip() for n in nomes_padrao if n and n.strip()]
    if not nomes:
        return [], 0.0

    conn = get_connection()
    cur = conn.cursor()
    hoje_iso = date.today().isoformat()
    placeholders = ", ".join(["?"] * len(nomes))
    params: List[object] = [hoje_iso, *nomes]
    cur.execute(
        f"""
        SELECT rs.nome, rl.categoria, COALESCE(SUM(rl.valor), 0) AS total
        FROM receitas_lancamentos rl
        JOIN receitas_saldos rs ON rs.id = rl.saldo_id
        WHERE rl.tipo_origem <> 'agendado'
          AND (rl.data_recebimento IS NULL OR rl.data_recebimento <= ?)
          AND rs.nome IN ({placeholders})
        GROUP BY rs.nome, rl.categoria;
        """,
        params,
    )
    rows = cur.fetchall()
    conn.close()

    mapa: Dict[str, Dict[str, float | str]] = {
        nome: {"nome": nome, "saldo_conta": 0.0, "saldo_beneficio": 0.0}
        for nome in nomes
    }
    for r in rows:
        nome = str(r["nome"])
        categoria = str(r["categoria"])
        total = float(r["total"])
        if nome not in mapa:
            continue
        if categoria in {"salario", "extra", "bonus"}:
            mapa[nome]["saldo_conta"] = float(mapa[nome]["saldo_conta"]) + total
        elif categoria == "beneficio":
            mapa[nome]["saldo_beneficio"] = float(mapa[nome]["saldo_beneficio"]) + total

    resumo = [mapa[n] for n in sorted(mapa.keys(), key=lambda x: x.lower())]
    total_geral = sum(
        float(item["saldo_conta"]) + float(item["saldo_beneficio"]) for item in resumo
    )
    return resumo, total_geral


def calcular_saldos_beneficios_disponiveis() -> List[Dict[str, float | str]]:
    conn = get_connection()
    cur = conn.cursor()
    hoje_iso = date.today().isoformat()
    cur.execute(
        """
        SELECT re.id, re.descricao, COALESCE(SUM(rl.valor), 0) AS saldo_disponivel
        FROM receitas_extras re
        LEFT JOIN receitas_lancamentos rl
            ON rl.receita_extra_id = re.id
           AND rl.categoria = 'beneficio'
           AND rl.tipo_origem <> 'agendado'
           AND (rl.data_recebimento IS NULL OR rl.data_recebimento <= ?)
        WHERE re.categoria = 'beneficio'
        GROUP BY re.id, re.descricao
        ORDER BY re.descricao;
        """,
        (hoje_iso,),
    )
    rows = cur.fetchall()
    conn.close()
    return [
        {"beneficio": str(r["descricao"]), "saldo_disponivel": float(r["saldo_disponivel"])}
        for r in rows
    ]


def calcular_saldos_beneficios_por_pessoa(
    nomes_padrao: List[str],
) -> Dict[str, List[Dict[str, float | str]]]:
    nomes = [n.strip() for n in nomes_padrao if n and n.strip()]
    if not nomes:
        return {}

    conn = get_connection()
    cur = conn.cursor()
    hoje_iso = date.today().isoformat()
    placeholders = ", ".join(["?"] * len(nomes))
    params: List[object] = [hoje_iso, *nomes]
    cur.execute(
        f"""
        SELECT rs.nome AS pessoa, re.descricao AS beneficio, COALESCE(SUM(rl.valor), 0) AS saldo_disponivel
        FROM receitas_lancamentos rl
        JOIN receitas_saldos rs ON rs.id = rl.saldo_id
        JOIN receitas_extras re ON re.id = rl.receita_extra_id
        WHERE re.categoria = 'beneficio'
          AND rl.tipo_origem <> 'agendado'
          AND (rl.data_recebimento IS NULL OR rl.data_recebimento <= ?)
          AND rs.nome IN ({placeholders})
        GROUP BY rs.nome, re.descricao
        ORDER BY rs.nome, re.descricao;
        """,
        params,
    )
    rows = cur.fetchall()
    conn.close()

    por_pessoa: Dict[str, List[Dict[str, float | str]]] = {nome: [] for nome in nomes}
    for r in rows:
        pessoa = str(r["pessoa"])
        por_pessoa.setdefault(pessoa, [])
        por_pessoa[pessoa].append(
            {
                "beneficio": str(r["beneficio"]),
                "saldo_disponivel": float(r["saldo_disponivel"]),
            }
        )
    return por_pessoa

