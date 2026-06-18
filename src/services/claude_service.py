import anthropic
import os
import json
from typing import Optional

CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

SYSTEM_PROMPT = """Você é um assistente de chatbot para a Ortopedia Geral, uma clínica de ortopedia.
Você ajuda com:
- Agendamento de consultas
- Respostas sobre tratamentos ortopédicos
- Esclarecimento de dúvidas gerais
- FAQ da clínica

Sempre seja educado, conciso e profissional. Se não souber responder, ofereça contato com a clínica."""

async def gerar_resposta(numero_cliente: str, mensagem_texto: str, historico: Optional[list] = None) -> str:
    """Gera resposta usando Claude API"""
    
    # Prepara histórico de conversas
    messages = historico or []
    messages.append({
        "role": "user",
        "content": mensagem_texto
    })
    
    # Faz requisição para Claude
    response = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=messages
    )
    
    resposta_texto = response.content[0].text
    
    return resposta_texto

def formatar_historico(dados_json: Optional[str]) -> list:
    """Converte JSON do Redis em lista de mensagens"""
    if not dados_json:
        return []
    try:
        return json.loads(dados_json)
    except:
        return []

def salvar_historico(historico: list) -> str:
    """Converte lista de mensagens em JSON para Redis"""
    return json.dumps(historico)