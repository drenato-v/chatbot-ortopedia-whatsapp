# Ferramentas de roteamento e modelos de dados do FastAPI/Pydantic
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

# Funções de banco de dados para técnicos e agendamentos
from db.mysql import (
    listar_tecnicos,
    buscar_agendamentos_por_data,
    buscar_agendamentos_pendentes,
    atualizar_status_agendamento,
    criar_agendamento_manual,
    atualizar_agendamento,
    buscar_agendamento_por_id,
)

# Serviços de agenda: visualização, bloqueio e liberação de slots
from services.tecnico_service import (
    buscar_agenda_dia,
    toggle_disponibilidade,
    marcar_hora_como_ocupada,
    liberar_hora,
)

# Envio de notificações ao cliente via WhatsApp
from services.whatsapp import enviar_mensagem

# Painel interno das atendentes.
# Sem autenticação por decisão do time: roda só na máquina
# da clínica (localhost). Não expor na internet sem adicionar login.
router = APIRouter(prefix="/painel", tags=["painel"])


# ── Modelos de entrada (validação automática pelo FastAPI) ────────────────────

class ToggleHoraBody(BaseModel):
    """Dados para bloquear ou liberar um slot na agenda de um técnico."""
    tecnico_id: int
    data: str   # formato YYYY-MM-DD
    hora: int   # hora inteira (ex: 9 para 09:00)


class AgendamentoManualBody(BaseModel):
    """Dados para criar um agendamento diretamente pelo painel (sem passar pelo bot)."""
    tecnico_id:    int
    data:          str
    hora:          int
    tipo_consulta: str
    nome_paciente: str
    observacoes:   Optional[str] = None
    tecnico_id_2:  Optional[int] = None  # segundo técnico (atendimento compartilhado)


class AgendamentoEditBody(BaseModel):
    """
    Dados para editar um agendamento existente.

    Campos opcionais foram adicionados progressivamente para suportar
    edição de técnico principal, horário e telefone pelo painel.
    O campo 'hora' (inteiro) representa a hora ANTIGA para liberar o slot;
    'horario_new' representa o novo valor a ser salvo.
    """
    nome_paciente:     str
    tipo_consulta:     str
    observacoes:       Optional[str] = None
    telefone_paciente: Optional[str] = None
    horario_new:       Optional[str] = None  # novo horário ex: "14:00"
    tecnico_id_old:    Optional[int] = None  # técnico principal antes da edição
    tecnico_id_new:    Optional[int] = None  # técnico principal após a edição
    tecnico_id_2_old:  Optional[int] = None
    tecnico_id_2_new:  Optional[int] = None
    data:              str
    hora:              int  # hora antiga (inteiro) para liberar o slot correto


class ConfirmarBody(BaseModel):
    """Permite que a atendente troque o técnico antes de confirmar o agendamento."""
    tecnico_id: Optional[int] = None


# ── Endpoints de técnicos ─────────────────────────────────────────────────────

@router.get("/api/tecnicos")
async def api_listar_tecnicos():
    """Lista todos os técnicos ativos, ordenados por setor e nome."""
    return {"tecnicos": listar_tecnicos()}


# ── Endpoints de disponibilidade ──────────────────────────────────────────────

@router.get("/api/disponibilidade")
async def api_buscar_disponibilidade(tecnico_id: int, data: str):
    """Retorna a agenda completa de um técnico para uma data (slot a slot)."""
    return {"agenda": buscar_agenda_dia(tecnico_id, data)}


@router.post("/api/disponibilidade/toggle")
async def api_toggle_disponibilidade(body: ToggleHoraBody):
    """Alterna um slot entre disponível e bloqueado. Retorna o novo estado."""
    novo_estado = toggle_disponibilidade(body.tecnico_id, body.data, body.hora)
    return {"disponivel": novo_estado}


@router.post("/api/disponibilidade/liberar")
async def api_liberar_hora(body: ToggleHoraBody):
    """Força a liberação de um slot bloqueado (usado ao cancelar ou recusar agendamentos)."""
    liberar_hora(body.tecnico_id, body.data, body.hora)
    return {"disponivel": True}


