from fastapi import APIRouter, Request, Query
from fastapi.responses import PlainTextResponse, JSONResponse
# Serviços relacionados à IA e histórico
from services.claude_service import (
    gerar_resposta,
    formatar_historico,
    salvar_historico
)
# Serviço responsável por enviar mensagens ao WhatsApp
from services.whatsapp import enviar_mensagem
# Serviço responsável por estado da conversa (sessão)
from services.session_service import (
    obter_sessao,
    atualizar_estado,
    atualizar_dados_agendamento,
    EstadosConversa,
    obter_agendamento_id,
    definir_agendamento_id
)
# Camada de persistência
from db.mysql import (
    buscar_cliente_por_numero,
    criar_cliente,
    salvar_conversa,
    criar_agendamento_em_progresso,
    atualizar_agendamento,
    buscar_agendamento_em_progresso
)
import re

# Cria agrupamento de rotas
router = APIRouter()

# Token usado pela Meta para validar o webhook
VERIFY_TOKEN = "meu_token_secreto"

@router.get("/webhook")
async def verificar_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge")
):
    """
    Endpoint chamado pela Meta durante configuração do webhook.
    Se o token estiver correto, devolve o challenge.
    """

    if (
        hub_mode == "subscribe"
        and hub_verify_token == VERIFY_TOKEN
    ):
        return PlainTextResponse(content=hub_challenge)
    return PlainTextResponse(
        content="Token inválido",
        status_code=403
    )

def detectar_intencao(mensagem: str, estado: str) -> str:
    """
    Implementa máquina de estados simples.

    Decide para qual etapa da conversa
    o usuário será encaminhado.
    """

    msg_lower = mensagem.lower()

    # Detecta intenção inicial de agendamento
    if any(
        palavra in msg_lower
        for palavra in [
            "agendar",
            "marcar",
            "consulta",
            "appointment"
        ]
    ):
        return EstadosConversa.AGENDAMENTO_PENDENTE


    # Detecta preenchimento de data
    if (
        estado == EstadosConversa.AGUARDANDO_DATA
        and re.search(
            r'\d{2}/\d{2}/\d{4}',
            mensagem
        )
    ):
        return EstadosConversa.AGUARDANDO_HORARIO

    # Detecta preenchimento de horário
    if (
        estado == EstadosConversa.AGUARDANDO_HORARIO
        and re.search(
            r'\d{1,2}[:h]\d{2}',
            mensagem
        )
    ):
        return EstadosConversa.AGUARDANDO_TIPO

    # Detecta tipo de atendimento
    if (
        estado == EstadosConversa.AGUARDANDO_TIPO
        and any(
            palavra in msg_lower
            for palavra in [
                "avaliação",
                "acompanhamento",
                "fisioterapia",
                "outro"
            ]
        )
    ):
        return EstadosConversa.AGENDAMENTO_CONFIRMADO

    # Fluxo padrão: conversa livre
    return EstadosConversa.CONVERSA_LIVRE


@router.post("/webhook")
async def webhook(request: Request):
    """
    Endpoint principal.

    Fluxo:
    Meta → Webhook → Sessão →
    Agendamento → Claude →
    Persistência → WhatsApp
    """

    try:
        # Lê corpo da requisição
        data = await request.json()

        # Extrai mensagem do formato enviado pela Meta
        changes = (
            data
            .get("entry", [{}])[0]
            .get("changes", [{}])[0]
        )

        messages = (
            changes
            .get("value", {})
            .get("messages", [])
        )


        # Ignora eventos sem mensagem
        if not messages:
            return JSONResponse({"status": "ok"})


        mensagem = messages[0]
        numero_cliente = mensagem.get("from")
        texto_cliente = (
            mensagem
            .get("text", {})
            .get("body", "")
        )

        # Evita processar payload inválido
        if (
            not numero_cliente
            or not texto_cliente
        ):
            return JSONResponse({"status": "ok"})

        # Busca cliente ou cria registro
        cliente = buscar_cliente_por_numero(
            numero_cliente
        )

        if not cliente:
            cliente_id = criar_cliente(
                numero_cliente
            )

        else:
            cliente_id = cliente["id"]


        # Recupera sessão ativa
        sessao = obter_sessao(
            numero_cliente
        )

        estado_atual = sessao.get(
            "estado",
            EstadosConversa.INICIAL
        )

        historico = sessao.get(
            "historico",
            []
        )

        dados_agendamento = sessao.get(
            "dados_agendamento",
            {}
        )

        # Detecta próximo estado
        novo_estado = detectar_intencao(
            texto_cliente,
            estado_atual
        )

        # Chama IA para gerar resposta
        resposta = await gerar_resposta(
            numero_cliente,
            texto_cliente,
            estado=novo_estado,
            historico=historico,
            dados_agendamento=dados_agendamento
        )

        # Atualiza histórico
        historico.append(
            {
                "role": "user",
                "content": texto_cliente
            }
        )

        historico.append(
            {
                "role": "assistant",
                "content": resposta
            }
        )


        # Mantém somente últimas mensagens
        sessao["historico"] = historico[-10:]

        sessao["estado"] = novo_estado

        # Salva sessão
        from services.session_service import salvar_sessao

        salvar_sessao(
            numero_cliente,
            sessao
        )

        # Persiste conversa
        salvar_conversa(
            cliente_id,
            texto_cliente,
            resposta
        )

        # Envia resposta ao cliente
        await enviar_mensagem(
            numero_cliente,
            resposta
        )

        print(
            f"✅ Estado: {novo_estado}"
        )

        return JSONResponse(
            {"status": "ok"}
        )

    except Exception as e:

        print(
            f"❌ Erro: {e}"
        )

        import traceback

        traceback.print_exc()

        return JSONResponse(
            {
                "status": "error",
                "message": str(e)
            },
            status_code=500
        )