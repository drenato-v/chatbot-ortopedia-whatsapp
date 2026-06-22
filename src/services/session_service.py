# Cliente Redis compartilhado pela aplicação
from db.redis import client
# Serialização dos dados da sessão
import json
# Tipo opcional para retornos que podem ser None
from typing import Optional

class EstadosConversa:
    """
    Define os estados possíveis da máquina de conversa.

    Cada estado representa uma etapa do atendimento
    e controla o comportamento do chatbot.
    """

    INICIAL = "inicial"

    AGENDAMENTO_PENDENTE = "agendamento_pendente"

    AGUARDANDO_NOME = "aguardando_nome"

    AGUARDANDO_DATA = "aguardando_data"

    AGUARDANDO_HORARIO = "aguardando_horario"

    AGUARDANDO_TIPO = "aguardando_tipo"

    AGENDAMENTO_CONFIRMADO = "agendamento_confirmado"

    CONVERSA_LIVRE = "conversa_livre"

def obter_sessao(numero_cliente: str) -> dict:
    """
    Recupera sessão do Redis.

    Caso não exista, cria uma sessão padrão.
    """

    sessao_json = client.get(
        f"sessao:{numero_cliente}"
    )

    if not sessao_json:
        return criar_sessao_padrao(
            numero_cliente
        )

    return json.loads(
        sessao_json
    )

def criar_sessao_padrao(numero_cliente: str) -> dict:
    """
    Cria estrutura inicial da sessão.

    Mantém:
    - estado atual;
    - histórico;
    - dados de agendamento.
    """

    sessao = {

        "numero": numero_cliente,

        "estado": EstadosConversa.INICIAL,

        "historico": [],

        "dados_agendamento": {

            "data": None,

            "horario": None,

            "tipo_consulta": None
        }
    }

    salvar_sessao(
        numero_cliente,
        sessao
    )

    return sessao

def salvar_sessao(
    numero_cliente: str,
    dados: dict,
    ttl: int = 86400
):
    """
    Salva sessão no Redis.

    TTL padrão:
    86400 segundos = 24 horas.
    """

    client.setex(

        f"sessao:{numero_cliente}",

        ttl,

        json.dumps(dados)
    )

def atualizar_estado(
    numero_cliente: str,
    novo_estado: str
):
    """
    Atualiza apenas o estado atual
    sem alterar restante da sessão.
    """

    sessao = obter_sessao(
        numero_cliente
    )

    sessao["estado"] = novo_estado

    salvar_sessao(
        numero_cliente,
        sessao
    )

def atualizar_dados_agendamento(
    numero_cliente: str,
    **kwargs
):
    """
    Atualiza parcialmente os dados
    relacionados ao agendamento.
    """

    sessao = obter_sessao(
        numero_cliente
    )

    sessao["dados_agendamento"].update(
        kwargs
    )

    salvar_sessao(
        numero_cliente,
        sessao
    )

def limpar_sessao(
    numero_cliente: str
):
    """
    Remove sessão do Redis.

    Útil após:
    - confirmação;
    - cancelamento;
    - timeout.
    """

    client.delete(
        f"sessao:{numero_cliente}"
    )

def obter_agendamento_id(
    numero_cliente: str
) -> Optional[int]:
    """
    Recupera ID do agendamento
    associado à conversa.
    """

    sessao = obter_sessao(
        numero_cliente
    )

    return sessao.get(
        "agendamento_id"
    )

def definir_agendamento_id(
    numero_cliente: str,
    agendamento_id: int
):
    """
    Associa um registro do banco
    à sessão atual.
    """

    sessao = obter_sessao(
        numero_cliente
    )

    sessao["agendamento_id"] = (
        agendamento_id
    )

    salvar_sessao(
        numero_cliente,
        sessao
    )