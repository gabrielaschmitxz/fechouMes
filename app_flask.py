"""Aplicação Flask principal para Fechou Mês - Controle Financeiro"""
from flask import Flask, render_template, request, redirect, url_for, flash, session, g
from datetime import datetime
from decimal import Decimal
import logging
import sys
import os
import time
from pathlib import Path

# Adiciona o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent))

from finance_app.database import setup_database, get_connection, USE_POSTGRES
from finance_app.services import (
    cartao_service,
    contas_service,
    pessoas_service,
    auth_service,
)

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me")
app.logger.setLevel(logging.INFO)

# Inicializa banco de dados
setup_database()
app.logger.info("App iniciada com backend de banco: %s", "postgres" if USE_POSTGRES else "sqlite")


def _mes_ano_atual():
    """Retorna mês e ano atuais"""
    hoje = datetime.now()
    return hoje.month, hoje.year


_MESES_NOMES = [
    "",
    "Janeiro",
    "Fevereiro",
    "Março",
    "Abril",
    "Maio",
    "Junho",
    "Julho",
    "Agosto",
    "Setembro",
    "Outubro",
    "Novembro",
    "Dezembro",
]


def _normalizar_competencia(mes_raw, ano_raw, mes_padrao: int, ano_padrao: int):
    try:
        mes = int(mes_raw)
        ano = int(ano_raw)
    except (TypeError, ValueError):
        return mes_padrao, ano_padrao
    if mes < 1 or mes > 12:
        return mes_padrao, ano_padrao
    if ano < 2000 or ano > 2100:
        return mes_padrao, ano_padrao
    return mes, ano


def _listar_competencias(base_mes: int, base_ano: int):
    competencias = []
    inicio = (base_ano * 12 + base_mes - 1) - 12
    fim = (base_ano * 12 + base_mes - 1) + 18
    for indice in range(inicio, fim + 1):
        ano = indice // 12
        mes = (indice % 12) + 1
        competencias.append(
            {
                "mes": mes,
                "ano": ano,
                "label": f"{mes:02d}/{ano} - {_MESES_NOMES[mes]}",
            }
        )
    return competencias


def _deslocar_competencia(mes: int, ano: int, delta: int):
    indice = (ano * 12 + mes - 1) + delta
    return (indice % 12) + 1, indice // 12


def _parse_categoria_id(raw_value) -> int | None:
    texto = str(raw_value or "").strip()
    if not texto:
        return None
    try:
        categoria_id = int(texto)
    except (TypeError, ValueError):
        return None
    return categoria_id if categoria_id > 0 else None


def _cartao_redirect_params(default_aba: str = "principal") -> dict:
    """Preserva aba, competências e ordenação após POST na tela do cartão."""
    aba = (request.form.get("ret_aba") or request.args.get("aba") or default_aba).strip().lower()
    if aba not in {"principal", "categorias", "lancamentos"}:
        aba = default_aba

    params: dict = {"aba": aba}
    for key in (
        "mes_fatura",
        "ano_fatura",
        "mes_lancamento",
        "ano_lancamento",
        "sort_by",
        "sort_dir",
    ):
        valor = request.form.get(f"ret_{key}") or request.args.get(key)
        if valor is None or str(valor).strip() == "":
            continue
        if key in {"mes_fatura", "ano_fatura", "mes_lancamento", "ano_lancamento"}:
            try:
                params[key] = int(valor)
            except (TypeError, ValueError):
                continue
        else:
            params[key] = str(valor).strip()
    return params


def _redirect_cartao(default_aba: str = "principal"):
    return redirect(url_for("cartao", **_cartao_redirect_params(default_aba)))


def _parse_brl_value(raw_value, default=0.0):
    if raw_value is None:
        return default
    if isinstance(raw_value, (int, float)):
        return float(raw_value)

    value = str(raw_value).strip()
    if not value:
        return default

    value = value.replace("R$", "").replace(" ", "")
    if "," in value:
        value = value.replace(".", "").replace(",", ".")

    try:
        return float(value)
    except ValueError:
        return default


def _to_float(value, default=0.0):
    if value is None:
        return default
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@app.before_request
def _require_login():
    g.request_started_at = time.perf_counter()
    if request.path == "/favicon.ico":
        return "", 204
    public_endpoints = {"login", "static"}
    if request.endpoint is None or request.endpoint in public_endpoints:
        return
    if session.get("user_id"):
        return
    return redirect(url_for("login", next=request.path))


