# ============================================================
# Gerenciamento de sessão da conversa usando Redis
# Responsável por:
# - Criar sessões
# - Persistir estado da conversa
# - Armazenar dados do agendamento
# - Recuperar informações entre mensagens
# ============================================================


# Cliente Redis compartilhado por toda a aplicação
from db.redis import client

# Utilizado para converter estruturas Python ↔ JSON
import json

# Tipagem para indicar retorno opcional (valor ou None)
from typing import Optional


class EstadosConversa:
    """
    Máquina de estados da conversa com o paciente.

    Cada estado representa um ponto do fluxo de atendimento.
    O webhook utiliza esse valor para decidir como interpretar
    a próxima mensagem recebida.

    Fluxo principal:

    INICIAL
        ↓
    AGENDAMENTO_PENDENTE
        ↓
    AGUARDANDO_NOME
        ↓
    AGUARDANDO_TELEFONE
        ↓
    AGUARDANDO_DATA
        ↓
    AGUARDANDO_HORARIO
        ↓
    AGUARDANDO_TIPO
        ↓
    AGENDAMENTO_CONFIRMADO
        ↓
    CONVERSA_LIVRE
    """

    # Estado inicial da conversa
    # O bot ainda não iniciou coleta de dados
    INICIAL = "inicial"

    # Serviço identificado e aguardando confirmação
    # antes de iniciar coleta de informações
    AGENDAMENTO_PENDENTE = "agendamento_pendente"

    # Coleta do nome completo
    AGUARDANDO_NOME = "aguardando_nome"

    # Coleta do telefone
    AGUARDANDO_TELEFONE = "aguardando_telefone"

    # Coleta da data desejada
    AGUARDANDO_DATA = "aguardando_data"

    # Coleta do horário
    AGUARDANDO_HORARIO = "aguardando_horario"

    # Identificação ou confirmação do tipo de consulta
    AGUARDANDO_TIPO = "aguardando_tipo"

    # Agendamento já salvo e aguardando aprovação
    AGENDAMENTO_CONFIRMADO = "agendamento_confirmado"

    # Fluxo encerrado; IA responde normalmente
    CONVERSA_LIVRE = "conversa_livre"


def obter_sessao(numero_cliente: str) -> dict:
    """
    Recupera a sessão do Redis.

    Processo:
    1. Busca usando a chave sessao:<numero>.
    2. Se não existir:
       - cria sessão padrão
       - salva no Redis
    3. Retorna dicionário Python.
    """

    # Recupera JSON armazenado
    sessao_json = client.get(f"sessao:{numero_cliente}")

    # Primeira interação ou sessão expirada
    if not sessao_json:
        return criar_sessao_padrao(numero_cliente)

    # Converte JSON → dict
    return json.loads(sessao_json)


def criar_sessao_padrao(numero_cliente: str) -> dict:
    """
    Cria uma sessão inicial.

    Estrutura:
    {
        numero,
        estado,
        historico,
        dados_agendamento
    }

    Após criar:
    - salva no Redis
    - retorna sessão criada
    """

    sessao = {
        # Identificador do cliente
        "numero": numero_cliente,

        # Estado inicial do fluxo
        "estado": EstadosConversa.INICIAL,

        # Histórico de mensagens
        "historico": [],

        # Informações coletadas durante o agendamento
        "dados_agendamento": {

            # Data desejada
            "data": None,

            # Horário escolhido
            "horario": None,

            # Tipo de atendimento
            "tipo_consulta": None,
        },
    }

    # Persiste imediatamente
    salvar_sessao(numero_cliente, sessao)

    return sessao


def salvar_sessao(
    numero_cliente: str,
    dados: dict,
    ttl: int = 86400,
):
    """
    Salva sessão no Redis.

    Parâmetros:
    - numero_cliente → identificador da sessão
    - dados → conteúdo serializado
    - ttl → tempo de vida

    TTL padrão:
    86400 segundos = 24 horas

    Após expiração:
    a sessão será removida automaticamente.
    """

    client.setex(
        # Chave Redis
        f"sessao:{numero_cliente}",

        # Tempo de expiração
        ttl,

        # Dict → JSON
        json.dumps(dados),
    )


def atualizar_estado(
    numero_cliente: str,
    novo_estado: str,
):
    """
    Atualiza apenas o estado atual.

    Mantém:
    - histórico
    - dados do agendamento
    - demais campos
    """

    sessao = obter_sessao(numero_cliente)

    # Substitui somente o estado
    sessao["estado"] = novo_estado

    salvar_sessao(numero_cliente, sessao)


def atualizar_dados_agendamento(
    numero_cliente: str,
    **kwargs,
):
    """
    Atualiza campos específicos do agendamento.

    Exemplo:
    atualizar_dados_agendamento(
        numero,
        data="25/06",
        horario="14:00"
    )

    Usa update() para preservar valores existentes.
    """

    sessao = obter_sessao(numero_cliente)

    # Atualização parcial
    sessao["dados_agendamento"].update(kwargs)

    salvar_sessao(numero_cliente, sessao)


def limpar_sessao(numero_cliente: str):
    """
    Remove completamente a sessão do Redis.

    Cenários comuns:
    - agendamento concluído
    - cancelamento
    - limpeza administrativa
    """

    client.delete(f"sessao:{numero_cliente}")


def obter_agendamento_id(
    numero_cliente: str,
) -> Optional[int]:
    """
    Obtém o ID do agendamento associado à sessão.

    Retorno:
    - int → existe agendamento
    - None → não existe
    """

    sessao = obter_sessao(numero_cliente)

    return sessao.get("agendamento_id")


def definir_agendamento_id(
    numero_cliente: str,
    agendamento_id: int,
):
    """
    Associa um registro do banco à sessão.

    Permite manter vínculo entre:
    sessão Redis ↔ tabela de agendamentos
    """

    sessao = obter_sessao(numero_cliente)

    # Salva referência do banco
    sessao["agendamento_id"] = agendamento_id

    salvar_sessao(numero_cliente, sessao)