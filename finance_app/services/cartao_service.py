from __future__ import annotations

from datetime import date
import re
import unicodedata
from typing import Dict, List, Tuple

from finance_app.database import USE_POSTGRES, get_connection
from finance_app.models import CartaoCategoria, CartaoConfig, CartaoParcelada, CartaoAvista


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


def _extrair_parcela_descricao(texto: object | None) -> Tuple[int | None, int | None]:
    descricao = str(texto or "")
    match = re.search(r"parcela\s+(\d+)\s*/\s*(\d+)", descricao, flags=re.IGNORECASE)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def listar_categorias() -> List[CartaoCategoria]:
    conn = get_connection()
    cur = conn.cursor()
    if USE_POSTGRES:
        cur.execute("SELECT id, nome FROM cartao_categorias ORDER BY LOWER(nome);")
    else:
        cur.execute("SELECT id, nome FROM cartao_categorias ORDER BY nome COLLATE NOCASE;")
    rows = cur.fetchall()
    conn.close()
    return [CartaoCategoria(id=int(r["id"]), nome=str(r["nome"])) for r in rows]


def criar_categoria(nome: str) -> int | None:
    nome_limpo = str(nome or "").strip()
    if not nome_limpo:
        return None
    conn = get_connection()
    cur = conn.cursor()
    try:
        if USE_POSTGRES:
            cur.execute(
                "INSERT INTO cartao_categorias (nome) VALUES (?) RETURNING id;",
                (nome_limpo,),
            )
            row = cur.fetchone()
            categoria_id = int(row["id"]) if row else None
        else:
            cur.execute("INSERT INTO cartao_categorias (nome) VALUES (?);", (nome_limpo,))
            categoria_id = int(cur.lastrowid) if cur.lastrowid else None
        conn.commit()
        return categoria_id
    except Exception:
        conn.rollback()
        return None
    finally:
        conn.close()


def _contar_lancamentos_categoria(cur, categoria_id: int) -> int:
    cur.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM cartao_avista WHERE categoria_id = ?)
          + (SELECT COUNT(*) FROM cartao_parceladas WHERE categoria_id = ?)
          AS total;
        """,
        (categoria_id, categoria_id),
    )
    row = cur.fetchone()
    return int(row["total"] or 0) if row else 0


def atualizar_categoria(categoria_id: int, nome: str) -> Dict[str, object]:
    """
    Renomeia a categoria. Lançamentos antigos seguem o mesmo id e passam a exibir o nome novo.
    Se o nome já existir em outra categoria, une os lançamentos na existente e remove a duplicada.
    """
    nome_limpo = str(nome or "").strip()
    if categoria_id <= 0 or not nome_limpo:
        return {"ok": False, "lancamentos": 0, "mesclada": False}

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, nome FROM cartao_categorias WHERE id = ?;", (categoria_id,))
        atual = cur.fetchone()
        if not atual:
            return {"ok": False, "lancamentos": 0, "mesclada": False}

        if USE_POSTGRES:
            cur.execute(
                """
                SELECT id FROM cartao_categorias
                WHERE LOWER(TRIM(nome)) = LOWER(TRIM(?)) AND id <> ?;
                """,
                (nome_limpo, categoria_id),
            )
        else:
            cur.execute(
                """
                SELECT id FROM cartao_categorias
                WHERE LOWER(TRIM(nome)) = LOWER(TRIM(?)) AND id <> ?;
                """,
                (nome_limpo, categoria_id),
            )
        existente = cur.fetchone()
        mesclada = False

        if existente:
            alvo_id = int(existente["id"])
            cur.execute(
                "UPDATE cartao_avista SET categoria_id = ? WHERE categoria_id = ?;",
                (alvo_id, categoria_id),
            )
            cur.execute(
                "UPDATE cartao_parceladas SET categoria_id = ? WHERE categoria_id = ?;",
                (alvo_id, categoria_id),
            )
            cur.execute("DELETE FROM cartao_categorias WHERE id = ?;", (categoria_id,))
            total = _contar_lancamentos_categoria(cur, alvo_id)
            mesclada = True
            nome_final = nome_limpo
        else:
            cur.execute(
                "UPDATE cartao_categorias SET nome = ? WHERE id = ?;",
                (nome_limpo, categoria_id),
            )
            total = _contar_lancamentos_categoria(cur, categoria_id)
            nome_final = nome_limpo

        conn.commit()
        return {
            "ok": True,
            "lancamentos": total,
            "mesclada": mesclada,
            "nome": nome_final,
            "nome_anterior": str(atual["nome"]),
        }
    except Exception:
        conn.rollback()
        return {"ok": False, "lancamentos": 0, "mesclada": False}
    finally:
        conn.close()


def excluir_categoria(categoria_id: int) -> bool:
    if categoria_id <= 0:
        return False
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM cartao_categorias WHERE id = ?;", (categoria_id,))
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def categoria_existe(categoria_id: int | None) -> bool:
    if categoria_id is None:
        return True
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM cartao_categorias WHERE id = ? LIMIT 1;", (categoria_id,))
    ok = cur.fetchone() is not None
    conn.close()
    return ok


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
               mes_inicio, ano_inicio, status, pessoa_id, categoria_id
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
               mes_inicio, ano_inicio, status, pessoa_id, categoria_id
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
    categoria_id: int | None = None,
) -> None:
    if categoria_id is None:
        categoria_id = resolver_categoria_id_por_descricao(descricao)
    valor_parcela = valor_total / total_parcelas if total_parcelas else valor_total
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO cartao_parceladas
        (descricao, valor_parcela, total_parcelas, parcela_atual, mes_inicio, ano_inicio, status, pessoa_id, categoria_id)
        VALUES (?, ?, ?, ?, ?, ?, 'Ativa', ?, ?);
        """,
        (descricao, valor_parcela, total_parcelas, parcela_atual, mes_inicio, ano_inicio, pessoa_id, categoria_id),
    )
    conn.commit()
    conn.close()