# ── Endpoints de agendamentos ─────────────────────────────────────────────────

@router.get("/api/agendamentos")
async def api_listar_agendamentos(data: str):
    """Lista agendamentos confirmados/pendentes de uma data específica (aba Agendamentos)."""
    return {"agendamentos": buscar_agendamentos_por_data(data)}


@router.get("/api/agendamentos/pendentes")
async def api_listar_agendamentos_pendentes():
    """Lista todos os agendamentos aguardando aprovação (aba Pendentes)."""
    return {"agendamentos": buscar_agendamentos_pendentes()}


@router.post("/api/agendamentos/{agendamento_id}/confirmar")
async def api_confirmar_agendamento(agendamento_id: int, body: ConfirmarBody = None):
    """
    Confirma um agendamento pendente e notifica o cliente via WhatsApp.

    Se a atendente trocou o técnico no dropdown antes de confirmar,
    libera o slot do técnico antigo e ocupa o slot do novo antes de confirmar.
    """
    ag = buscar_agendamento_por_id(agendamento_id)

    # Troca de técnico solicitada pela atendente
    if body and body.tecnico_id is not None and ag and body.tecnico_id != ag.get("tecnico_id"):
        old_tecnico_id = ag.get("tecnico_id")
        if ag.get("data_agendamento") and ag.get("horario"):
            data_str = ag["data_agendamento"].strftime("%Y-%m-%d")
            hora_int = int(ag["horario"].split(":")[0])
            if old_tecnico_id:
                liberar_hora(old_tecnico_id, data_str, hora_int)      # libera slot antigo
            marcar_hora_como_ocupada(body.tecnico_id, data_str, hora_int)  # ocupa slot novo
        atualizar_agendamento(agendamento_id, tecnico_id=body.tecnico_id)
        # Recarrega o registro para que o nome do técnico na mensagem esteja correto
        ag = buscar_agendamento_por_id(agendamento_id)

    atualizar_status_agendamento(agendamento_id, "confirmado")

    # Envia confirmação ao paciente via WhatsApp
    if ag and ag.get("numero_whatsapp"):
        data_fmt = ag["data_agendamento"].strftime("%d/%m/%Y") if ag.get("data_agendamento") else "—"
        horario  = ag.get("horario") or "—"
        servico  = ag.get("tipo_consulta") or "—"
        tecnico  = ag.get("tecnico_nome") or "nossa equipe"
        paciente = ag.get("nome_paciente") or "paciente"
        msg = (
            f"Olá, {paciente}! Seu agendamento na Ortopedia Geral foi *confirmado*!\n\n"
            f"📅 Data: {data_fmt}\n"
            f"🕐 Horário: {horario}\n"
            f"🏥 Serviço: {servico}\n"
            f"👤 Técnico: {tecnico}\n\n"
            f"Aguardamos você! Qualquer dúvida: (17) 99793-1926"
        )
        await enviar_mensagem(ag["numero_whatsapp"], msg)

    return {"status": "confirmado"}


@router.post("/api/agendamentos/{agendamento_id}/cancelar")
async def api_cancelar_agendamento(agendamento_id: int):
    """
    Cancela (recusa) um agendamento e libera os slots dos técnicos envolvidos.
    Notifica o cliente sobre a recusa via WhatsApp.
    """
    ag = buscar_agendamento_por_id(agendamento_id)
    atualizar_status_agendamento(agendamento_id, "cancelado")

    # Libera os slots bloqueados pelos técnicos principal e secundário
    if ag and ag.get("data_agendamento") and ag.get("horario"):
        data = ag["data_agendamento"].strftime("%Y-%m-%d")
        hora = int(ag["horario"].split(":")[0])
        if ag.get("tecnico_id"):
            liberar_hora(ag["tecnico_id"], data, hora)
        if ag.get("tecnico_id_2"):
            liberar_hora(ag["tecnico_id_2"], data, hora)

    # Notifica o paciente sobre a recusa
    if ag and ag.get("numero_whatsapp"):
        paciente = ag.get("nome_paciente") or "paciente"
        msg = (
            f"Olá, {paciente}. Infelizmente não foi possível confirmar sua solicitação "
            f"de agendamento na Ortopedia Geral.\n\n"
            f"Para reagendar ou mais informações: (17) 99793-1926"
        )
        await enviar_mensagem(ag["numero_whatsapp"], msg)

    return {"status": "cancelado"}


