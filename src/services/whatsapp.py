# Cliente HTTP assíncrono
import httpx
# Variáveis de ambiente
import os
# Tipagem opcional
from typing import Optional

# Endpoint base da API Meta
WHATSAPP_API_URL = os.getenv(
    "WHATSAPP_API_URL",
    "https://graph.facebook.com/v18.0"
)

# ID do número configurado no painel Meta
PHONE_ID = os.getenv(
    "WHATSAPP_PHONE_ID"
)

# Token de autenticação
WHATSAPP_TOKEN = os.getenv(
    "WHATSAPP_TOKEN"
)

async def enviar_mensagem(
    numero_destinatario: str,
    texto: str
) -> dict:
    """
    Envia mensagem simples.

    Fluxo:
    Sistema → Meta → Cliente
    """

    url = (
        f"{WHATSAPP_API_URL}"
        f"/{PHONE_ID}"
        f"/messages"
    )

    # Corpo da requisição
    payload = {

        "messaging_product": "whatsapp",
        "to": numero_destinatario,
        "type": "text",
        "text": {
            "body": texto
        }
    }

    # Cabeçalhos
    headers = {
        "Authorization":
            f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type":
            "application/json"
    }

    # Cria conexão HTTP temporária
    async with httpx.AsyncClient() as client:

        response = await client.post(
            url,
            json=payload,
            headers=headers
        )

    # Retorna resposta da API
    return response.json()

async def enviar_template(
    numero_destinatario: str,
    template_name: str,
    parametros: Optional[list] = None
) -> dict:
    """
    Envia mensagem baseada
    em template aprovado.
    """

    url = (
        f"{WHATSAPP_API_URL}"
        f"/{PHONE_ID}"
        f"/messages"
    )

    payload = {

        "messaging_product":
            "whatsapp",

        "to":
            numero_destinatario,
        "type":
            "template",
        "template": {
            "name":
                template_name,
            "language": {
                "code":
                    "pt_BR"
            }
        }
    }

    # Adiciona parâmetros
    # somente se existirem
    if parametros:

        payload[
            "template"
        ][
            "parameters"
        ] = {

            "body": {

                "parameters":
                    parametros
            }
        }

    headers = {

        "Authorization":
            f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type":
            "application/json"
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            json=payload,
            headers=headers
        )

    return response.json()