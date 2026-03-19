"""AplicaÃ§Ã£o Flask principal para Fechou MÃªs - Controle Financeiro"""
from flask import Flask, render_template, request, redirect, url_for, flash, session
from datetime import datetime
from decimal import Decimal
import sys
import os
from pathlib import Path

# Adiciona o diretÃ³rio raiz ao path
sys.path.insert(0, str(Path(__file__).parent))

from finance_app.database import setup_database, get_connection
from finance_app.services import (
    receita_service,
    cartao_service,
    contas_service,
    pessoas_service,
    auth_service,
)

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me")

# Inicializa banco de dados
setup_database()


def _mes_ano_atual():
    """Retorna mÃªs e ano atuais"""
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
    if request.path == "/favicon.ico":
        return "", 204
    public_endpoints = {"login", "static"}
    if request.endpoint is None or request.endpoint in public_endpoints:
        return
    if session.get("user_id"):
        return
    return redirect(url_for("login", next=request.path))


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
    """PÃ¡gina principal do dashboard focada no cartÃ£o."""
    cfg = cartao_service.get_config()
    fatura_info = cartao_service.calcular_fatura_atual()
    limite_total = _to_float(cfg.limite_total)
    total_fatura = _to_float(fatura_info.get("total_geral"))
    limite_disponivel = limite_total - total_fatura
    percentual_utilizado = (total_fatura / limite_total * 100.0) if limite_total > 0 else 0.0

    return render_template('dashboard.html',
        fatura_info=fatura_info,
        limite_total=limite_total,
        limite_disponivel=limite_disponivel,
        percentual_utilizado=percentual_utilizado,
        dia_fechamento=cfg.dia_fechamento,
        dia_vencimento=cfg.dia_vencimento,
        fatura_paga=cfg.fatura_paga,
    )


@app.route('/receitas', methods=['GET', 'POST'])
def receitas():
    flash('A tela de receitas foi removida deste fluxo.', 'info')
    return redirect(url_for('dashboard'))


