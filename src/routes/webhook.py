from fastapi import APIRouter, Request, Query
from fastapi.responses import PlainTextResponse, JSONResponse
from services.claude_service import gerar_resposta
from services.session_service import (
    EstadosConversa, obter_sessao, salvar_sessao,
    obter_agendamento_id, definir_agendamento_id,
)
from services.tecnico_service import (
    buscar_tecnico_cliente, buscar_tecnicos_disponiveis,
    buscar_horarios_disponiveis, atribuir_tecnico_cliente,
    marcar_hora_como_ocupada
)
from services.whatsapp import enviar_mensagem
from db.mysql import (
    buscar_cliente_por_numero, criar_cliente, salvar_conversa,
    criar_agendamento_em_progresso, atualizar_agendamento,
)
from datetime import datetime
import re
import os

router = APIRouter()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "ortopedia_token")

SETORES = [
    "Prótese", "Palmilha", "Tutor", "Órteses",
    "Órtese Individual", "Cadeira de Rodas", "Escaneamento 3D", "Outras"
]

# ── Webhook verification ───────────────────────────────────────────────────────

@router.get("/webhook")
async def verificar_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge")
):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return PlainTextResponse(content=hub_challenge)
    return PlainTextResponse(content="Token inválido", status_code=403)

# ── Detection helpers ──────────────────────────────────────────────────────────

def detectar_setor(mensagem: str) -> str:
    msg = mensagem.lower()
    if any(p in msg for p in ["ortese individual", "órtese individual"]):
        return "Órtese Individual"
    if any(p in msg for p in ["prótese", "protese", "membro artificial"]):
        return "Prótese"
    if any(p in msg for p in ["palmilha"]):
        return "Palmilha"
    if any(p in msg for p in ["tutor"]):
        return "Tutor"
    if any(p in msg for p in ["órtese", "ortese"]):
        return "Órteses"
    if any(p in msg for p in ["cadeira de rodas", "cadeira"]):
        return "Cadeira de Rodas"
    if any(p in msg for p in ["3d", "escaneamento", "scan", "colete"]):
        return "Escaneamento 3D"
    return None


_ESTADOS_EM_FLUXO = {
    EstadosConversa.AGENDAMENTO_PENDENTE,
    EstadosConversa.AGUARDANDO_NOME,
    EstadosConversa.AGUARDANDO_DATA,
    EstadosConversa.AGUARDANDO_HORARIO,
    EstadosConversa.AGUARDANDO_TIPO,
}

def detectar_intencao(mensagem: str, estado: str) -> str:
    msg = mensagem.lower()

    tem_data    = bool(re.search(r'\d{2}/\d{2}/\d{4}', mensagem))
    tem_horario = bool(re.search(r'\d{1,2}[:h]\d{2}', mensagem))
    tem_setor   = any(s.lower() in msg for s in SETORES) or bool(detectar_setor(mensagem))

    # Aguardando nome: qualquer mensagem é tratada como o nome do paciente
    if estado == EstadosConversa.AGUARDANDO_NOME:
        return EstadosConversa.AGUARDANDO_NOME

    # Novo pedido de agendamento (só fora de um fluxo já em andamento)
    if any(w in msg for w in ["agendar", "marcar", "consulta", "quero consultar"]) \
            and estado not in _ESTADOS_EM_FLUXO:
        return EstadosConversa.AGENDAMENTO_PENDENTE

    # Data fornecida → avança para aguardar horário
    if tem_data and estado in (EstadosConversa.AGUARDANDO_DATA,
                                EstadosConversa.AGENDAMENTO_PENDENTE):
        return EstadosConversa.AGUARDANDO_HORARIO

    # Horário fornecido → avança para aguardar tipo (ou confirma direto)
    if tem_horario and estado == EstadosConversa.AGUARDANDO_HORARIO:
        return EstadosConversa.AGUARDANDO_TIPO

    # Setor fornecido em AGENDAMENTO_PENDENTE → permanece pendente
    # (o handler avança para AGUARDANDO_NOME após salvar o setor)
    if tem_setor and estado == EstadosConversa.AGENDAMENTO_PENDENTE:
        return EstadosConversa.AGENDAMENTO_PENDENTE

    # Mantém estado ativo se já em fluxo de agendamento
    if estado in _ESTADOS_EM_FLUXO:
        return estado

    return EstadosConversa.CONVERSA_LIVRE


