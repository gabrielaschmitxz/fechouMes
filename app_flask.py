"""AplicaÃ§Ã£o Flask principal para Fechou MÃªs - Controle Financeiro"""
from flask import Flask, render_template, request, redirect, url_for, flash
from datetime import datetime, date
import sys
from pathlib import Path

# Adiciona o diretÃ³rio raiz ao path
sys.path.insert(0, str(Path(__file__).parent))

from finance_app.database import setup_database
from finance_app.services import (
    receita_service,
    cartao_service,
    gastos_service,
    contas_service,
    pessoas_service,
)

app = Flask(__name__)
app.secret_key = 'fechou-mes-secret-key-2024'  # Mude em produÃ§Ã£o!

# Inicializa banco de dados
setup_database()


def _mes_ano_atual():
    """Retorna mÃªs e ano atuais"""
    hoje = datetime.now()
    return hoje.month, hoje.year

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


@app.route('/')
def index():
    """Redireciona para dashboard"""
    return redirect(url_for('dashboard'))


@app.route('/dashboard')
def dashboard():
    """PÃ¡gina principal do dashboard"""
    mes = request.args.get('mes', type=int, default=_mes_ano_atual()[0])
    ano = request.args.get('ano', type=int, default=_mes_ano_atual()[1])
    
    # Buscar dados
    pessoas_ativas = pessoas_service.listar_pessoas(only_ativas=True)
    nomes_padrao = [p.nome.strip() for p in pessoas_ativas if p.padrao and p.nome.strip()]
    receita_service.garantir_saldos_por_nomes(nomes_padrao)
    resumo_receitas_padrao, _ = receita_service.calcular_resumo_receitas_padrao(nomes_padrao)
    saldos_beneficios_por_pessoa = receita_service.calcular_saldos_beneficios_por_pessoa(nomes_padrao)
    gastos_pix_por_pessoa = gastos_service.calcular_totais_gastos_pix_por_pessoa(mes, ano)
    pessoa_id_por_nome = {p.nome.strip(): p.id for p in pessoas_ativas if p.nome.strip()}
    pix_por_nome_padrao = {
        nome: float(gastos_pix_por_pessoa.get(pessoa_id_por_nome.get(nome, -1), 0.0))
        for nome in nomes_padrao
    }
    total_geral = sum(float(x["saldo_conta"]) for x in resumo_receitas_padrao)
    fatura_info = cartao_service.calcular_fatura_atual()
    totais_pix = gastos_service.calcular_totais_gastos_pix(mes, ano)
    totais_contas = contas_service.calcular_totais_contas_fixas(mes, ano)
    total_mes_terc, total_pago_terc, saldo_pend_terc = pessoas_service.calcular_totais_gerais_terceiros(mes, ano)
    
    total_despesas = (
        totais_contas["total"]
        + fatura_info["total_geral"]
        + totais_pix["total_geral"]
    )
    saldo_restante = total_geral - total_despesas
    
    return render_template('dashboard.html',
        mes=mes, ano=ano,
        resumo_receitas_padrao=resumo_receitas_padrao,
        pix_por_nome_padrao=pix_por_nome_padrao,
        saldos_beneficios_por_pessoa=saldos_beneficios_por_pessoa,
        total_geral=total_geral,
        totais_contas=totais_contas,
        fatura_info=fatura_info,
        totais_pix=totais_pix,
        total_mes_terc=total_mes_terc,
        total_pago_terc=total_pago_terc,
        saldo_pend_terc=saldo_pend_terc,
        total_despesas=total_despesas,
        saldo_restante=saldo_restante
    )