@app.route('/cartao', methods=['GET', 'POST'])
def cartao():
    """PÃ¡gina do cartÃ£o de crÃ©dito"""
    cfg = cartao_service.get_config()
    mes_comp_padrao, ano_comp_padrao = cartao_service.mes_ano_fatura_atual()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'config':
            limite = _parse_brl_value(request.form.get('limite'), 0.0) or None
            dia_fech = int(request.form.get('dia_fechamento'))
            dia_venc = int(request.form.get('dia_vencimento'))
            cartao_service.atualizar_config(limite, dia_fech, dia_venc)
            flash('ConfiguraÃ§Ã£o atualizada.', 'success')
            return redirect(url_for('cartao'))
        
        elif action == 'marcar_paga':
            cartao_service.marcar_fatura_como_paga()
            flash('Fatura marcada como paga e parcelas avanÃ§adas.', 'success')
            return redirect(url_for('cartao'))
        
        elif action == 'reabrir':
            cartao_service.reabrir_fatura_atual()
            flash('Fatura marcada como pendente novamente.', 'info')
            return redirect(url_for('cartao'))
        
        elif action == 'compra':
            descricao = request.form.get('descricao')
            valor_compra = _parse_brl_value(request.form.get('valor'), 0.0)
            pessoa_id_str = request.form.get('pessoa_id', '')
            pessoa_id = int(pessoa_id_str) if pessoa_id_str else None
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
                flash('Informe descriÃ§Ã£o e valor maior que zero.', 'warning')
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
                )
            else:
                valor_total = valor_compra * total_parcelas if modo_valor == 'parcela' else valor_compra
                cartao_service.criar_parcelada(
                    descricao, valor_total, total_parcelas,
                    mes_competencia, ano_competencia, pessoa_id, parcela_atual
                )
            flash('Compra registrada com sucesso.', 'success')
            return redirect(url_for('cartao'))

        elif action == 'excluir_lancamento':
            tipo = (request.form.get('tipo') or '').strip().lower()
            lancamento_id = int(request.form.get('lancamento_id', 0))
            if lancamento_id <= 0:
                flash('Lançamento inválido.', 'warning')
                return redirect(url_for('cartao'))
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
            return redirect(url_for('cartao'))

        elif action == 'editar_lancamento':
            tipo = (request.form.get('tipo') or '').strip().lower()
            lancamento_id = int(request.form.get('lancamento_id', 0))
            descricao = (request.form.get('descricao') or '').strip()
            valor = _parse_brl_value(request.form.get('valor'), 0.0)
            pessoa_id_str = request.form.get('pessoa_id', '')
            pessoa_id = int(pessoa_id_str) if pessoa_id_str else None
            mes_competencia, ano_competencia = _normalizar_competencia(
                request.form.get('mes_competencia'),
                request.form.get('ano_competencia'),
                mes_comp_padrao,
                ano_comp_padrao,
            )

            if lancamento_id <= 0 or not descricao or valor <= 0:
                flash('Dados inválidos para edição.', 'warning')
                return redirect(url_for('cartao'))

            if tipo == 'avista':
                ok = cartao_service.atualizar_avista(
                    lancamento_id,
                    descricao,
                    valor,
                    pessoa_id,
                    mes_competencia,
                    ano_competencia,
                )
            elif tipo == 'parcelado':
                total_parcelas = int(request.form.get('total_parcelas', 1))
                parcela_atual = int(request.form.get('parcela_atual', 1))
                status_raw = request.form.get('status')
                status = status_raw.strip().capitalize() if status_raw else None
                if total_parcelas < 1 or parcela_atual < 1 or parcela_atual > total_parcelas:
                    flash('Parcela atual deve estar entre 1 e o total de parcelas.', 'warning')
                    return redirect(url_for('cartao'))
                if status is not None and status not in {'Ativa', 'Finalizada'}:
                    flash('Status inválido.', 'warning')
                    return redirect(url_for('cartao'))
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
                )
            else:
                ok = False

            if ok:
                flash('Lançamento atualizado com sucesso.', 'success')
            else:
                flash('Não foi possível atualizar o lançamento.', 'warning')
            return redirect(url_for('cartao'))
    
    info = cartao_service.calcular_fatura_atual()
    pessoas = pessoas_service.listar_pessoas()
    lancamentos_todos = cartao_service.listar_todos_lancamentos()
    competencias = _listar_competencias(mes_comp_padrao, ano_comp_padrao)
    anos_competencia = sorted(
        {c["ano"] for c in competencias}.union({int(l["ano_ref"]) for l in lancamentos_todos})
    )
    pessoa_nome_por_id = {p.id: p.nome for p in pessoas}
    for l in lancamentos_todos:
        l["pessoa_nome"] = pessoa_nome_por_id.get(l.get("pessoa_id")) or "Nosso"
        mes_ref = int(l["mes_ref"])
        ano_ref = int(l["ano_ref"])
        l["periodo"] = f'{mes_ref:02d}/{ano_ref} - {_MESES_NOMES[mes_ref]}'
        if l["tipo"] == "parcelado":
            parcela_exibicao = int(l.get("parcela_exibicao", l["parcela_atual"]))
            l["parcelas_label"] = f'{parcela_exibicao}/{int(l["total_parcelas"])}'
        else:
            l["parcelas_label"] = "-"
    for idx, l in enumerate(lancamentos_todos):
        l["ui_key"] = f"{l['tipo']}-{int(l['id'])}-{idx}"
    grupos_por_chave = {}
    for l in lancamentos_todos:
        chave = (int(l["ano_ref"]), int(l["mes_ref"]))
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

    lancamentos_por_competencia = [
        grupos_por_chave[chave]
        for chave in sorted(grupos_por_chave.keys(), key=lambda x: (x[0], x[1]))
    ]
    
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
    )


@app.route('/gastos-pix', methods=['GET', 'POST'])
def gastos_pix():
    flash('A tela de gastos Pix foi removida deste fluxo.', 'info')
    return redirect(url_for('dashboard'))


