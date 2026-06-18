from fastapi import APIRouter, Request, Query
from fastapi.responses import PlainTextResponse, JSONResponse
from services.claude_service import gerar_resposta, formatar_historico, salvar_historico
from services.whatsapp import enviar_mensagem
from db.redis import salvar_sessao, buscar_sessao
import json

router = APIRouter()

VERIFY_TOKEN = "meu_token_secreto"

@router.get("/webhook")
async def verificar_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge")
):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return PlainTextResponse(content=hub_challenge)
    return PlainTextResponse(content="Token inválido", status_code=403)

@router.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
        print("=== WEBHOOK RECEBIDO ===")
        print(json.dumps(data, indent=2))
        
        changes = data.get("entry", [{}])[0].get("changes", [{}])[0]
        messages = changes.get("value", {}).get("messages", [])
        
        print(f"Mensagens encontradas: {len(messages)}")
        
        if not messages:
            return JSONResponse({"status": "ok"})
        
        mensagem = messages[0]
        numero_cliente = mensagem.get("from")
        texto_cliente = mensagem.get("text", {}).get("body", "")
        
        print(f"Número: {numero_cliente}, Texto: {texto_cliente}")
        
        if not numero_cliente or not texto_cliente:
            return JSONResponse({"status": "ok"})
        
        # Busca histórico da sessão no Redis
        historico_json = buscar_sessao(numero_cliente)
        historico = formatar_historico(historico_json)
        
        # Gera resposta com Claude
        resposta = await gerar_resposta(numero_cliente, texto_cliente, historico)
        
        # Atualiza histórico
        historico.append({"role": "user", "content": texto_cliente})
        historico.append({"role": "assistant", "content": resposta})
        salvar_sessao(numero_cliente, salvar_historico(historico), ttl=86400)
        
        # Envia resposta via WhatsApp
        await enviar_mensagem(numero_cliente, resposta)
        
        print(f"Resposta enviada para {numero_cliente}")
        return JSONResponse({"status": "ok"})
    
    except Exception as e:
        print(f"Erro ao processar webhook: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)