@app.route('/receitas', methods=['GET', 'POST'])
def receitas():
    """PÃ¡gina de receitas"""
    mes = request.args.get('mes', type=int, default=_mes_ano_atual()[0])
    ano = request.args.get('ano', type=int, default=_mes_ano_atual()[1])
    pessoas_ativas = pessoas_service.listar_pessoas(only_ativas=True)
    nomes_padrao_lista = [p.nome.strip() for p in pessoas_ativas if p.padrao and p.nome.strip()]
    receita_service.garantir_saldos_por_nomes(nomes_padrao_lista)

    saldos = receita_service.listar_saldos()
    extras = receita_service.listar_receitas_extras()
    nomes_padrao = {nome.lower() for nome in nomes_padrao_lista}
    saldos_padrao = [s for s in saldos if s.nome.strip().lower() in nomes_padrao]
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'salario':
            pessoa = request.form.get('pessoa')
            valor = _parse_brl_value(request.form.get('valor'), 0.0)
            pessoa_valida = any(s.nome == pessoa for s in saldos_padrao)
            if not pessoa_valida:
                flash('Selecione uma pessoa padrão válida.', 'warning')
            elif valor > 0:
                receita_service.registrar_salario_recebido(pessoa, valor, 'salario')
                flash('SalÃ¡rio registrado com sucesso.', 'success')
            else:
                flash('Informe um valor maior que zero.', 'warning')
            return redirect(url_for('receitas'))
        
        elif action == 'extra':
            extra_select = request.form.get('extra_select')
            descricao_nova = request.form.get('descricao_nova', '')
            descricao_existente = request.form.get('descricao', '')
            descricao = descricao_nova if extra_select == 'novo' else (descricao_existente or extra_select)
            categoria = (request.form.get('categoria_extra') or 'extra').strip().lower()
            data_recebimento = (request.form.get('data_recebimento') or '').strip()
            
            valor = _parse_brl_value(request.form.get('valor'), 0.0)
            pessoa_saldo = request.form.get('pessoa_saldo')
            pessoa_valida = any(s.nome == pessoa_saldo for s in saldos_padrao)
            categorias_validas = {'extra', 'beneficio', 'bonus'}
            extra_existente = next((e for e in extras if e.descricao == descricao), None)
            extra_ref = extra_existente
            data_ref = None

            # Para receita já cadastrada, usa categoria/data salvas como fonte da verdade.
            if extra_select != 'novo' and extra_existente:
                categoria = (extra_existente.categoria or categoria).strip().lower()
                if not data_recebimento and extra_existente.data_recebimento:
                    data_recebimento = str(extra_existente.data_recebimento)
            
            if not descricao:
                flash('Informe a descriÃ§Ã£o.', 'warning')
                return redirect(url_for('receitas'))
            if not pessoa_valida:
                flash('Selecione uma pessoa padrão válida.', 'warning')
                return redirect(url_for('receitas'))
            if categoria not in categorias_validas:
                flash('Categoria inválida para receita.', 'warning')
                return redirect(url_for('receitas'))
            if categoria in {'extra', 'bonus'} and valor <= 0:
                flash('Para Extra/Bônus, informe um valor adicional maior que zero.', 'warning')
                return redirect(url_for('receitas'))
            if categoria == 'beneficio':
                if extra_select == 'novo':
                    if valor <= 0:
                        flash('Para novo benefício, informe o valor padrão.', 'warning')
                        return redirect(url_for('receitas'))
                elif not extra_existente:
                    flash('Benefício selecionado não encontrado.', 'warning')
                    return redirect(url_for('receitas'))
                elif valor <= 0 and (extra_existente.valor_padrao or 0) <= 0:
                    flash('Esse benefício não possui valor padrão cadastrado.', 'warning')
                    return redirect(url_for('receitas'))
                elif valor <= 0:
                    valor = float(extra_existente.valor_padrao)
            if categoria != 'beneficio' and valor <= 0:
                flash('Informe um valor maior que zero.', 'warning')
                return redirect(url_for('receitas'))
            if data_recebimento:
                try:
                    data_ref = datetime.strptime(data_recebimento, "%Y-%m-%d").date()
                except ValueError:
                    flash('Data recebimento inválida.', 'warning')
                    return redirect(url_for('receitas'))
            if categoria == 'beneficio' and extra_select != 'novo' and extra_existente and not data_ref and extra_existente.data_recebimento:
                try:
                    data_ref = datetime.strptime(extra_existente.data_recebimento, "%Y-%m-%d").date()
                except ValueError:
                    data_ref = None
            if data_ref and data_ref.year < 2000:
                flash('Data recebimento inválida.', 'warning')
                return redirect(url_for('receitas'))
            
            if extra_select == 'novo':
                valor_padrao = valor if categoria == 'beneficio' else None
                extra_ref = receita_service.criar_ou_atualizar_receita_extra(
                    descricao,
                    valor_padrao,
                    categoria,
                    data_ref.isoformat() if data_ref else None,
                )
            saldo = receita_service.obter_saldo_por_nome(pessoa_saldo)
            if saldo:
                if categoria == 'beneficio' and data_ref and data_ref > date.today():
                    receita_service.registrar_receita_agendada(
                        saldo.id,
                        categoria,
                        valor,
                        descricao,
                        data_ref.isoformat(),
                        extra_ref.id if extra_ref else None,
                    )
                    flash('Benefício agendado para recebimento futuro (não somado no saldo ainda).', 'info')
                else:
                    receita_service.registrar_extra_recebido(
                        saldo.id,
                        valor,
                        descricao,
                        categoria,
                        extra_ref.id if extra_ref else None,
                        data_ref.isoformat() if data_ref else date.today().isoformat(),
                    )
                    flash('Receita registrada com sucesso.', 'success')
            else:
                flash('Saldo da pessoa não encontrado.', 'warning')
            return redirect(url_for('receitas'))

        elif action == 'editar_receita_extra':
            extra_id = int(request.form.get('extra_id', 0))
            descricao = (request.form.get('descricao') or '').strip()
            categoria = (request.form.get('categoria_extra_edit') or 'extra').strip().lower()
            data_recebimento = (request.form.get('data_recebimento_edit') or '').strip() or None
            valor_padrao_raw = (request.form.get('valor_padrao') or '').strip()
            valor_padrao = (
                _parse_brl_value(valor_padrao_raw, 0.0) if valor_padrao_raw else None
            )
            categorias_validas = {'extra', 'beneficio', 'bonus'}
            if extra_id <= 0 or not descricao:
                flash('Dados inválidos para editar receita.', 'warning')
            elif categoria not in categorias_validas:
                flash('Categoria inválida para receita.', 'warning')
            else:
                try:
                    if data_recebimento:
                        datetime.strptime(data_recebimento, "%Y-%m-%d")
                    if categoria != 'beneficio':
                        data_recebimento = None
                    ok = receita_service.atualizar_receita_extra(
                        extra_id, descricao, valor_padrao, categoria, data_recebimento
                    )
                    if ok:
                        flash('Receita atualizada com sucesso.', 'success')
                    else:
                        flash('Receita não encontrada.', 'warning')
                except ValueError:
                    flash('Data recebimento inválida.', 'warning')
                except Exception:
                    flash('Não foi possível atualizar (nome já pode existir).', 'warning')
            return redirect(url_for('receitas'))

        elif action == 'excluir_receita_extra':
            extra_id = int(request.form.get('extra_id', 0))
            if extra_id > 0 and receita_service.excluir_receita_extra(extra_id):
                flash('Receita excluída com sucesso.', 'success')
            else:
                flash('Não foi possível excluir a receita.', 'warning')
            return redirect(url_for('receitas'))

        elif action == 'excluir_lancamento':
            lancamento_id = int(request.form.get('lancamento_id', 0))
            if lancamento_id > 0 and receita_service.excluir_lancamento_receita(lancamento_id):
                flash('Lançamento removido com sucesso.', 'success')
            else:
                flash('Não foi possível remover o lançamento.', 'warning')
            return redirect(url_for('receitas'))

        elif action == 'editar_lancamento':
            lancamento_id = int(request.form.get('lancamento_id', 0))
            categoria = (request.form.get('categoria') or '').strip().lower()
            descricao = (request.form.get('descricao') or '').strip()
            valor = _parse_brl_value(request.form.get('valor'), 0.0)

            categorias_validas = {'salario', 'beneficio', 'bonus', 'extra'}
            if lancamento_id <= 0:
                flash('Lançamento inválido.', 'warning')
            elif categoria not in categorias_validas:
                flash('Categoria inválida.', 'warning')
            elif valor <= 0:
                flash('Informe um valor maior que zero.', 'warning')
            else:
                ok = receita_service.atualizar_lancamento_receita(
                    lancamento_id,
                    categoria,
                    descricao or None,
                    valor,
                )
                if ok:
                    flash('Lançamento atualizado com sucesso.', 'success')
                else:
                    flash('Não foi possível atualizar o lançamento.', 'warning')
            return redirect(url_for('receitas'))

    lancamentos_por_saldo = {}
    totais_cat_por_saldo = {}
    totais_receitas_por_saldo = {}
    gastos_por_saldo = {}
    totais_gastos_por_saldo = {}
    resumo_beneficios_por_saldo = {}
    pix_por_saldo = {}
    lancamentos_extras_tabela = []
    pessoas_todas = pessoas_service.listar_pessoas(only_ativas=False)
    pessoa_por_nome = {p.nome.strip().lower(): p for p in pessoas_todas}
    gastos_pix_por_pessoa = gastos_service.calcular_totais_gastos_pix_por_pessoa(mes, ano)
    for s in saldos:
        lancs = receita_service.listar_lancamentos_por_saldo(s.id)
        lancamentos_por_saldo[s.id] = lancs
        totais_cat_por_saldo[s.id] = receita_service.calcular_totais_lancamentos_por_categoria(s.id)
        totais_receitas_por_saldo[s.id] = sum(float(l.valor) for l in lancs)
        for l in lancs:
            if l.categoria == "salario":
                nome_receita = f"Salário - {s.nome}"
            elif l.categoria == "beneficio":
                nome_receita = f"Benefício - {s.nome}"
            elif l.categoria == "bonus":
                nome_receita = f"Bônus - {s.nome}"
            else:
                nome_receita = f"Receita - {s.nome}"
            lancamentos_extras_tabela.append(
                {
                    "lancamento_id": l.id,
                    "extra_nome": nome_receita,
                    "categoria": l.categoria,
                    "descricao": l.descricao or "",
                    "data_ref": l.data_recebimento or l.created_at[:10],
                    "status": "Agendado" if l.tipo_origem == "agendado" else "Recebido",
                    "valor": l.valor,
                }
            )

        pessoa = pessoa_por_nome.get(s.nome.strip().lower())
        if pessoa:
            gastos = pessoas_service.listar_contas_status_pessoa(pessoa.id, mes, ano)
        else:
            gastos = []
        gastos_por_saldo[s.id] = gastos
        totais_gastos_por_saldo[s.id] = sum(float(g["valor"]) for g in gastos)
        resumo_beneficios_por_saldo[s.id] = receita_service.listar_resumo_beneficios_por_saldo(s.id)
        pix_por_saldo[s.id] = float(gastos_pix_por_pessoa.get(pessoa.id, 0.0)) if pessoa else 0.0
    lancamentos_extras_tabela.sort(key=lambda x: str(x["data_ref"]), reverse=True)

    return render_template(
        'receitas.html',
        saldos=saldos,
        saldos_padrao=saldos_padrao,
        extras=extras,
        mes=mes,
        ano=ano,
        hoje_iso=date.today().isoformat(),
        lancamentos_extras_tabela=lancamentos_extras_tabela,
        lancamentos_por_saldo=lancamentos_por_saldo,
        totais_cat_por_saldo=totais_cat_por_saldo,
        totais_receitas_por_saldo=totais_receitas_por_saldo,
        gastos_por_saldo=gastos_por_saldo,
        totais_gastos_por_saldo=totais_gastos_por_saldo,
        resumo_beneficios_por_saldo=resumo_beneficios_por_saldo,
        pix_por_saldo=pix_por_saldo,
    )