@app.after_request
def _log_request_timing(response):
    started_at = getattr(g, "request_started_at", None)
    if started_at is not None:
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        app.logger.info(
            "%s %s -> %s em %.1fms",
            request.method,
            request.path,
            response.status_code,
            elapsed_ms,
        )
    return response


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Tela de login."""
    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        user = auth_service.autenticar_usuario(username, password)
        if user:
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            next_url = request.args.get("next")
            if not next_url or not next_url.startswith("/"):
                next_url = url_for("dashboard")
            return redirect(next_url)
        flash('Usuário ou senha inválidos.', 'warning')

    return render_template('login.html')


@app.route('/logout')
def logout():
    """Encerra a sessão do usuário."""
    session.clear()
    flash('Sessão encerrada com sucesso.', 'info')
    return redirect(url_for('login'))


@app.route('/')
def index():
    """Redireciona para dashboard"""
    return redirect(url_for('dashboard'))


@app.route('/dashboard')
def dashboard():
    """Página principal do dashboard focada no cartão."""
    cfg = cartao_service.get_config()
    mes_aberto, ano_aberto = cartao_service.mes_ano_fatura_em_aberto()
    mes_ref, ano_ref = _normalizar_competencia(
        request.args.get('mes'),
        request.args.get('ano'),
        mes_aberto,
        ano_aberto,
    )
    fatura_info = cartao_service.calcular_fatura_competencia(mes_ref, ano_ref)
    gastos_categoria = cartao_service.listar_gastos_por_categoria_competencia(mes_ref, ano_ref)
    limite_total = _to_float(cfg.limite_total)
    total_fatura = _to_float(fatura_info.get("total_geral"))
    limite_disponivel = limite_total - total_fatura
    percentual_utilizado = (total_fatura / limite_total * 100.0) if limite_total > 0 else 0.0
    competencias = _listar_competencias(mes_aberto, ano_aberto)
    anos_competencia = sorted({c["ano"] for c in competencias})

    return render_template('dashboard.html',
        fatura_info=fatura_info,
        limite_total=limite_total,
        limite_disponivel=limite_disponivel,
        percentual_utilizado=percentual_utilizado,
        competencias=competencias,
        anos_competencia=anos_competencia,
        mes_ref=mes_ref,
        ano_ref=ano_ref,
        gastos_categoria=gastos_categoria,
    )


@app.route('/receitas', methods=['GET', 'POST'])
def receitas():
    flash('A tela de receitas foi removida deste fluxo.', 'info')
    return redirect(url_for('dashboard'))


@app.route('/cartao', methods=['GET', 'POST'])
def cartao():
    """Página do cartão de crédito"""
    cfg = cartao_service.get_config()
    mes_fatura_aberta, ano_fatura_aberta = cartao_service.mes_ano_fatura_em_aberto()
    mes_comp_padrao, ano_comp_padrao = mes_fatura_aberta, ano_fatura_aberta
    sort_by = (request.args.get('sort_by') or '').strip().lower()
    sort_dir = (request.args.get('sort_dir') or 'asc').strip().lower()
    if sort_dir not in {'asc', 'desc'}:
        sort_dir = 'asc'
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'config':
            limite = _parse_brl_value(request.form.get('limite'), 0.0) or None
            dia_fech = int(request.form.get('dia_fechamento'))
            dia_venc = int(request.form.get('dia_vencimento'))
            cartao_service.atualizar_config(limite, dia_fech, dia_venc)
            flash('Configuração atualizada.', 'success')
            return redirect(url_for('cartao'))
        
        elif action == 'marcar_paga':
            cartao_service.marcar_fatura_como_paga()
            flash('Fatura marcada como paga e parcelas avançadas.', 'success')
            return redirect(url_for('cartao'))
        
        elif action == 'reabrir':
            cartao_service.reabrir_fatura_atual()
            flash('Fatura marcada como pendente novamente.', 'info')
            return redirect(url_for('cartao'))
        
        elif action == 'nova_categoria':
            nome = (request.form.get('nome') or '').strip()
            if not nome:
                flash('Informe o nome da categoria.', 'warning')
            elif cartao_service.criar_categoria(nome):
                flash('Categoria criada com sucesso.', 'success')
            else:
                flash('Não foi possível criar. Verifique se o nome já existe.', 'warning')
            return redirect(url_for('cartao', aba='categorias'))

        elif action == 'editar_categoria':
            categoria_id = int(request.form.get('categoria_id', 0))
            nome = (request.form.get('nome') or '').strip()
            if categoria_id <= 0 or not nome:
                flash('Dados inválidos para edição da categoria.', 'warning')
            else:
                resultado = cartao_service.atualizar_categoria(categoria_id, nome)
                if resultado.get("ok"):
                    qtd = int(resultado.get("lancamentos") or 0)
                    nome_cat = resultado.get("nome") or nome
                    if resultado.get("mesclada"):
                        flash(
                            f'Categoria unida em "{nome_cat}". '
                            f'{qtd} lançamento(s) antigo(s) e novo(s) aparecem com esse nome no cartão e no dashboard.',
                            'success',
                        )
                    else:
                        flash(
                            f'Categoria renomeada para "{nome_cat}". '
                            f'{qtd} lançamento(s) vinculado(s) já exibem o nome novo.',
                            'success',
                        )
                else:
                    flash('Não foi possível atualizar a categoria.', 'warning')
            return redirect(url_for('cartao', aba='categorias'))

        elif action == 'excluir_categoria':
            categoria_id = int(request.form.get('categoria_id', 0))
            if categoria_id <= 0:
                flash('Categoria inválida.', 'warning')
            elif cartao_service.excluir_categoria(categoria_id):
                flash('Categoria excluída. Lançamentos ficaram sem categoria.', 'success')
            else:
                flash('Não foi possível excluir a categoria.', 'warning')
            return redirect(url_for('cartao', aba='categorias'))

        elif action == 'compra':
            descricao = request.form.get('descricao')
            valor_compra = _parse_brl_value(request.form.get('valor'), 0.0)
            pessoa_id_str = request.form.get('pessoa_id', '')
            pessoa_id = int(pessoa_id_str) if pessoa_id_str else None
            categoria_id = _parse_categoria_id(request.form.get('categoria_id'))
            avista = request.form.get('tipo') == 'avista'
            total_parcelas = int(request.form.get('total_parcelas', 1))
            parcela_atual = int(request.form.get('parcela_atual', 1))
            modo_valor = request.form.get('modo_valor', 'total')
            mes_competencia, ano_competencia = _normalizar_competencia(
                request.form.get('mes_competencia'),
                request.form.get('ano_competencia'),
                mes_comp_padrao,
                ano_comp_padrao,
            )
            
            if not descricao or valor_compra <= 0:
                flash('Informe descrição e valor maior que zero.', 'warning')
                return redirect(url_for('cartao'))
            if categoria_id is not None and not cartao_service.categoria_existe(categoria_id):
                flash('Categoria inválida.', 'warning')
                return redirect(url_for('cartao'))
            if not avista:
                if total_parcelas < 1:
                    flash('Número de parcelas deve ser maior que zero.', 'warning')
                    return redirect(url_for('cartao'))
                if parcela_atual < 1 or parcela_atual > total_parcelas:
                    flash('Parcela atual deve estar entre 1 e o total de parcelas.', 'warning')
                    return redirect(url_for('cartao'))
            
            if avista:
                cartao_service.registrar_compra_avista(
                    descricao,
                    valor_compra,
                    pessoa_id,
                    mes_competencia,
                    ano_competencia,
                    categoria_id,
                )
            else:
                valor_total = valor_compra * total_parcelas if modo_valor == 'parcela' else valor_compra
                cartao_service.criar_parcelada(
                    descricao, valor_total, total_parcelas,
                    mes_competencia, ano_competencia, pessoa_id, parcela_atual,
                    categoria_id,
                )
            flash('Compra registrada com sucesso.', 'success')
            return redirect(url_for('cartao'))

        elif action == 'excluir_lancamento':
            tipo = (request.form.get('tipo') or '').strip().lower()
            lancamento_id = int(request.form.get('lancamento_id', 0))
            if lancamento_id <= 0:
                flash('Lançamento inválido.', 'warning')
                return _redirect_cartao('lancamentos')
            if tipo == 'avista':
                ok = cartao_service.excluir_avista(lancamento_id)
            elif tipo == 'parcelado':
                ok = cartao_service.excluir_parcelada(lancamento_id)
            else:
                ok = False
            if ok:
                flash('Lançamento excluído com sucesso.', 'success')
            else:
                flash('Não foi possível excluir o lançamento.', 'warning')
            return _redirect_cartao('lancamentos')

        elif action == 'editar_lancamento':
            tipo = (request.form.get('tipo') or '').strip().lower()
            lancamento_id = int(request.form.get('lancamento_id', 0))
            descricao = (request.form.get('descricao') or '').strip()
            valor = _parse_brl_value(request.form.get('valor'), 0.0)
            pessoa_id_str = request.form.get('pessoa_id', '')
            pessoa_id = int(pessoa_id_str) if pessoa_id_str else None
            categoria_id = _parse_categoria_id(request.form.get('categoria_id'))
            mes_competencia, ano_competencia = _normalizar_competencia(
                request.form.get('mes_competencia'),
                request.form.get('ano_competencia'),
                mes_comp_padrao,
                ano_comp_padrao,
            )

            if lancamento_id <= 0 or not descricao or valor <= 0:
                flash('Dados inválidos para edição.', 'warning')
                return _redirect_cartao('lancamentos')
            if categoria_id is not None and not cartao_service.categoria_existe(categoria_id):
                flash('Categoria inválida.', 'warning')
                return _redirect_cartao('lancamentos')

            if tipo == 'avista':
                ok = cartao_service.atualizar_avista(
                    lancamento_id,
                    descricao,
                    valor,
                    pessoa_id,
                    mes_competencia,
                    ano_competencia,
                    categoria_id,
                )
            elif tipo == 'parcelado':
                total_parcelas = int(request.form.get('total_parcelas', 1))
                parcela_atual = int(request.form.get('parcela_atual', 1))
                status_raw = request.form.get('status')
                status = status_raw.strip().capitalize() if status_raw else None
                if total_parcelas < 1:
                    flash('O total de parcelas deve ser maior que zero.', 'warning')
                    return _redirect_cartao('lancamentos')
                parcela_atual = max(1, min(parcela_atual, total_parcelas))
                if status is not None and status not in {'Ativa', 'Finalizada'}:
                    flash('Status inválido.', 'warning')
                    return _redirect_cartao('lancamentos')
                ok = cartao_service.atualizar_parcelada(
                    lancamento_id,
                    descricao,
                    valor,
                    parcela_atual,
                    total_parcelas,
                    status,
                    pessoa_id,
                    mes_competencia,
                    ano_competencia,
                    categoria_id,
                )
            else:
                ok = False

            if ok:
                if categoria_id is not None:
                    nomes_cat = {
                        c.id: c.nome for c in cartao_service.listar_categorias()
                    }
                    nome_cat = nomes_cat.get(categoria_id, '')
                    flash(
                        f'Lançamento atualizado. Categoria salva: {nome_cat or categoria_id}.',
                        'success',
                    )
                else:
                    flash(
                        'Lançamento atualizado. Categoria removida (sem categoria).',
                        'success',
                    )
            else:
                flash('Não foi possível atualizar o lançamento.', 'warning')
            return _redirect_cartao('lancamentos')
    
    mes_fatura_exibicao, ano_fatura_exibicao = _normalizar_competencia(
        request.args.get('mes_fatura'),
        request.args.get('ano_fatura'),
        mes_fatura_aberta,
        ano_fatura_aberta,
    )
    mes_lancamento_exibicao, ano_lancamento_exibicao = _normalizar_competencia(
        request.args.get('mes_lancamento'),
        request.args.get('ano_lancamento'),
        mes_fatura_exibicao,
        ano_fatura_exibicao,
    )
    info = cartao_service.calcular_fatura_competencia(mes_fatura_exibicao, ano_fatura_exibicao)
    pessoas = pessoas_service.listar_pessoas()
    categorias = cartao_service.listar_categorias()
    aba_ativa = (request.args.get('aba') or 'principal').strip().lower()
    if aba_ativa not in {'principal', 'categorias', 'lancamentos'}:
        aba_ativa = 'principal'
    lancamentos_todos = cartao_service.listar_todos_lancamentos()
    competencias = _listar_competencias(mes_comp_padrao, ano_comp_padrao)
    anos_competencia = sorted(
        {c["ano"] for c in competencias}.union({int(l["ano_ref"]) for l in lancamentos_todos})
    )
    mes_fatura_anterior, ano_fatura_anterior = _deslocar_competencia(mes_fatura_exibicao, ano_fatura_exibicao, -1)
    mes_fatura_proxima, ano_fatura_proxima = _deslocar_competencia(mes_fatura_exibicao, ano_fatura_exibicao, 1)
    exibindo_fatura_aberta = (mes_fatura_exibicao, ano_fatura_exibicao) == (mes_fatura_aberta, ano_fatura_aberta)
    pessoa_nome_por_id = {p.id: p.nome for p in pessoas}
    for l in lancamentos_todos:
        l["pessoa_nome"] = pessoa_nome_por_id.get(l.get("pessoa_id")) or "Nosso"
        mes_ref = int(l["mes_ref"])
        ano_ref = int(l["ano_ref"])
        l["periodo"] = f'{mes_ref:02d}/{ano_ref} - {_MESES_NOMES[mes_ref]}'
        if l["tipo"] == "parcelado":
            total_p = int(l["total_parcelas"])
            parcela_exibicao = int(l.get("parcela_exibicao") or 1)
            parcela_exibicao = max(1, min(parcela_exibicao, total_p))
            l["parcela_exibicao"] = parcela_exibicao
            l["parcelas_label"] = f"{parcela_exibicao}/{total_p}"
        else:
            l["parcelas_label"] = "-"
    for idx, l in enumerate(lancamentos_todos):
        l["ui_key"] = f"{l['tipo']}-{int(l['id'])}-{idx}"
    grupos_por_chave = {}
    competencia_minima_lancamentos = (2026, 3)
    for l in lancamentos_todos:
        chave = (int(l["ano_ref"]), int(l["mes_ref"]))
        if chave < competencia_minima_lancamentos:
            continue
        grupo = grupos_por_chave.get(chave)
        if grupo is None:
            ano_ref, mes_ref = chave
            grupo = {
                "chave": chave,
                "titulo": f'{mes_ref:02d}/{ano_ref} - {_MESES_NOMES[mes_ref]}',
                "lancamentos": [],
            }
            grupos_por_chave[chave] = grupo
        grupo["lancamentos"].append(l)

    if sort_by == 'pessoa':
        for grupo in grupos_por_chave.values():
            grupo["lancamentos"] = sorted(
                grupo["lancamentos"],
                key=lambda l: (
                    (l.get("pessoa_nome") or "").strip().lower(),
                    (l.get("descricao") or "").strip().lower(),
                    str(l.get("tipo") or ""),
                    int(l.get("id") or 0),
                ),
                reverse=(sort_dir == 'desc'),
            )

    lancamentos_por_competencia = [
        grupos_por_chave[chave]
        for chave in sorted(grupos_por_chave.keys(), key=lambda x: (x[0], x[1]), reverse=True)
    ]
    chaves_lancamentos = [grupo["chave"] for grupo in lancamentos_por_competencia]
    if (ano_lancamento_exibicao, mes_lancamento_exibicao) not in chaves_lancamentos and chaves_lancamentos:
        ano_lancamento_exibicao, mes_lancamento_exibicao = chaves_lancamentos[0]

    grupo_lancamentos_ativo = None
    idx_lancamentos_ativo = -1
    for idx, grupo in enumerate(lancamentos_por_competencia):
        if grupo["chave"] == (ano_lancamento_exibicao, mes_lancamento_exibicao):
            grupo_lancamentos_ativo = grupo
            idx_lancamentos_ativo = idx
            break
    competencia_lanc_anterior = (
        lancamentos_por_competencia[idx_lancamentos_ativo - 1]
        if idx_lancamentos_ativo > 0
        else None
    )
    competencia_lanc_proxima = (
        lancamentos_por_competencia[idx_lancamentos_ativo + 1]
        if idx_lancamentos_ativo >= 0 and idx_lancamentos_ativo + 1 < len(lancamentos_por_competencia)
        else None
    )
    
    return render_template(
        'cartao.html',
        cfg=cfg,
        info=info,
        pessoas=pessoas,
        competencias=competencias,
        anos_competencia=anos_competencia,
        mes_comp_padrao=mes_comp_padrao,
        ano_comp_padrao=ano_comp_padrao,
        lancamentos_todos=lancamentos_todos,
        lancamentos_por_competencia=lancamentos_por_competencia,
        grupo_lancamentos_ativo=grupo_lancamentos_ativo,
        competencia_lanc_anterior=competencia_lanc_anterior,
        competencia_lanc_proxima=competencia_lanc_proxima,
        mes_fatura_aberta=mes_fatura_aberta,
        ano_fatura_aberta=ano_fatura_aberta,
        mes_fatura_exibicao=mes_fatura_exibicao,
        ano_fatura_exibicao=ano_fatura_exibicao,
        mes_lancamento_exibicao=mes_lancamento_exibicao,
        ano_lancamento_exibicao=ano_lancamento_exibicao,
        mes_fatura_anterior=mes_fatura_anterior,
        ano_fatura_anterior=ano_fatura_anterior,
        mes_fatura_proxima=mes_fatura_proxima,
        ano_fatura_proxima=ano_fatura_proxima,
        exibindo_fatura_aberta=exibindo_fatura_aberta,
        sort_by=sort_by,
        sort_dir=sort_dir,
        categorias=categorias,
        aba_ativa=aba_ativa,
    )


@app.route('/gastos-pix', methods=['GET', 'POST'])
def gastos_pix():
    flash('A tela de gastos Pix foi removida deste fluxo.', 'info')
    return redirect(url_for('dashboard'))


@app.route('/contas-fixas', methods=['GET', 'POST'])
def contas_fixas():
    """Página de contas fixas"""
    mes = request.args.get('mes', type=int, default=_mes_ano_atual()[0])
    ano = request.args.get('ano', type=int, default=_mes_ano_atual()[1])
    sort_by = (request.args.get('sort_by') or '').strip().lower()
    sort_dir = (request.args.get('sort_dir') or 'asc').strip().lower()
    if sort_dir not in {'asc', 'desc'}:
        sort_dir = 'asc'
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'nova_conta':
            nome = request.form.get('nome')
            categoria = (request.form.get('categoria') or '').strip() or None
            valor_str = request.form.get('valor')
            valor = _parse_brl_value(valor_str, None) if valor_str else None
            mes_comp = request.form.get('mes_competencia', type=int, default=mes)
            ano_comp = request.form.get('ano_competencia', type=int, default=ano)
            desconto_pessoa_nome = (request.form.get('desconto_pessoa_nome') or '').strip() or None
            vencimento_data = (request.form.get('vencimento_data') or '').strip() or None
            data_fim_str = (request.form.get('data_fim') or '').strip() or None
            
            if not nome:
                flash('Informe o nome da conta.', 'warning')
            else:
                contas_service.criar_conta_fixa(
                    nome,
                    categoria,
                    valor,
                    desconto_pessoa_nome,
                    None,
                    None,
                    vencimento_data,
                    None,
                    mes_comp,
                    ano_comp,
                    data_fim_str,
                )
                flash('Conta fixa cadastrada.', 'success')
            return redirect(url_for('contas_fixas', mes=mes_comp, ano=ano_comp))


        elif action == 'editar_conta':
            conta_id = int(request.form.get('conta_id', 0))
            nome = (request.form.get('nome') or '').strip()
            categoria = (request.form.get('categoria') or '').strip() or None
            valor_str = (request.form.get('valor') or '').strip()
            valor = _parse_brl_value(valor_str, None) if valor_str else None
            desconto_pessoa_nome = (request.form.get('desconto_pessoa_nome') or '').strip() or None
            vencimento_data = (request.form.get('vencimento_data') or '').strip() or None
            data_fim = (request.form.get('data_fim') or '').strip() or None
            mes_comp = request.form.get('mes_competencia', type=int, default=mes)
            ano_comp = request.form.get('ano_competencia', type=int, default=ano)

            if conta_id <= 0 or not nome:
                flash('Dados inválidos para editar conta.', 'warning')
            else:
                ok = contas_service.atualizar_conta_fixa(
                    conta_id,
                    nome,
                    categoria,
                    valor,
                    desconto_pessoa_nome,
                    None,
                    None,
                    vencimento_data,
                    data_fim,
                    mes_comp,
                    ano_comp,
                )
                if ok:
                    flash('Conta atualizada com sucesso.', 'success')
                else:
                    flash('Conta não encontrada.', 'warning')
            return redirect(url_for('contas_fixas', mes=mes_comp, ano=ano_comp))

        elif action == 'excluir_conta':
            conta_id = int(request.form.get('conta_id', 0))
            if conta_id > 0 and contas_service.excluir_conta_fixa(conta_id):
                flash('Conta excluída com sucesso.', 'success')
            else:
                flash('Não foi possível excluir a conta.', 'warning')
            return redirect(url_for('contas_fixas', mes=mes, ano=ano))
        
        elif action == 'marcar_pago':
            conta_id = int(request.form.get('conta_id', 0))
            foi_atualizada = contas_service.marcar_conta_como_paga(conta_id)
            if foi_atualizada:
                flash('Conta marcada como paga com sucesso.', 'success')
            else:
                flash('Conta não encontrada ou já estava marcada como paga.', 'info')
            return redirect(url_for('contas_fixas', mes=mes, ano=ano))
    
    conn = get_connection()
    try:
        # Gera automaticamente do mês atual usando a mesma conexão do carregamento da tela.
        contas_service.gerar_contas_fixas_mes_atual(conn=conn)
        contas_service.garantir_contas_casa_competencia(mes, ano, conn=conn)
        contas = contas_service.listar_contas_fixas(mes, ano, conn=conn)
        totais = contas_service.calcular_totais_contas_fixas(mes, ano, contas=contas)
        pessoas_todas = pessoas_service.listar_pessoas(only_ativas=False, conn=conn)
    finally:
        conn.close()
    if sort_by == 'pessoa':
        contas = sorted(
            contas,
            key=lambda c: (
                (c.desconto_pessoa_nome or '').strip().lower(),
                (c.nome or '').strip().lower(),
                int(c.id),
            ),
            reverse=(sort_dir == 'desc'),
        )
    nomes_pessoas = sorted(
        {p.nome.strip() for p in pessoas_todas if p.nome and p.nome.strip()},
        key=lambda x: x.lower(),
    )
    
    return render_template('contas_fixas.html', 
        mes=mes, ano=ano, contas=contas, totais=totais, nomes_pessoas=nomes_pessoas,
        sort_by=sort_by, sort_dir=sort_dir)


@app.route('/pessoas', methods=['GET', 'POST'])
def pessoas():
    """Página de pessoas (terceiros)"""
    mes_atual, ano_atual = _mes_ano_atual()
    mes_raw = request.args.get('mes')
    ano_raw = request.args.get('ano')
    mes = int(mes_raw) if mes_raw and str(mes_raw).isdigit() else mes_atual
    ano = int(ano_raw) if ano_raw and str(ano_raw).isdigit() else ano_atual
    competencia_informada = (mes_raw is not None) or (ano_raw is not None)
    mes_cartao_alt = None
    ano_cartao_alt = None
    if (mes, ano) == (mes_atual, ano_atual):
        try:
            mes_cartao, ano_cartao = cartao_service.mes_ano_fatura_atual()
            if (mes_cartao, ano_cartao) != (mes, ano):
                mes_cartao_alt = mes_cartao
                ano_cartao_alt = ano_cartao
        except Exception:
            mes_cartao_alt = None
            ano_cartao_alt = None

    # Se o usuário não escolheu mês/ano manualmente, usa a competência real de pagamento.
    if not competencia_informada and mes_cartao_alt is not None and ano_cartao_alt is not None:
        mes = mes_cartao_alt
        ano = ano_cartao_alt
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'nova_pessoa':
            nome = request.form.get('nome')
            if nome:
                pessoas_service.criar_pessoa(nome)
                flash('Pessoa criada com sucesso.', 'success')
            return redirect(url_for('pessoas', mes=mes, ano=ano))
        
        elif action == 'excluir_pessoa':
            pessoa_id = int(request.form.get('pessoa_id'))
            pessoa = pessoas_service.get_pessoa_by_id(pessoa_id)
            if not pessoa:
                flash('Pessoa não encontrada.', 'warning')
            else:
                try:
                    pessoas_service.excluir_pessoa(pessoa_id)
                    flash('Pessoa excluída com sucesso.', 'success')
                except Exception:
                    flash('Não foi possível excluir. A pessoa pode ter registros vinculados.', 'warning')
            return redirect(url_for('pessoas', mes=mes, ano=ano))

        
        elif action == 'editar_pessoa':
            pessoa_id = int(request.form.get('pessoa_id'))
            novo_nome = (request.form.get('novo_nome') or '').strip()
            novo_ativo = request.form.get('novo_ativo') == 'on'

            pessoa = pessoas_service.get_pessoa_by_id(pessoa_id)
            if not pessoa:
                flash('Pessoa nao encontrada.', 'warning')
            elif not novo_nome:
                flash('O nome da pessoa nao pode ser vazio.', 'warning')
            else:
                try:
                    pessoas_service.atualizar_pessoa(pessoa_id, novo_nome, novo_ativo)
                    flash('Pessoa atualizada com sucesso.', 'success')
                except Exception:
                    flash('Nao foi possivel atualizar. Verifique se o nome ja existe.', 'warning')
            return redirect(url_for('pessoas', mes=mes, ano=ano))

        elif action == 'toggle_padrao':
            pessoa_id = int(request.form.get('pessoa_id'))
            pessoa = pessoas_service.get_pessoa_by_id(pessoa_id)
            if not pessoa:
                flash('Pessoa não encontrada.', 'warning')
            else:
                pessoas_service.atualizar_padrao_pessoa(pessoa_id, not pessoa.padrao)
                flash('Padrão atualizado.', 'success')
            return redirect(url_for('pessoas', mes=mes, ano=ano))

        elif action == 'registrar_pagamento_itens':
            pessoa_id = int(request.form.get('pessoa_id'))
            itens_tokens = request.form.getlist('conta_paga')
            mes_ref = request.form.get('mes_ref', type=int, default=mes)
            ano_ref = request.form.get('ano_ref', type=int, default=ano)

            total = pessoas_service.registrar_pagamento_terceiro_por_itens(
                pessoa_id, itens_tokens, mes_ref, ano_ref, mes_cartao_alt, ano_cartao_alt
            )
            if total > 0:
                flash(f'Pagamento registrado: R$ {total:,.2f}.', 'success')
            else:
                flash('Selecione ao menos uma conta pendente.', 'warning')
            return redirect(url_for('pessoas', mes=mes, ano=ano))

        elif action == 'registrar_pagamento_item':
            pessoa_id = int(request.form.get('pessoa_id', 0))
            conta_token = (request.form.get('conta_token') or '').strip()
            mes_ref = request.form.get('mes_ref', type=int, default=mes)
            ano_ref = request.form.get('ano_ref', type=int, default=ano)
            if pessoa_id <= 0 or not conta_token:
                flash('Dados inválidos para pagamento.', 'warning')
                return redirect(url_for('pessoas', mes=mes, ano=ano))
            total = pessoas_service.registrar_pagamento_terceiro_por_itens(
                pessoa_id, [conta_token], mes_ref, ano_ref, mes_cartao_alt, ano_cartao_alt
            )
            if total > 0:
                flash(f'Pagamento registrado: R$ {total:,.2f}.', 'success')
            else:
                flash('Esta conta já está paga ou não foi encontrada.', 'warning')
            return redirect(url_for('pessoas', mes=mes, ano=ano))

        elif action == 'registrar_pagamento_todos':
            pessoa_id = int(request.form.get('pessoa_id', 0))
            mes_ref = request.form.get('mes_ref', type=int, default=mes)
            ano_ref = request.form.get('ano_ref', type=int, default=ano)
            if pessoa_id <= 0:
                flash('Pessoa inválida para pagamento.', 'warning')
                return redirect(url_for('pessoas', mes=mes, ano=ano))
            contas = pessoas_service.listar_contas_status_pessoa(
                pessoa_id, mes_ref, ano_ref, mes_cartao_alt, ano_cartao_alt
            )
            itens_tokens = [str(c["token"]) for c in contas if not bool(c.get("pago"))]
            total = pessoas_service.registrar_pagamento_terceiro_por_itens(
                pessoa_id, itens_tokens, mes_ref, ano_ref, mes_cartao_alt, ano_cartao_alt
            )
            if total > 0:
                flash(f'Todas as contas pendentes foram marcadas como pagas: R$ {total:,.2f}.', 'success')
            else:
                flash('Não há contas pendentes para essa pessoa.', 'info')
            return redirect(url_for('pessoas', mes=mes, ano=ano))

        elif action == 'adicionar_desconto':
            pessoa_id = int(request.form.get('pessoa_id', 0))
            mes_ref = request.form.get('mes_ref', type=int, default=mes)
            ano_ref = request.form.get('ano_ref', type=int, default=ano)
            pessoa = pessoas_service.get_pessoa_by_id(pessoa_id)
            if not pessoa:
                flash('Pessoa não encontrada.', 'warning')
                return redirect(url_for('pessoas', mes=mes, ano=ano))

            descricao_desconto = (request.form.get('descricao_desconto') or '').strip()
            valor_desconto = _parse_brl_value(request.form.get('valor_desconto'), 0.0)
            if not descricao_desconto:
                flash('Informe a descrição do desconto.', 'warning')
            elif valor_desconto <= 0:
                flash('Informe um valor de desconto maior que zero.', 'warning')
            else:
                pessoas_service.adicionar_desconto_manual_pessoa(
                    pessoa_id, descricao_desconto, float(valor_desconto), mes_ref, ano_ref
                )
                flash('Desconto adicionado com sucesso.', 'success')
            return redirect(url_for('pessoas', mes=mes, ano=ano))

        elif action == 'excluir_desconto':
            pessoa_id = int(request.form.get('pessoa_id', 0))
            desconto_id = int(request.form.get('desconto_id', 0))
            if desconto_id > 0 and pessoa_id > 0 and pessoas_service.excluir_desconto_manual_pessoa(desconto_id, pessoa_id):
                flash('Desconto removido com sucesso.', 'success')
            else:
                flash('Não foi possível remover o desconto.', 'warning')
            return redirect(url_for('pessoas', mes=mes, ano=ano))

        elif action == 'editar_desconto':
            pessoa_id = int(request.form.get('pessoa_id', 0))
            desconto_id = int(request.form.get('desconto_id', 0))
            descricao_desconto = (request.form.get('descricao_desconto') or '').strip()
            valor_desconto = _parse_brl_value(request.form.get('valor_desconto'), 0.0)
            if pessoa_id <= 0 or desconto_id <= 0 or not descricao_desconto:
                flash('Dados inválidos para editar desconto.', 'warning')
            elif valor_desconto <= 0:
                flash('Informe um valor maior que zero.', 'warning')
            else:
                ok = pessoas_service.atualizar_desconto_manual_pessoa(
                    desconto_id, pessoa_id, descricao_desconto, float(valor_desconto)
                )
                if ok:
                    flash('Desconto atualizado com sucesso.', 'success')
                else:
                    flash('Desconto não encontrado.', 'warning')
            return redirect(url_for('pessoas', mes=mes, ano=ano))
    
    prioridades_nome = {"aila": 1, "raynne": 2}

    def _ordem_pessoa(p):
        nome_norm = (p.nome or "").strip().lower()
        if p.padrao:
            return (0, 0, int(p.id))
        if nome_norm in prioridades_nome:
            return (1, prioridades_nome[nome_norm], int(p.id))
        return (2, 0, int(p.id))

    conn = get_connection()
    try:
        pessoas_list = sorted(
            pessoas_service.listar_pessoas(only_ativas=False, conn=conn),
            key=_ordem_pessoa,
        )
        totais_por_pessoa = pessoas_service.calcular_totais_por_pessoa(
            mes, ano, mes_cartao_alt, ano_cartao_alt, conn=conn
        )
        resumos = []
        for p in pessoas_list:
            if p.padrao:
                total_mes = 0.0
                total_pago = 0.0
                saldo_pend = 0.0
            else:
                info = totais_por_pessoa.get(p.id, {"total_mes": 0.0, "total_pago": 0.0, "saldo_pendente": 0.0})
                total_mes = float(info["total_mes"])
                total_pago = float(info["total_pago"])
                saldo_pend = float(info["saldo_pendente"])

            resumos.append({
                'pessoa': p,
                'total_mes': total_mes,
                'total_pago': total_pago,
                'saldo_pend': saldo_pend
            })

        ids_padrao = {p.id for p in pessoas_list if p.padrao}
        total_mes_geral = sum(
            float(info.get("total_mes", 0.0))
            for pid, info in totais_por_pessoa.items()
            if pid not in ids_padrao
        )
        total_pago_geral = sum(
            float(info.get("total_pago", 0.0))
            for pid, info in totais_por_pessoa.items()
            if pid not in ids_padrao
        )
        saldo_pend_geral = total_mes_geral - total_pago_geral

        pessoas_ativas = [p for p in pessoas_list if p.ativo and not p.padrao]
        ids_pessoas_ativas = {p.id for p in pessoas_ativas}
        pessoa_ativa_id = request.args.get('pessoa_id', type=int)
        if pessoa_ativa_id not in ids_pessoas_ativas:
            pessoa_ativa_id = None
        contas_status_por_pessoa_mes = {}
        descontos_itens_por_pessoa_mes = {}
        previsao_mes_por_pessoa = {}
        if pessoa_ativa_id:
            detalhe = pessoas_service.carregar_detalhe_pessoa_pagina(
                pessoa_ativa_id,
                mes,
                ano,
                mes_cartao_alt,
                ano_cartao_alt,
                conn=conn,
            )
            previsao_mes_por_pessoa[pessoa_ativa_id] = detalhe["previsao"]
            contas_status_por_pessoa_mes[pessoa_ativa_id] = detalhe["contas_status_por_mes"]
            descontos_itens_por_pessoa_mes[pessoa_ativa_id] = detalhe["descontos_itens_por_mes"]
    finally:
        conn.close()

    return render_template('pessoas.html',
        mes=mes, ano=ano,
        pessoa_ativa_id=pessoa_ativa_id,
        pessoas=pessoas_list,
        pessoas_ativas=pessoas_ativas,
        resumos=resumos,
        descontos_itens_por_pessoa_mes=descontos_itens_por_pessoa_mes,
        previsao_mes_por_pessoa=previsao_mes_por_pessoa,
        contas_status_por_pessoa_mes=contas_status_por_pessoa_mes,
        total_mes_geral=total_mes_geral,
        total_pago_geral=total_pago_geral,
        saldo_pend_geral=saldo_pend_geral
    )

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