@router.post("/api/agendamentos/manual")
async def api_criar_agendamento_manual(body: AgendamentoManualBody):
    """
    Cria um agendamento diretamente pelo painel (sem passar pelo bot do WhatsApp).
    Usado pelas atendentes para registrar agendamentos feitos por telefone ou presencialmente.
    """
    data_hora = datetime.strptime(f"{body.data} {body.hora:02d}:00", "%Y-%m-%d %H:%M")
    horario_str = f"{body.hora:02d}:00"

    agendamento_id = criar_agendamento_manual(
        tecnico_id=body.tecnico_id,
        data_agendamento=data_hora,
        horario=horario_str,
        tipo_consulta=body.tipo_consulta,
        nome_paciente=body.nome_paciente,
        observacoes=body.observacoes,
        tecnico_id_2=body.tecnico_id_2,
    )

    # Bloqueia os slots dos técnicos envolvidos
    marcar_hora_como_ocupada(body.tecnico_id, body.data, body.hora)
    if body.tecnico_id_2:
        marcar_hora_como_ocupada(body.tecnico_id_2, body.data, body.hora)

    return {"status": "ok", "agendamento_id": agendamento_id}


@router.put("/api/agendamentos/{agendamento_id}")
async def api_editar_agendamento(agendamento_id: int, body: AgendamentoEditBody):
    """
    Edita campos de um agendamento existente.

    Gerencia automaticamente a troca de slots quando técnico ou horário mudam:
    - Se o técnico principal mudou: libera slot antigo, ocupa slot novo
    - Se só o horário mudou (mesmo técnico): libera hora antiga, ocupa hora nova
    - O mesmo tratamento é aplicado ao segundo técnico
    """
    hora_old = body.hora
    hora_new = int(body.horario_new.split(':')[0]) if body.horario_new else hora_old

    # Monta os campos a atualizar no banco
    update_kwargs = dict(
        nome_paciente=body.nome_paciente,
        tipo_consulta=body.tipo_consulta,
        observacoes=body.observacoes,
        tecnico_id_2=body.tecnico_id_2_new,
    )
    # Campos opcionais — só atualizados se enviados
    if body.telefone_paciente is not None:
        update_kwargs["telefone_paciente"] = body.telefone_paciente
    if body.horario_new:
        update_kwargs["horario"] = body.horario_new
    if body.tecnico_id_new is not None:
        update_kwargs["tecnico_id"] = body.tecnico_id_new

    atualizar_agendamento(agendamento_id, **update_kwargs)

    # ── Gerenciamento de slots do técnico principal ───────────────────────────
    old_tec = body.tecnico_id_old
    new_tec = body.tecnico_id_new if body.tecnico_id_new is not None else old_tec
    if old_tec != new_tec or hora_old != hora_new:
        if old_tec:
            liberar_hora(old_tec, body.data, hora_old)
        if new_tec:
            marcar_hora_como_ocupada(new_tec, body.data, hora_new)

    # ── Gerenciamento de slots do segundo técnico ─────────────────────────────
    if body.tecnico_id_2_old != body.tecnico_id_2_new:
        # Técnico secundário trocado
        if body.tecnico_id_2_old:
            liberar_hora(body.tecnico_id_2_old, body.data, hora_old)
        if body.tecnico_id_2_new:
            marcar_hora_como_ocupada(body.tecnico_id_2_new, body.data, hora_new)
    elif hora_old != hora_new and body.tecnico_id_2_new:
        # Mesmo técnico secundário, mas hora mudou
        liberar_hora(body.tecnico_id_2_new, body.data, hora_old)
        marcar_hora_como_ocupada(body.tecnico_id_2_new, body.data, hora_new)

    return {"status": "ok"}