@app.route('/cartao', methods=['GET', 'POST'])
def cartao():
    """PÃ¡gina do cartÃ£o de crÃ©dito"""
    cfg = cartao_service.get_config()
    
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
            
            mes_inicio, ano_inicio = _mes_ano_atual()
            if avista:
                cartao_service.registrar_compra_avista(descricao, valor_compra, pessoa_id)
            else:
                valor_total = valor_compra * total_parcelas if modo_valor == 'parcela' else valor_compra
                cartao_service.criar_parcelada(
                    descricao, valor_total, total_parcelas,
                    mes_inicio, ano_inicio, pessoa_id, parcela_atual
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

            if lancamento_id <= 0 or not descricao or valor <= 0:
                flash('Dados inválidos para edição.', 'warning')
                return redirect(url_for('cartao'))

            if tipo == 'avista':
                ok = cartao_service.atualizar_avista(
                    lancamento_id, descricao, valor, pessoa_id
                )
            elif tipo == 'parcelado':
                total_parcelas = int(request.form.get('total_parcelas', 1))
                parcela_atual = int(request.form.get('parcela_atual', 1))
                status = (request.form.get('status') or 'Ativa').strip().capitalize()
                if total_parcelas < 1 or parcela_atual < 1 or parcela_atual > total_parcelas:
                    flash('Parcela atual deve estar entre 1 e o total de parcelas.', 'warning')
                    return redirect(url_for('cartao'))
                if status not in {'Ativa', 'Finalizada'}:
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
    pessoa_nome_por_id = {p.id: p.nome for p in pessoas}
    for l in lancamentos_todos:
        l["pessoa_nome"] = pessoa_nome_por_id.get(l.get("pessoa_id")) or "Nosso"
        l["periodo"] = f'{int(l["mes_ref"]):02d}/{int(l["ano_ref"])}'
        if l["tipo"] == "parcelado":
            l["parcelas_label"] = f'{int(l["parcela_atual"])}/{int(l["total_parcelas"])}'
        else:
            l["parcelas_label"] = "-"
    
    return render_template(
        'cartao.html',
        cfg=cfg,
        info=info,
        pessoas=pessoas,
        lancamentos_todos=lancamentos_todos,
    )


@app.route('/gastos-pix', methods=['GET', 'POST'])
def gastos_pix():
    """PÃ¡gina de gastos Pix/DÃ©bito"""
    mes = request.args.get('mes', type=int, default=_mes_ano_atual()[0])
    ano = request.args.get('ano', type=int, default=_mes_ano_atual()[1])
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'novo_gasto':
            descricao = request.form.get('descricao')
            valor = _parse_brl_value(request.form.get('valor'), 0.0)
            categoria = ''
            pessoa_id_str = request.form.get('pessoa_id', '')
            pessoa_id = int(pessoa_id_str) if pessoa_id_str else None
            receita_extra_id_str = request.form.get('receita_extra_id', '')
            receita_extra_id = int(receita_extra_id_str) if receita_extra_id_str else None
            saldo_beneficio_nome = (request.form.get('saldo_beneficio_nome') or '').strip()
            
            if not descricao or valor <= 0:
                flash('Informe descriÃ§Ã£o e valor maior que zero.', 'warning')
                return redirect(url_for('gastos_pix', mes=mes, ano=ano))
            if pessoa_id is None:
                flash('Selecione uma pessoa para o gasto.', 'warning')
                return redirect(url_for('gastos_pix', mes=mes, ano=ano))
            if receita_extra_id and not saldo_beneficio_nome:
                flash('Selecione o saldo para abater o benefício.', 'warning')
                return redirect(url_for('gastos_pix', mes=mes, ano=ano))
            
            gastos_service.registrar_gasto_pix(
                descricao, valor, categoria, pessoa_id, receita_extra_id, mes, ano
            )
            if receita_extra_id:
                ok = receita_service.registrar_abatimento_beneficio(
                    saldo_beneficio_nome, receita_extra_id, valor, descricao
                )
                if not ok:
                    flash('Gasto salvo, mas não foi possível abater do benefício.', 'warning')
            flash('Gasto registrado com sucesso.', 'success')
            return redirect(url_for('gastos_pix', mes=mes, ano=ano))

        elif action == 'editar_gasto':
            gasto_id = int(request.form.get('gasto_id', 0))
            descricao = (request.form.get('descricao') or '').strip()
            valor = _parse_brl_value(request.form.get('valor'), 0.0)
            pessoa_id_str = request.form.get('pessoa_id', '')
            pessoa_id = int(pessoa_id_str) if pessoa_id_str else None

            if gasto_id <= 0 or not descricao or valor <= 0 or pessoa_id is None:
                flash('Dados inválidos para editar gasto.', 'warning')
                return redirect(url_for('gastos_pix', mes=mes, ano=ano))

            ok = gastos_service.atualizar_gasto_pix(gasto_id, descricao, valor, pessoa_id)
            if ok:
                flash('Gasto atualizado com sucesso.', 'success')
            else:
                flash('Não foi possível atualizar o gasto.', 'warning')
            return redirect(url_for('gastos_pix', mes=mes, ano=ano))

        elif action == 'excluir_gasto':
            gasto_id = int(request.form.get('gasto_id', 0))
            if gasto_id > 0 and gastos_service.excluir_gasto_pix(gasto_id):
                flash('Gasto excluído com sucesso.', 'success')
            else:
                flash('Não foi possível excluir o gasto.', 'warning')
            return redirect(url_for('gastos_pix', mes=mes, ano=ano))
    
    gastos = gastos_service.listar_gastos_pix(mes, ano)
    totais = gastos_service.calcular_totais_gastos_pix(mes, ano)
    pessoas = pessoas_service.listar_pessoas()
    pessoas_ativas = pessoas_service.listar_pessoas(only_ativas=True)
    nomes_padrao = [p.nome.strip() for p in pessoas_ativas if p.padrao and p.nome.strip()]
    receita_service.garantir_saldos_por_nomes(nomes_padrao)
    saldos = receita_service.listar_saldos()
    saldos_padrao = [s for s in saldos if s.nome in nomes_padrao]
    beneficios = [e for e in receita_service.listar_receitas_extras() if e.categoria == 'beneficio']
    
    return render_template('gastos_pix.html', 
        mes=mes, ano=ano, gastos=gastos, totais=totais, pessoas=pessoas, beneficios=beneficios, saldos_padrao=saldos_padrao)


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
            vencimento_data = (request.form.get('vencimento_data') or '').strip() or None
            data_fim_str = request.form.get('data_fim')
            
            if not nome:
                flash('Informe o nome da conta.', 'warning')
            else:
                contas_service.criar_conta_fixa(
                    nome, categoria, valor, vencimento_data, None, mes, ano, data_fim_str
                )
                flash('Conta fixa cadastrada.', 'success')
            return redirect(url_for('contas_fixas', mes=mes, ano=ano))


        elif action == 'editar_conta':
            conta_id = int(request.form.get('conta_id', 0))
            nome = (request.form.get('nome') or '').strip()
            categoria = (request.form.get('categoria') or '').strip() or None
            valor_str = (request.form.get('valor') or '').strip()
            valor = _parse_brl_value(valor_str, None) if valor_str else None
            vencimento_data = (request.form.get('vencimento_data') or '').strip() or None
            data_fim = (request.form.get('data_fim') or '').strip() or None

            if conta_id <= 0 or not nome:
                flash('Dados inválidos para editar conta.', 'warning')
            else:
                ok = contas_service.atualizar_conta_fixa(
                    conta_id, nome, categoria, valor, vencimento_data, data_fim
                )
                if ok:
                    flash('Conta atualizada com sucesso.', 'success')
                else:
                    flash('Conta não encontrada.', 'warning')
            return redirect(url_for('contas_fixas', mes=mes, ano=ano))

        elif action == 'excluir_conta':
            conta_id = int(request.form.get('conta_id', 0))
            if conta_id > 0 and contas_service.excluir_conta_fixa(conta_id):
                flash('Conta excluída com sucesso.', 'success')
            else:
                flash('Não foi possível excluir a conta.', 'warning')
            return redirect(url_for('contas_fixas', mes=mes, ano=ano))
        
        elif action == 'marcar_pago':
            conta_id = int(request.form.get('conta_id'))
            contas_service.marcar_conta_como_paga(conta_id)
            flash('Conta marcada como paga com sucesso.', 'success')
            return redirect(url_for('contas_fixas', mes=mes, ano=ano))
    
    # Gera automaticamente do mÃªs atual
    contas_service.gerar_contas_fixas_mes_atual()
    contas = contas_service.listar_contas_fixas(mes, ano)
    totais = contas_service.calcular_totais_contas_fixas(mes, ano)
    
    return render_template('contas_fixas.html', 
        mes=mes, ano=ano, contas=contas, totais=totais)


@app.route('/pessoas', methods=['GET', 'POST'])
def pessoas():
    """PÃ¡gina de pessoas (terceiros)"""
    mes = request.args.get('mes', type=int, default=_mes_ano_atual()[0])
    ano = request.args.get('ano', type=int, default=_mes_ano_atual()[1])
    
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

            total = pessoas_service.registrar_pagamento_terceiro_por_itens(
                pessoa_id, itens_tokens, mes, ano
            )
            if total > 0:
                flash(f'Pagamento registrado: R$ {total:,.2f}.', 'success')
            else:
                flash('Selecione ao menos uma conta pendente.', 'warning')
            return redirect(url_for('pessoas', mes=mes, ano=ano))
    
    pessoas_list = pessoas_service.listar_pessoas(only_ativas=False) # Listar todas as pessoas para gerenciamento
    totais_por_pessoa = pessoas_service.calcular_totais_por_pessoa(mes, ano)
    resumos = []
    for p in pessoas_list:
        info = totais_por_pessoa.get(p.id, {"total_mes": 0.0, "total_pago": 0.0, "saldo_pendente": 0.0})
        resumos.append({
            'pessoa': p,
            'total_mes': info["total_mes"],
            'total_pago': info["total_pago"],
            'saldo_pend': info["saldo_pendente"]
        })
    
    total_mes_geral, total_pago_geral, saldo_pend_geral = pessoas_service.calcular_totais_gerais_terceiros(mes, ano)

    pessoas_ativas = [p for p in pessoas_list if p.ativo and not p.padrao]
    contas_status_por_pessoa = {}
    for p in pessoas_ativas:
        contas_status_por_pessoa[p.id] = pessoas_service.listar_contas_status_pessoa(
            p.id, mes, ano
        )
    
    return render_template('pessoas.html',
        mes=mes, ano=ano,
        pessoas=pessoas_list,
        pessoas_ativas=pessoas_ativas,
        resumos=resumos,
        contas_status_por_pessoa=contas_status_por_pessoa,
        total_mes_geral=total_mes_geral,
        total_pago_geral=total_pago_geral,
        saldo_pend_geral=saldo_pend_geral
    )

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)


