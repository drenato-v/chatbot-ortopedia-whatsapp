# ============================================================
# Cliente de integração com WhatsApp Business API (Meta)
#
# Responsabilidades:
# - Enviar mensagens simples
# - Enviar templates aprovados
# - Centralizar comunicação HTTP
#
# Fluxo:
#
# FastAPI
#     ↓
# Serviço WhatsApp
#     ↓
# Graph API (Meta)
#     ↓
# Dispositivo do cliente
#
# Implementação assíncrona:
# usa httpx.AsyncClient para evitar bloquear
# o loop de eventos da aplicação.
# ============================================================


# Cliente HTTP assíncrono
# Permite chamadas externas sem travar o servidor
import httpx


# Leitura de variáveis de ambiente
# Evita credenciais fixas no código
import os


# Tipagem para parâmetros opcionais
from typing import Optional



async def enviar_mensagem(
    numero_destinatario: str,
    texto: str,
) -> dict:
    """
    Envia mensagem de texto simples.

    Entrada:
    - numero_destinatario → telefone no padrão esperado pela Meta
    - texto → conteúdo da mensagem

    Saída:
    JSON retornado pela Graph API.

    Exemplo de sucesso:
    {
        "messages":[
            {
                "id":"wamid..."
            }
        ]
    }
    """

    # ========================================================
    # Recupera configurações do ambiente
    #
    # Exemplo .env:
    #
    # WHATSAPP_API_URL=
    # WHATSAPP_PHONE_ID=
    # WHATSAPP_TOKEN=
    # ========================================================

    api_url = os.getenv(
        "WHATSAPP_API_URL",
        "https://graph.facebook.com/v18.0",
    )

    phone_id = os.getenv(
        "WHATSAPP_PHONE_ID"
    )

    token = os.getenv(
        "WHATSAPP_TOKEN"
    )


    # Endpoint de envio de mensagens
    #
    # Ex:
    # https://graph.facebook.com/v18.0/123/messages
    url = (
        f"{api_url}/"
        f"{phone_id}"
        f"/messages"
    )


    # ========================================================
    # Corpo da requisição
    #
    # type=text:
    # envia mensagem livre
    # ========================================================

    payload = {

        "messaging_product":
            "whatsapp",

        "to":
            numero_destinatario,

        "type":
            "text",

        "text": {

            "body":
                texto
        },
    }


    # Cabeçalhos HTTP
    headers = {

        # Token Bearer Meta
        "Authorization":
            f"Bearer {token}",

        # Conteúdo JSON
        "Content-Type":
            "application/json",
    }


    # ========================================================
    # Abre cliente HTTP
    #
    # AsyncClient:
    # - reutiliza conexões
    # - não bloqueia FastAPI
    # - fecha automaticamente
    # ========================================================

    async with httpx.AsyncClient() as client:

        response = await client.post(

            url,

            json=payload,

            headers=headers,
        )


    # Converte resposta
    result = response.json()


    # Log simples para debug
    print(
        "[WhatsApp API] "
        f"status={response.status_code} "
        f"body={result}"
    )


    return result



async def enviar_template(
    numero_destinatario: str,
    template_name: str,
    parametros: Optional[list] = None,
) -> dict:
    """
    Envia mensagem usando template.

    Templates são obrigatórios para:

    - iniciar conversa
    - enviar mensagens fora da janela de 24h

    Parâmetros:
    {{1}}
    {{2}}
    {{3}}

    são preenchidos dinamicamente.
    """

    # ========================================================
    # Configuração
    # ========================================================

    api_url = os.getenv(
        "WHATSAPP_API_URL",
        "https://graph.facebook.com/v18.0",
    )

    phone_id = os.getenv(
        "WHATSAPP_PHONE_ID"
    )

    token = os.getenv(
        "WHATSAPP_TOKEN"
    )


    # Endpoint da Meta
    url = (
        f"{api_url}/"
        f"{phone_id}"
        f"/messages"
    )


    # ========================================================
    # Payload base
    #
    # type=template:
    # envia modelo previamente aprovado
    # ========================================================

    payload = {

        "messaging_product":
            "whatsapp",

        "to":
            numero_destinatario,

        "type":
            "template",

        "template": {

            # Nome cadastrado na Meta
            "name":
                template_name,

            # Idioma aprovado
            "language": {

                "code":
                    "pt_BR"
            },
        },
    }


    # ========================================================
    # Injeta variáveis do template
    #
    # Ex:
    #
    # {{1}} → João
    # {{2}} → 15/06
    #
    # ========================================================

    if parametros:

        payload[
            "template"
        ][
            "components"
        ] = [

            {

                "type":
                    "body",

                "parameters":
                    parametros,
            }
        ]


    # Cabeçalhos
    headers = {

        "Authorization":
            f"Bearer {token}",

        "Content-Type":
            "application/json",
    }


    # Executa chamada HTTP
    async with httpx.AsyncClient() as client:

        response = await client.post(

            url,

            json=payload,

            headers=headers,
        )


    # Retorna resposta da API
    return response.json()