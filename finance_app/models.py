from dataclasses import dataclass
from typing import Optional


@dataclass
class ReceitaSaldo:
    id: int
    nome: str
    saldo_atual: float


@dataclass
class ReceitaExtra:
    id: int
    descricao: str
    valor_padrao: Optional[float]
    categoria: str
    data_recebimento: Optional[str]


@dataclass
class ReceitaLancamento:
    id: int
    saldo_id: int
    tipo_origem: str
    categoria: str
    descricao: Optional[str]
    valor: float
    created_at: str
    data_recebimento: Optional[str]


@dataclass
class ContaFixa:
    id: int
    nome: str
    categoria: Optional[str]
    valor_padrao: Optional[float]
    desconto_pessoa_nome: Optional[str]
    desconto_origem: Optional[str]
    desconto_receita_extra_id: Optional[int]
    desconto_aplicado: bool
    vencimento_dia: Optional[int]
    vencimento_data: Optional[str]
    mes_referencia: int
    ano_referencia: int
    status: str
    data_fim: Optional[str]


@dataclass
class CartaoConfig:
    id: int
    limite_total: Optional[float]
    dia_fechamento: int
    dia_vencimento: int
    fatura_paga: bool


@dataclass
class CartaoParcelada:
    id: int
    descricao: str
    valor_parcela: float
    total_parcelas: int
    parcela_atual: int
    mes_inicio: int
    ano_inicio: int
    status: str
    pessoa_id: Optional[int]


@dataclass
class CartaoAvista:
    id: int
    descricao: str
    valor: float
    mes_referencia: int
    ano_referencia: int
    pessoa_id: Optional[int]


@dataclass
class GastoPix:
    id: int
    descricao: str
    valor: float
    categoria: Optional[str]
    mes_referencia: int
    ano_referencia: int
    pessoa_id: Optional[int]
    receita_extra_id: Optional[int]


@dataclass
class Pessoa:
    id: int
    nome: str
    ativo: bool
    padrao: bool

