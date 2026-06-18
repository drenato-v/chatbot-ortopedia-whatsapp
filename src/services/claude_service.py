# SDK oficial da Anthropic
import anthropic
# Variáveis de ambiente
import os
# Serialização do histórico
import json
# Tipagem opcional
from typing import Optional
# Busca conhecimento persistido
# (base simples de perguntas e respostas)
from db.mysql import buscar_faq

# Recupera chave da API do ambiente
CLAUDE_API_KEY = os.getenv(
    "CLAUDE_API_KEY"
)

# Inicializa cliente global
# para reutilizar conexões
client = anthropic.Anthropic(
    api_key=CLAUDE_API_KEY
)

def gerar_system_prompt(
    estado: str = "inicial",
    dados_agendamento: dict = None
) -> str:
    """
    Monta dinamicamente o system prompt.

    Objetivo:
    adaptar comportamento da IA
    conforme estágio da conversa.
    """

    # Recupera FAQ do banco
    faq_list = buscar_faq()

    # Converte FAQ para texto
    faq_texto = "\n".join(

        [
            f"P: {item['pergunta']}\nR: {item['resposta']}"

            for item in faq_list
        ]

    )

    # Contexto fixo
    prompt_base = f"""
Você é um assistente inteligente do chatbot da Ortopedia Geral.

OBJETIVO:
Atender com educação,
agendar consultas,
responder dúvidas.

INFORMAÇÕES:

- Telefone: (17)99793-1926
- Horário: Segunda a sexta, 08h às 18h
- Endereço:
Rua General Glicério, 3841,
São José do Rio Preto - SP

FAQ:

{faq_texto}
"""

    # Solicitação de data
    if estado == "aguardando_data":

        return (
            prompt_base
            +
            """
ESTADO:
Usuário iniciou agendamento.

Solicite somente a data.

Formato:
DD/MM/YYYY
"""
        )

    # Solicitação de horário
    elif estado == "aguardando_horario":

        return (
            prompt_base
            +
            f"""
ESTADO:
Data escolhida:
{dados_agendamento.get("data")}

Solicite horário.

Atendimento:
08h às 18h
"""
        )

    # Solicitação tipo consulta
    elif estado == "aguardando_tipo":

        return (
            prompt_base
            +
            f"""
ESTADO:

Data:
{dados_agendamento.get("data")}

Horário:
{dados_agendamento.get("horario")}

Pergunte:

- Avaliação inicial
- Acompanhamento
- Fisioterapia
- Outro
"""
        )

    # Conversa geral
    else:

        return (
            prompt_base
            +
            """
Responda naturalmente.

Se:
- ortopedia → responda
- agendamento → conduza fluxo
- dúvida → consulte FAQ
"""
        )

async def gerar_resposta(
    numero_cliente: str,
    mensagem_texto: str,
    estado: str = "inicial",
    historico: Optional[list] = None,
    dados_agendamento: dict = None
) -> str:
    """
    Envia contexto ao Claude
    e retorna resposta.
    """

    messages = historico or []

    # Adiciona mensagem atual
    messages.append(

        {
            "role": "user",
            "content": mensagem_texto
        }

    )

    try:

        response = client.messages.create(

            model="claude-3-5-sonnet-20241022",

            max_tokens=1024,

            system=gerar_system_prompt(
                estado,
                dados_agendamento
            ),

            messages=messages
        )


        return (
            response
            .content[0]
            .text
        )


    except Exception as e:

        print(
            f"Erro ao chamar Claude: {e}"
        )

        return (
            "Desculpe, tive um problema. "
            "Tente novamente."
        )

def formatar_historico(
    dados_json: Optional[str]
) -> list:
    """
    Converte JSON para lista.
    """

    if not dados_json:
        return []

    try:

        return json.loads(
            dados_json
        )

    except:

        return []

def salvar_historico(
    historico: list
) -> str:
    """
    Serializa histórico.
    """

    return json.dumps(
        historico
    )