def registrar_compra_avista(
    descricao: str,
    valor: float,
    pessoa_id: int | None,
    mes_referencia: int | None = None,
    ano_referencia: int | None = None,
    categoria_id: int | None = None,
) -> None:
    if categoria_id is None:
        categoria_id = resolver_categoria_id_por_descricao(descricao)
    if mes_referencia is None or ano_referencia is None:
        mes_ref, ano_ref = mes_ano_fatura_atual()
    else:
        mes_ref, ano_ref = mes_referencia, ano_referencia
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO cartao_avista (descricao, valor, mes_referencia, ano_referencia, pessoa_id, categoria_id)
        VALUES (?, ?, ?, ?, ?, ?);
        """,
        (descricao, valor, mes_ref, ano_ref, pessoa_id, categoria_id),
    )
    conn.commit()
    conn.close()


def listar_avista_mes(mes: int, ano: int) -> List[CartaoAvista]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, descricao, valor, mes_referencia, ano_referencia, pessoa_id, categoria_id
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
    # A competência em aberto segue apenas a regra de fechamento.
    # A flag fatura_paga indica status da competência exibida, mas não deve
    # empurrar automaticamente a navegação para o mês seguinte.
    return mes_ano_fatura_atual(hoje=hoje)


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


def listar_gastos_por_categoria_competencia(mes_ref: int, ano_ref: int) -> Dict[str, object]:
    """Agrupa lançamentos do cartão na competência (à vista + parcela do mês) por categoria."""
    idx_alvo = _indice_competencia(mes_ref, ano_ref)
    grupos: Dict[int | None, List[Dict[str, object]]] = {}

    def add_item(categoria_id: int | None, descricao: str, valor: float) -> None:
        grupos.setdefault(categoria_id, []).append(
            {"descricao": str(descricao), "valor": float(valor)}
        )

    for avista in listar_avista_mes(mes_ref, ano_ref):
        add_item(avista.categoria_id, avista.descricao, float(avista.valor))

    for parcelada in listar_parceladas():
        idx_inicio = _indice_competencia(int(parcelada.mes_inicio), int(parcelada.ano_inicio))
        parcela_num = idx_alvo - idx_inicio + 1
        if parcela_num < 1 or parcela_num > int(parcelada.total_parcelas):
            continue
        descricao = (
            f"{parcelada.descricao} (parcela {parcela_num}/{parcelada.total_parcelas})"
        )
        add_item(parcelada.categoria_id, descricao, float(parcelada.valor_parcela))

    nomes_categoria: Dict[int | None, str] = {None: "Sem categoria"}
    for categoria in listar_categorias():
        nomes_categoria[categoria.id] = categoria.nome

    categorias: List[Dict[str, object]] = []
    total = 0.0
    for categoria_id, itens in grupos.items():
        subtotal = sum(float(item["valor"]) for item in itens)
        total += subtotal
        categorias.append(
            {
                "id": categoria_id,
                "nome": nomes_categoria.get(categoria_id, "Sem categoria"),
                "valor": subtotal,
                "itens": sorted(itens, key=lambda item: float(item["valor"]), reverse=True),
            }
        )

    categorias.sort(key=lambda item: float(item["valor"]), reverse=True)
    for categoria in categorias:
        categoria["percentual"] = (float(categoria["valor"]) / total * 100.0) if total > 0 else 0.0

    return {
        "mes_referencia": mes_ref,
        "ano_referencia": ano_ref,
        "total": total,
        "categorias": categorias,
    }


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
            ca.id,
            ca.descricao,
            ca.valor AS valor,
            NULL AS total_parcelas,
            NULL AS parcela_atual,
            ca.mes_referencia AS mes_ref,
            ca.ano_referencia AS ano_ref,
            'Lançado' AS status,
            ca.pessoa_id,
            ca.categoria_id,
            cc.nome AS categoria_nome
        FROM cartao_avista ca
        LEFT JOIN cartao_categorias cc ON cc.id = ca.categoria_id
        ORDER BY ca.ano_referencia DESC, ca.mes_referencia DESC, ca.id DESC;
        """
    )
    rows.extend(dict(r) for r in cur.fetchall())

    cur.execute(
        """
        SELECT
            cp.id,
            cp.descricao,
            cp.valor_parcela AS valor,
            cp.total_parcelas,
            cp.parcela_atual,
            cp.mes_inicio,
            cp.ano_inicio,
            cp.status,
            cp.pessoa_id,
            cp.categoria_id,
            cc.nome AS categoria_nome
        FROM cartao_parceladas cp
        LEFT JOIN cartao_categorias cc ON cc.id = cp.categoria_id
        ORDER BY cp.ano_inicio DESC, cp.mes_inicio DESC, cp.id DESC;
        """
    )
    parceladas = [dict(r) for r in cur.fetchall()]
    historico_primeira_competencia: Dict[int, int] = {}
    if parceladas:
        ids_parceladas = [int(item["id"]) for item in parceladas]
        filtros_ids = ", ".join(["?"] * len(ids_parceladas))
        cur.execute(
            f"""
            SELECT item_id, descricao_item, mes_referencia, ano_referencia
            FROM pagamentos_terceiros_itens
            WHERE tipo = 'cartao_parcelada'
              AND item_id IN ({filtros_ids});
            """,
            tuple(ids_parceladas),
        )
        for row in cur.fetchall():
            item_id = int(row["item_id"])
            parcela_num, _ = _extrair_parcela_descricao(row["descricao_item"])
            if parcela_num is None:
                continue
            idx_primeiro = _indice_competencia(
                int(row["mes_referencia"]),
                int(row["ano_referencia"]),
            ) - (parcela_num - 1)
            if item_id not in historico_primeira_competencia or idx_primeiro < historico_primeira_competencia[item_id]:
                historico_primeira_competencia[item_id] = idx_primeiro

    for item in parceladas:
        total_parcelas = int(item.get("total_parcelas") or 1)
        parcela_atual = int(item.get("parcela_atual") or 1)
        status = str(item.get("status") or "")
        idx_primeiro = historico_primeira_competencia.get(int(item["id"]))
        if idx_primeiro is None:
            # mes_inicio/ano_inicio no cadastro = competência da 1ª parcela (igual à fatura).
            mes_inicio = int(item.get("mes_inicio") or 1)
            ano_inicio = int(item.get("ano_inicio") or date.today().year)
        else:
            mes_inicio, ano_inicio = (idx_primeiro % 12) + 1, idx_primeiro // 12

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
                    "categoria_id": item.get("categoria_id"),
                    "categoria_nome": item.get("categoria_nome"),
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
    categoria_id: int | None = None,
) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE cartao_avista
        SET descricao = ?, valor = ?, pessoa_id = ?, mes_referencia = ?, ano_referencia = ?, categoria_id = ?
        WHERE id = ?;
        """,
        (descricao, valor, pessoa_id, mes_referencia, ano_referencia, categoria_id, lancamento_id),
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
    categoria_id: int | None = None,
) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE cartao_parceladas
        SET descricao = ?, valor_parcela = ?, parcela_atual = ?, total_parcelas = ?, status = COALESCE(?, status), pessoa_id = ?, mes_inicio = ?, ano_inicio = ?, categoria_id = ?
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
            categoria_id,
            lancamento_id,
        ),
    )
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


CATEGORIAS_PADRAO_ORDEM: Tuple[str, ...] = (
    "Internet e assinaturas",
    "Calçados",
    "Roupas",
    "Eventos e festas",
    "Viagens e hospedagem",
    "Moradia",
    "Alimentação",
    "Lanches/Delivery",
    "Restaurantes",
    "Transporte",
    "Saúde e farmácia",
    "Beleza e estética",
    "Casa e utilidades",
    "Tecnologia",
    "Veículos",
    "Presentes",
    "Pets",
    "Lazer e entretenimento",
    "Outros",
)


def _normalizar_descricao_categoria(texto: str) -> str:
    texto = str(texto or "").strip().lower()
    texto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def classificar_descricao_categoria(descricao: str) -> str:
    """Sugere categoria com base em palavras-chave da descrição do lançamento."""
    t = _normalizar_descricao_categoria(descricao)

    def tem(*palavras: str) -> bool:
        return any(p in t for p in palavras)

    if tem(
        "spotify",
        "youtube",
        "gympass",
        "premium",
        "cinemark clube",
        "smiles",
        "milhas",
    ):
        return "Internet e assinaturas"
    if tem("tenis", "vans", "nike", "centauro", "salto", "arrezo"):
        return "Calçados"
    if tem("noiva", "aniversario", "imersao", "the send", "fifa"):
        return "Eventos e festas"
    if tem("vestido") and "noiva" not in t:
        return "Roupas"
    if tem("shein", "renner", "vivacci", "kris roupa", "camisa amor", "minha compra", "mala amor"):
        return "Roupas"
    if tem(
        "airbnb",
        "hotel",
        "passagem",
        "bombinhas",
        "guarda sol",
        "barco praia",
        "cabana",
        "praia da conceicao",
    ):
        return "Viagens e hospedagem"
    if tem("aluguel", "condominio"):
        return "Moradia"
    if tem(
        "ifood",
        "rappi",
        "uber eats",
        "ubereats",
        "99food",
        "99 food",
        "aiqfome",
        "pede.ai",
        "pede ai",
        "ze delivery",
        "zedelivery",
        "anota ai",
        "anotaai",
        "pedido ifood",
        "ifood pedido",
        "ifood*",
        "delivery",
        "loggi comida",
        "keeta",
        "cardapio web",
        "menudino",
        "goomer",
        "james delivery",
        "mcdonald",
        "burger king",
        " bk ",
        "subway",
        "habib",
        "giraffas",
        "bobs",
        "kfc",
        "taco bell",
        "spoleto",
        "hamburger",
        "hamburguer",
        "lanche",
        "fast food",
        "five guys",
        "pizza hut",
        "dominos",
        "domino",
        "popeyes",
        "china in box",
        "chinabox",
        "hot dog",
        "hotdog",
        "mister pizza",
        "pizza crek",
        "pastel",
        "crepe",
        "salgado",
        "lanchonete",
    ):
        return "Lanches/Delivery"
    if tem(
        "restaurante",
        "churrasc",
        "churrasco",
        "ruina bar",
        "oliveiras",
        "outback",
        "madero",
        "cantina",
        "bistro",
        "pub ",
        "pizzaria",
        "jantar",
        "almoco fora",
        "almoço fora",
        "comer fora",
        "saiu pra comer",
        "saiu para comer",
        "rodizio",
        "rodízio",
        "sushi",
        "japa ",
        "temaki",
        "starbucks",
        "cafeteria",
        "cervejaria",
        "choperia",
        "boteco",
        "bar e",
        "no bar",
        "no restaurante",
    ):
        return "Restaurantes"
    if tem(
        "mercadinho",
        "kompro",
        "komprao",
        "supermerc",
        "atacadao",
        "carrefour",
        "pao de acucar",
        "extra hiper",
        "assai",
        "hortifruti",
        "sacolao",
        "cafe da manha",
        "almoco",
        "almoço",
        "refri",
        "sorvete",
        "cheetos",
    ):
        return "Alimentação"
    if tem("uber", "estacionamento", "cast"):
        return "Transporte"
    if "gasolina" in t or "posto" in t:
        return "Transporte"
    if tem("farmacia", "panvel", "monjauro", "anticoncepcional", "durepox"):
        return "Saúde e farmácia"
    if tem("salao", "perfume", "zaad", "oculos", "zeiss", "lente"):
        return "Beleza e estética"
    if tem("panelas", "forno", "ninja", "copo descartavel", "papelaria", "balanca", "fischer"):
        return "Casa e utilidades"
    if tem(
        "iphone",
        "iplace",
        "carregador",
        "mercado livre",
        "meli",
        "maquina de sorvete",
        "diferenca fatura",
    ):
        return "Tecnologia"
    if tem("mecanico", "pneu", "seguro carro", "seguro cartao", "loovi"):
        return "Veículos"
    if tem("presente", "tatavio"):
        return "Presentes"
    if tem("juninhos dog", " dog"):
        return "Pets"
    if tem("cinema", "ingresso", "show ", "teatro", "parque"):
        return "Lazer e entretenimento"

    return "Outros"


def _migrar_categorias_comida_antigas(cur, nome_para_id: Dict[str, int]) -> None:
    """Unifica nomes antigos (Delivery, Lanches…) nos atuais Lanches/Delivery e Restaurantes."""
    alvo_lanches = nome_para_id.get("Lanches/Delivery")
    alvo_rest = nome_para_id.get("Restaurantes")
    if alvo_lanches is None and alvo_rest is None:
        return

    fusao_lanches = ("Delivery", "Lanches e fast food")
    renomear_rest = "Restaurantes e bares"

    for nome_antigo in fusao_lanches:
        antigo_id = nome_para_id.get(nome_antigo)
        if antigo_id is None or alvo_lanches is None or antigo_id == alvo_lanches:
            continue
        cur.execute(
            "UPDATE cartao_avista SET categoria_id = ? WHERE categoria_id = ?;",
            (alvo_lanches, antigo_id),
        )
        cur.execute(
            "UPDATE cartao_parceladas SET categoria_id = ? WHERE categoria_id = ?;",
            (alvo_lanches, antigo_id),
        )
        cur.execute("DELETE FROM cartao_categorias WHERE id = ?;", (antigo_id,))
        nome_para_id.pop(nome_antigo, None)

    antigo_rest_id = nome_para_id.get(renomear_rest)
    if antigo_rest_id is not None and alvo_rest is not None and antigo_rest_id != alvo_rest:
        cur.execute(
            "UPDATE cartao_avista SET categoria_id = ? WHERE categoria_id = ?;",
            (alvo_rest, antigo_rest_id),
        )
        cur.execute(
            "UPDATE cartao_parceladas SET categoria_id = ? WHERE categoria_id = ?;",
            (alvo_rest, antigo_rest_id),
        )
        cur.execute("DELETE FROM cartao_categorias WHERE id = ?;", (antigo_rest_id,))
        nome_para_id.pop(renomear_rest, None)
    elif antigo_rest_id is not None and alvo_rest is None:
        cur.execute(
            "UPDATE cartao_categorias SET nome = ? WHERE id = ?;",
            ("Restaurantes", antigo_rest_id),
        )
        nome_para_id["Restaurantes"] = antigo_rest_id
        nome_para_id.pop(renomear_rest, None)


def garantir_categorias_padrao(conn=None) -> Dict[str, int]:
    """Garante que todas as categorias padrão existem; retorna mapa nome -> id."""
    close_conn = conn is None
    conn_local = conn or get_connection()
    cur = conn_local.cursor()
    nome_para_id: Dict[str, int] = {}
    try:
        for nome in CATEGORIAS_PADRAO_ORDEM:
            if USE_POSTGRES:
                cur.execute(
                    "INSERT INTO cartao_categorias (nome) VALUES (?) ON CONFLICT (nome) DO NOTHING;",
                    (nome,),
                )
            else:
                cur.execute(
                    "INSERT OR IGNORE INTO cartao_categorias (nome) VALUES (?);",
                    (nome,),
                )
        cur.execute("SELECT id, nome FROM cartao_categorias;")
        for row in cur.fetchall():
            nome_para_id[str(row["nome"])] = int(row["id"])
        _migrar_categorias_comida_antigas(cur, nome_para_id)
        cur.execute("SELECT id, nome FROM cartao_categorias;")
        nome_para_id = {str(row["nome"]): int(row["id"]) for row in cur.fetchall()}
        if close_conn:
            conn_local.commit()
        return nome_para_id
    finally:
        if close_conn:
            conn_local.close()


def resolver_categoria_id_por_descricao(
    descricao: str,
    conn=None,
) -> int | None:
    """Retorna id da categoria sugerida para a descrição, ou None."""
    nome = classificar_descricao_categoria(descricao)
    mapa = garantir_categorias_padrao(conn=conn)
    return mapa.get(nome)


def reclassificar_lancamentos_por_descricao(
    conn=None,
    *,
    reset_categorias: bool = False,
) -> Dict[str, int]:
    """
    Aplica classificação automática em todos os lançamentos.
    Com reset_categorias=True, recria a lista padrão (como o script reseed).
    """
    close_conn = conn is None
    conn_local = conn or get_connection()
    cur = conn_local.cursor()
    stats: Dict[str, int] = {nome: 0 for nome in CATEGORIAS_PADRAO_ORDEM}

    try:
        if reset_categorias:
            cur.execute("UPDATE cartao_avista SET categoria_id = NULL;")
            cur.execute("UPDATE cartao_parceladas SET categoria_id = NULL;")
            cur.execute("DELETE FROM cartao_categorias;")
            if close_conn:
                conn_local.commit()

        nome_para_id = garantir_categorias_padrao(conn=conn_local)
        if close_conn:
            conn_local.commit()

        cur.execute("SELECT id, descricao FROM cartao_avista;")
        for row in cur.fetchall():
            cat = classificar_descricao_categoria(row["descricao"])
            stats[cat] = stats.get(cat, 0) + 1
            cat_id = nome_para_id.get(cat)
            cur.execute(
                "UPDATE cartao_avista SET categoria_id = ? WHERE id = ?;",
                (cat_id, int(row["id"])),
            )

        cur.execute("SELECT id, descricao FROM cartao_parceladas;")
        for row in cur.fetchall():
            cat = classificar_descricao_categoria(row["descricao"])
            stats[cat] = stats.get(cat, 0) + 1
            cat_id = nome_para_id.get(cat)
            cur.execute(
                "UPDATE cartao_parceladas SET categoria_id = ? WHERE id = ?;",
                (cat_id, int(row["id"])),
            )

        if close_conn:
            conn_local.commit()
        return stats
    finally:
        if close_conn:
            conn_local.close()

