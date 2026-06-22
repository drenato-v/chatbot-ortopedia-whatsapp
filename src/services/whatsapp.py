# Cliente HTTP assíncrono
import httpx
# Variáveis de ambiente
import os
# Tipagem opcional
from typing import Optional

async def enviar_mensagem(
    numero_destinatario: str,
    texto: str
) -> dict:
    """
    Envia mensagem simples.

    Fluxo:
    Sistema → Meta → Cliente
    """

    api_url   = os.getenv("WHATSAPP_API_URL", "https://graph.facebook.com/v18.0")
    phone_id  = os.getenv("WHATSAPP_PHONE_ID")
    token     = os.getenv("WHATSAPP_TOKEN")

    url = f"{api_url}/{phone_id}/messages"

    payload = {
        "messaging_product": "whatsapp",
        "to": numero_destinatario,
        "type": "text",
        "text": {"body": texto}
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # Cria conexão HTTP temporária
    async with httpx.AsyncClient() as client:

        response = await client.post(
            url,
            json=payload,
            headers=headers
        )

    result = response.json()
    print(f"[WhatsApp API] status={response.status_code} body={result}")
    return result

async def enviar_template(
    numero_destinatario: str,
    template_name: str,
    parametros: Optional[list] = None
) -> dict:
    """
    Envia mensagem baseada
    em template aprovado.
    """

    api_url  = os.getenv("WHATSAPP_API_URL", "https://graph.facebook.com/v18.0")
    phone_id = os.getenv("WHATSAPP_PHONE_ID")
    token    = os.getenv("WHATSAPP_TOKEN")

    url = f"{api_url}/{phone_id}/messages"

    payload = {
        "messaging_product": "whatsapp",
        "to": numero_destinatario,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": "pt_BR"}
        }
    }

    if parametros:
        payload["template"]["components"] = [
            {"type": "body", "parameters": parametros}
        ]

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            json=payload,
            headers=headers
        )

    return response.json()