def formatar_horarios_para_claude(horarios: dict) -> str:
    linhas = []
    for data, slots in horarios.items():
        data_fmt = datetime.strptime(data, "%Y-%m-%d").strftime("%d/%m/%Y")
        disponiveis = [s["hora"] for s in slots if s["disponivel"]]
        if disponiveis:
            linhas.append(f"{data_fmt}: {', '.join(disponiveis)}")
    if linhas:
        return "Horários disponíveis nos próximos dias:\n" + "\n".join(linhas)
    return "Não há horários disponíveis nos próximos 7 dias."

# ── Main webhook ───────────────────────────────────────────────────────────────

@router.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()

        changes  = data.get("entry", [{}])[0].get("changes", [{}])[0]
        messages = changes.get("value", {}).get("messages", [])

        if not messages:
            return JSONResponse({"status": "ok"})

        mensagem       = messages[0]
        numero_cliente = mensagem.get("from")

        # Ignora mensagens não-texto (imagens, áudio, etc.)
        if mensagem.get("type") != "text":
            return JSONResponse({"status": "ok"})

        texto_cliente = mensagem.get("text", {}).get("body", "").strip()
        if not numero_cliente or not texto_cliente:
            return JSONResponse({"status": "ok"})

        # 1. Buscar/criar cliente ─────────────────────────────────────────────
        cliente = buscar_cliente_por_numero(numero_cliente)
        if not cliente:
            cliente_id = criar_cliente(numero_cliente)
        else:
            cliente_id = cliente["id"]

        # 2. Obter sessão ─────────────────────────────────────────────────────
        sessao           = obter_sessao(numero_cliente)
        estado_atual     = sessao.get("estado", EstadosConversa.INICIAL)
        historico        = sessao.get("historico", [])
        dados_agendamento = sessao.get("dados_agendamento", {})

        # Limpa estado após confirmação anterior
        if estado_atual == EstadosConversa.AGENDAMENTO_CONFIRMADO:
            estado_atual     = EstadosConversa.CONVERSA_LIVRE
            dados_agendamento = {}
            sessao.pop("agendamento_id", None)

        # 3. Detectar intenção e setor ────────────────────────────────────────
        novo_estado     = detectar_intencao(texto_cliente, estado_atual)
        setor_detectado = detectar_setor(texto_cliente) or dados_agendamento.get("setor")
        contexto_extra  = ""
        agendamento_id  = obter_agendamento_id(numero_cliente)

        # 4. Fluxo de agendamento ─────────────────────────────────────────────

        if novo_estado == EstadosConversa.AGENDAMENTO_PENDENTE:
            if not agendamento_id:
                agendamento_id = criar_agendamento_em_progresso(cliente_id)
                definir_agendamento_id(numero_cliente, agendamento_id)

            if setor_detectado:
                dados_agendamento["setor"] = setor_detectado
                tecnico_anterior = buscar_tecnico_cliente(cliente_id, setor_detectado)
                contexto_extra = f"Serviço detectado: {setor_detectado}. Pergunte o nome completo do paciente."
                if tecnico_anterior:
                    contexto_extra += (
                        f" (O cliente já foi atendido por {tecnico_anterior['nome']} neste setor,"
                        " mencione isso após confirmar o nome.)"
                    )
                novo_estado = EstadosConversa.AGUARDANDO_NOME
            else:
                lista = ", ".join(SETORES)
                contexto_extra = f"Pergunte qual serviço o cliente precisa. Opções: {lista}"

        elif novo_estado == EstadosConversa.AGUARDANDO_NOME:
            # A mensagem inteira é o nome do paciente
            nome_paciente = texto_cliente.strip()
            dados_agendamento["nome_paciente"] = nome_paciente
            setor = dados_agendamento.get("setor")
            hoje  = datetime.now().strftime("%Y-%m-%d")
            if setor:
                horarios = buscar_horarios_disponiveis(setor, hoje, dias=7)
                contexto_extra = (
                    f"Nome do paciente registrado: {nome_paciente}. "
                    + formatar_horarios_para_claude(horarios)
                    + "\nPergunte qual data deseja, no formato DD/MM/AAAA."
                )
            else:
                contexto_extra = (
                    f"Nome do paciente registrado: {nome_paciente}. "
                    "Pergunte qual data deseja, no formato DD/MM/AAAA."
                )
            novo_estado = EstadosConversa.AGUARDANDO_DATA

        elif novo_estado == EstadosConversa.AGUARDANDO_HORARIO:
            # Usuário acabou de fornecer a data
            data_match = re.search(r'(\d{2}/\d{2}/\d{4})', texto_cliente)
            if data_match:
                data_str = data_match.group(1)
                dados_agendamento["data"] = data_str
                try:
                    data_obj  = datetime.strptime(data_str, "%d/%m/%Y")
                    data_mysql = data_obj.strftime("%Y-%m-%d")
                    if agendamento_id:
                        atualizar_agendamento(agendamento_id, data_agendamento=data_obj)
                    setor = dados_agendamento.get("setor")
                    if setor:
                        slots_dia  = buscar_horarios_disponiveis(setor, data_mysql, dias=1)
                        disponiveis = [
                            s["hora"] for dia in slots_dia.values()
                            for s in dia if s["disponivel"]
                        ]
                        if disponiveis:
                            contexto_extra = (
                                f"Horários disponíveis em {data_str}: {', '.join(disponiveis)}. "
                                "Peça ao cliente para escolher um horário."
                            )
                        else:
                            contexto_extra = (
                                f"Não há horários disponíveis em {data_str}. "
                                "Informe ao cliente e peça outra data."
                            )
                            novo_estado = EstadosConversa.AGUARDANDO_DATA
                except ValueError:
                    contexto_extra = "Data inválida. Peça ao cliente para informar no formato DD/MM/AAAA."
                    novo_estado    = EstadosConversa.AGUARDANDO_DATA

        elif novo_estado == EstadosConversa.AGUARDANDO_TIPO:
            # Usuário acabou de fornecer o horário OU o setor (se estava pendente)
            horario_match = re.search(r'(\d{1,2})[:h](\d{2})', texto_cliente)
            if horario_match:
                hora_int    = int(horario_match.group(1))
                horario_str = f"{hora_int:02d}:{horario_match.group(2)}"
                dados_agendamento["horario"] = horario_str
                dados_agendamento["hora_int"] = hora_int
                if agendamento_id:
                    atualizar_agendamento(agendamento_id, horario=horario_str)

            # Salva setor se detectado agora e ainda não estava definido
            if setor_detectado and not dados_agendamento.get("setor"):
                dados_agendamento["setor"] = setor_detectado

            if dados_agendamento.get("setor"):
                novo_estado = EstadosConversa.AGENDAMENTO_CONFIRMADO
            else:
                lista = ", ".join(SETORES)
                contexto_extra = f"Pergunte qual o tipo de serviço. Opções: {lista}"

        # Bloco separado (não elif) para poder ser alcançado pelo bloco acima
        if novo_estado == EstadosConversa.AGENDAMENTO_CONFIRMADO:
            setor    = setor_detectado or dados_agendamento.get("setor")
            hora_int  = dados_agendamento.get("hora_int")
            data_str  = dados_agendamento.get("data")
            horario_str = dados_agendamento.get("horario", "")

            if setor and hora_int is not None and data_str:
                data_mysql = datetime.strptime(data_str, "%d/%m/%Y").strftime("%Y-%m-%d")
                data_hora  = datetime.strptime(f"{data_str} {horario_str}", "%d/%m/%Y %H:%M") \
                    if horario_str else datetime.strptime(data_str, "%d/%m/%Y")

                tecnico = buscar_tecnico_cliente(cliente_id, setor)
                if not tecnico:
                    tecnicos = buscar_tecnicos_disponiveis(data_mysql, hora_int, setor)
                    tecnico  = tecnicos[0] if tecnicos else None

                if tecnico:
                    atribuir_tecnico_cliente(cliente_id, tecnico["id"], setor)
                    marcar_hora_como_ocupada(tecnico["id"], data_mysql, hora_int)
                    if agendamento_id:
                        atualizar_agendamento(
                            agendamento_id,
                            tecnico_id=tecnico["id"],
                            tipo_consulta=setor,
                            status="confirmado",
                            data_agendamento=data_hora,
                            nome_paciente=dados_agendamento.get("nome_paciente"),
                        )
                    contexto_extra = (
                        f"AGENDAMENTO CONFIRMADO COM SUCESSO. "
                        f"Técnico: {tecnico['nome']} | Serviço: {setor} | "
                        f"Data: {data_str} | Horário: {horario_str}. "
                        "Informe os dados ao cliente, deseje um bom atendimento e encerre gentilmente."
                    )
                    # Limpa dados de agendamento da sessão
                    dados_agendamento = {}
                    sessao.pop("agendamento_id", None)
                else:
                    contexto_extra = (
                        "Não há técnicos disponíveis nesse horário. "
                        "Informe ao cliente e peça outra data ou horário."
                    )
                    novo_estado = EstadosConversa.AGUARDANDO_DATA
            else:
                contexto_extra = (
                    "Dados incompletos. Peça novamente a data e horário ao cliente."
                )
                novo_estado = EstadosConversa.AGENDAMENTO_PENDENTE

        # 5. Agenda em conversa livre ─────────────────────────────────────────
        if novo_estado in (EstadosConversa.CONVERSA_LIVRE, EstadosConversa.INICIAL):
            setor_livre = detectar_setor(texto_cliente)
            if setor_livre:
                hoje_livre = datetime.now().strftime("%Y-%m-%d")
                horarios_livre = buscar_horarios_disponiveis(setor_livre, hoje_livre, dias=7)
                contexto_extra = (
                    formatar_horarios_para_claude(horarios_livre)
                    + f"\nResponda a pergunta do cliente sobre disponibilidade de {setor_livre}."
                )

        # 6. Gerar resposta com Claude ─────────────────────────────────────────
        msg_para_claude = texto_cliente
        if contexto_extra:
            msg_para_claude += f"\n\n[SISTEMA: {contexto_extra}]"

        resposta = await gerar_resposta(
            numero_cliente,
            msg_para_claude,
            estado=novo_estado,
            historico=historico,
            dados_agendamento=dados_agendamento,
        )

        # 6. Atualizar sessão ──────────────────────────────────────────────────
        historico.append({"role": "user",      "content": texto_cliente})
        historico.append({"role": "assistant", "content": resposta})
        sessao["historico"]         = historico[-10:]
        sessao["estado"]            = novo_estado
        sessao["dados_agendamento"] = dados_agendamento
        salvar_sessao(numero_cliente, sessao)

        # 7. Persistir conversa ────────────────────────────────────────────────
        salvar_conversa(cliente_id, texto_cliente, resposta)

        # 8. Enviar resposta ao WhatsApp ───────────────────────────────────────
        await enviar_mensagem(numero_cliente, resposta)

        print(f"[OK] Estado={novo_estado} | Número={numero_cliente}")
        return JSONResponse({"status": "ok"})

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[ERRO] {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)
