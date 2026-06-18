# Modelo base do Pydantic
from pydantic import BaseModel
# Datas usadas em registros
from datetime import datetime
# Campos opcionais
from typing import Optional

# CLIENTES
class ClienteCreate(BaseModel):
    """
    Estrutura usada para criar cliente.
    """

    numero_whatsapp: str
    nome: Optional[str] = None
    email: Optional[str] = None



class Cliente(ClienteCreate):
    """
    Representação completa
    de cliente persistido.
    """

    id: int
    created_at: datetime

# CONVERSAS
class ConversaCreate(BaseModel):
    """
    Estrutura para salvar interação.
    """

    cliente_id: int
    mensagem_usuario: str
    resposta_bot: str



class Conversa(ConversaCreate):
    """
    Conversa registrada.
    """

    id: int
    created_at: datetime

# AGENDAMENTOS
class AgendamentoCreate(BaseModel):
    """
    Dados necessários
    para criar agendamento.
    """

    cliente_id: int
    data_agendamento: datetime
    tipo_consulta: Optional[str] = None



class Agendamento(AgendamentoCreate):
    """
    Agendamento persistido.
    """

    id: int
    status: str = "pendente"
    created_at: datetime

# FAQ
class FAQCreate(BaseModel):
    """
    Entrada para criação
    de conhecimento.
    """

    pergunta: str
    resposta: str
    categoria: Optional[str] = None

class FAQ(FAQCreate):
    """
    FAQ armazenada.
    """

    id: int
    created_at: datetime