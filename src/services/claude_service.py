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
    prompt_base = f"""Você é a assistente virtual da Ortopedia Geral, clínica especializada em órteses, próteses e reabilitação.

CLÍNICA:
- Telefone: (17) 99793-1926
- Horário: Segunda a sexta, 08h às 18h
- Endereço: Rua General Glicério, 3841 — São José do Rio Preto/SP

SERVIÇOS DISPONÍVEIS:
Prótese, Palmilha, Tutor, Órteses, Órtese Individual, Cadeira de Rodas, Escaneamento 3D (inclui colete 3D)

FAQ:
{faq_texto}

REGRA CRÍTICA — DADOS DO SISTEMA:
Quando a mensagem do usuário contiver um bloco [SISTEMA: ...], esse bloco traz dados em tempo real do sistema interno da clínica (horários disponíveis, confirmações, instruções de fluxo). Você DEVE usar essas informações como verdade absoluta. NUNCA diga que não tem acesso à agenda ou a horários — quando o sistema fornecer esses dados, você os tem. Responda com base neles de forma natural e amigável, sem citar o bloco [SISTEMA] literalmente.
"""

    if estado == "aguardando_nome":
        return prompt_base + """
FLUXO: Aguardando nome do paciente.
Confirme o serviço detectado e pergunte o nome completo do paciente de forma simpática.
"""

    if estado == "aguardando_data":
        return prompt_base + """
FLUXO: Nome do paciente registrado. Aguardando data.
Apresente os horários disponíveis que estão no bloco [SISTEMA] e peça a data desejada no formato DD/MM/AAAA.
"""

    if estado == "aguardando_horario":
        return prompt_base + f"""
FLUXO: Data escolhida: {dados_agendamento.get("data") if dados_agendamento else ""}.
Mostre os horários disponíveis nessa data (estão no bloco [SISTEMA]) e peça ao cliente que escolha um.
"""

    if estado == "aguardando_tipo":
        return prompt_base + f"""
FLUXO: Data {dados_agendamento.get("data") if dados_agendamento else ""}, horário {dados_agendamento.get("horario") if dados_agendamento else ""}.
Se o serviço ainda não foi informado, pergunte qual é. Caso já esteja no bloco [SISTEMA], confirme e avance.
"""

    if estado == "agendamento_confirmado":
        return prompt_base + """
FLUXO: Agendamento confirmado com sucesso.
Informe todos os dados do agendamento (paciente, serviço, técnico, data, horário) de forma clara e deseje um bom atendimento.
"""

    # conversa_livre, inicial e qualquer outro estado
    return prompt_base + """
FLUXO: Conversa geral.
- Responda dúvidas sobre a clínica e serviços.
- Se o cliente perguntar sobre horários disponíveis e o bloco [SISTEMA] trouxer os dados, informe-os diretamente.
- Se o cliente quiser agendar, conduza o fluxo de agendamento.
- Seja breve, simpático e objetivo.
"""

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

            model="claude-sonnet-4-6",

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