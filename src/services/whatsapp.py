import httpx
import os
from typing import Optional

WHATSAPP_API_URL = os.getenv("WHATSAPP_API_URL", "https://graph.instagram.com/v18.0")
PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")

async def enviar_mensagem(numero_destinatario: str, texto: str) -> dict:
    """Envia mensagem de texto via WhatsApp"""
    url = f"{WHATSAPP_API_URL}/{PHONE_ID}/messages"
    
    payload = {
        "messaging_product": "whatsapp",
        "to": numero_destinatario,
        "type": "text",
        "text": {"body": texto}
    }
    
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers)
    
    return response.json()

async def enviar_template(numero_destinatario: str, template_name: str, parametros: Optional[list] = None) -> dict:
    """Envia mensagem usando template"""
    url = f"{WHATSAPP_API_URL}/{PHONE_ID}/messages"
    
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
        payload["template"]["parameters"] = {"body": {"parameters": parametros}}
    
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers)
    
    return response.json()