@app.route('/contas-fixas', methods=['GET', 'POST'])
def contas_fixas():
    """PÃ¡gina de contas fixas"""
    mes = request.args.get('mes', type=int, default=_mes_ano_atual()[0])
    ano = request.args.get('ano', type=int, default=_mes_ano_atual()[1])
    
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
            desconto_origem = (request.form.get('desconto_origem') or '').strip() or None
            desconto_receita_extra_id_str = (request.form.get('desconto_receita_extra_id') or '').strip()
            desconto_receita_extra_id = int(desconto_receita_extra_id_str) if desconto_receita_extra_id_str else None
            vencimento_data = (request.form.get('vencimento_data') or '').strip() or None
            data_fim_str = (request.form.get('data_fim') or '').strip() or None
            
            if not nome:
                flash('Informe o nome da conta.', 'warning')
            elif desconto_origem and not desconto_pessoa_nome:
                flash('Selecione a pessoa para desconto.', 'warning')
            elif desconto_origem == 'beneficio' and not desconto_receita_extra_id:
                flash('Selecione o benefício para abatimento.', 'warning')
            else:
                contas_service.criar_conta_fixa(
                    nome,
                    categoria,
                    valor,
                    desconto_pessoa_nome,
                    desconto_origem,
                    desconto_receita_extra_id,
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
            desconto_origem = (request.form.get('desconto_origem') or '').strip() or None
            desconto_receita_extra_id_str = (request.form.get('desconto_receita_extra_id') or '').strip()
            desconto_receita_extra_id = int(desconto_receita_extra_id_str) if desconto_receita_extra_id_str else None
            vencimento_data = (request.form.get('vencimento_data') or '').strip() or None
            data_fim = (request.form.get('data_fim') or '').strip() or None
            mes_comp = request.form.get('mes_competencia', type=int, default=mes)
            ano_comp = request.form.get('ano_competencia', type=int, default=ano)

            if conta_id <= 0 or not nome:
                flash('Dados inválidos para editar conta.', 'warning')
            elif desconto_origem and not desconto_pessoa_nome:
                flash('Selecione a pessoa para desconto.', 'warning')
            elif desconto_origem == 'beneficio' and not desconto_receita_extra_id:
                flash('Selecione o benefício para abatimento.', 'warning')
            else:
                ok = contas_service.atualizar_conta_fixa(
                    conta_id,
                    nome,
                    categoria,
                    valor,
                    desconto_pessoa_nome,
                    desconto_origem,
                    desconto_receita_extra_id,
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
            conta = contas_service.obter_conta_fixa_por_id(conta_id)
            if not conta:
                flash('Conta não encontrada.', 'warning')
                return redirect(url_for('contas_fixas', mes=mes, ano=ano))

            foi_atualizada = contas_service.marcar_conta_como_paga(conta_id)
            if foi_atualizada:
                flash('Conta marcada como paga com sucesso.', 'success')
            else:
                flash('A conta já estava marcada como paga.', 'info')
            return redirect(url_for('contas_fixas', mes=mes, ano=ano))
    
    # Gera automaticamente do mÃªs atual
    contas_service.gerar_contas_fixas_mes_atual()
    contas = contas_service.listar_contas_fixas(mes, ano)
    totais = contas_service.calcular_totais_contas_fixas(mes, ano)
    saldos = receita_service.listar_saldos()
    beneficios = [e for e in receita_service.listar_receitas_extras() if e.categoria == 'beneficio']
    pessoas_todas = pessoas_service.listar_pessoas(only_ativas=False)
    nomes_pessoas = sorted({p.nome.strip() for p in pessoas_todas if p.nome and p.nome.strip()})
    for s in saldos:
        nome = s.nome.strip()
        if nome and nome not in nomes_pessoas:
            nomes_pessoas.append(nome)
    nomes_pessoas = sorted(set(nomes_pessoas), key=lambda x: x.lower())
    
    return render_template('contas_fixas.html', 
        mes=mes, ano=ano, contas=contas, totais=totais, saldos=saldos, beneficios=beneficios, nomes_pessoas=nomes_pessoas)


@app.route('/pessoas', methods=['GET', 'POST'])
def pessoas():
    """PÃ¡gina de pessoas (terceiros)"""
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
                flash('Pessoa nÃ£o encontrada.', 'warning')
            else:
                try:
                    pessoas_service.excluir_pessoa(pessoa_id)
                    flash('Pessoa excluÃ­da com sucesso.', 'success')
                except Exception:
                    flash('NÃ£o foi possÃ­vel excluir. A pessoa pode ter registros vinculados.', 'warning')
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
    
    pessoas_list = pessoas_service.listar_pessoas(only_ativas=False) # Listar todas as pessoas para gerenciamento
    saldos_por_nome = {
        s.nome.strip().lower(): s
        for s in receita_service.listar_saldos()
        if s.nome and s.nome.strip()
    }
    totais_por_pessoa = pessoas_service.calcular_totais_por_pessoa(
        mes, ano, mes_cartao_alt, ano_cartao_alt
    )
    resumos = []
    for p in pessoas_list:
        info = totais_por_pessoa.get(p.id, {"total_mes": 0.0, "total_pago": 0.0, "saldo_pendente": 0.0})
        total_mes = float(info["total_mes"])
        total_pago = float(info["total_pago"])
        saldo_pend = float(info["saldo_pendente"])

        # Para pessoas padrão, exibe o saldo real da conta (Receitas) no cadastro.
        if p.padrao:
            saldo_padrao = saldos_por_nome.get((p.nome or "").strip().lower())
            total_mes = float(saldo_padrao.saldo_atual) if saldo_padrao else 0.0
            total_pago = 0.0
            saldo_pend = 0.0

        resumos.append({
            'pessoa': p,
            'total_mes': total_mes,
            'total_pago': total_pago,
            'saldo_pend': saldo_pend
        })
    
    total_mes_geral = sum(float(info.get("total_mes", 0.0)) for info in totais_por_pessoa.values())
    total_pago_geral = sum(float(info.get("total_pago", 0.0)) for info in totais_por_pessoa.values())
    saldo_pend_geral = total_mes_geral - total_pago_geral

    pessoas_ativas = [p for p in pessoas_list if p.ativo and not p.padrao]
    ids_pessoas_ativas = {p.id for p in pessoas_ativas}
    pessoa_ativa_id = request.args.get('pessoa_id', type=int)
    if pessoa_ativa_id not in ids_pessoas_ativas:
        pessoa_ativa_id = None
    contas_status_por_pessoa_mes = {}
    descontos_itens_por_pessoa_mes = {}
    previsao_mes_por_pessoa = {}
    pessoas_para_detalhe = [p for p in pessoas_ativas if p.id == pessoa_ativa_id] if pessoa_ativa_id else []
    for p in pessoas_para_detalhe:
        conn_pessoa = get_connection()
        try:
            previsao = pessoas_service.listar_previsao_contas_por_mes_pessoa(
                p.id, mes, ano, mes_cartao_alt, ano_cartao_alt, conn=conn_pessoa
            )
            meses_previsao = list(previsao.get("meses", []))
            chaves_com_contas = set()
            idx_limite = (ano * 12) + (mes - 1) + 11
            for mref in meses_previsao:
                m_ref = int(mref["mes"])
                a_ref = int(mref["ano"])
                chaves_com_contas.add(f"{a_ref}-{m_ref:02d}")
                idx_limite = max(idx_limite, (a_ref * 12) + (m_ref - 1))

            mes_fim = (idx_limite % 12) + 1
            ano_fim = idx_limite // 12
            descontos_por_mes = pessoas_service.listar_descontos_manuais_pessoa_intervalo(
                p.id, mes, ano, mes_fim, ano_fim, conn=conn_pessoa
            )

            chaves_existentes = {f"{int(m['ano'])}-{int(m['mes']):02d}" for m in meses_previsao}
            for chave_mes in descontos_por_mes.keys():
                if chave_mes in chaves_existentes:
                    continue
                ano_chave, mes_chave = chave_mes.split("-")
                meses_previsao.append(
                    {
                        "mes": int(mes_chave),
                        "ano": int(ano_chave),
                        "total": 0.0,
                        "itens": [],
                    }
                )
                chaves_existentes.add(chave_mes)

            meses_previsao.sort(key=lambda x: (int(x["ano"]), int(x["mes"])))
            previsao["meses"] = meses_previsao
            total_contas_previsto = sum(float(m.get("total", 0.0)) for m in meses_previsao)
            total_descontos_previsto = 0.0
            for itens_desc in descontos_por_mes.values():
                total_descontos_previsto += sum(float(d.get("valor", 0.0)) for d in itens_desc)
            previsao["total_geral_liquido"] = max(total_contas_previsto - total_descontos_previsto, 0.0)
            previsao_mes_por_pessoa[p.id] = previsao

            mapa_mes = {}
            mapa_descontos_mes = {}
            refs = []
            for chave in sorted(chaves_com_contas):
                ano_ref, mes_ref = chave.split("-")
                refs.append((int(mes_ref), int(ano_ref)))
            mapa_mes_otimizado = pessoas_service.listar_contas_status_pessoa_meses(
                p.id, refs, mes_cartao_alt, ano_cartao_alt, conn=conn_pessoa
            )
            for mref in previsao.get("meses", []):
                m = int(mref["mes"])
                a = int(mref["ano"])
                chave = f"{a}-{m:02d}"
                mapa_mes[chave] = mapa_mes_otimizado.get(chave, [])
                mapa_descontos_mes[chave] = descontos_por_mes.get(chave, [])
            contas_status_por_pessoa_mes[p.id] = mapa_mes
            descontos_itens_por_pessoa_mes[p.id] = mapa_descontos_mes
        finally:
            conn_pessoa.close()

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
