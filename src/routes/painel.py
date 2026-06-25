# Ferramentas de roteamento e modelos de dados do FastAPI/Pydantic
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from services.auth_service import get_current_user, require_roles

# Funções de banco de dados para técnicos e agendamentos
from db.mysql import (
    listar_tecnicos,
    buscar_agendamentos_por_data,
    buscar_agendamentos_pendentes,
    buscar_agendamentos_por_nome,
    atualizar_status_agendamento,
    criar_agendamento_manual,
    atualizar_agendamento,
    buscar_agendamento_por_id,
    buscar_paciente_por_cliente_id,
    criar_paciente,
    criar_ficha,
    buscar_ficha_por_agendamento,
    adicionar_historico,
    buscar_notificacoes,
    marcar_notificacao_lida,
    marcar_todas_notificacoes_lidas,
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

# Dependência reutilizável para rotas que exigem atendente ou admin
_atendente = Depends(require_roles("atendente"))


@router.get("/api/tecnicos")
async def api_listar_tecnicos(_=Depends(get_current_user)):
    """Lista todos os técnicos ativos. Qualquer usuário autenticado pode consultar."""
    return {"tecnicos": listar_tecnicos()}


# ── Endpoints de disponibilidade ──────────────────────────────────────────────

@router.get("/api/disponibilidade")
async def api_buscar_disponibilidade(tecnico_id: int, data: str, _=Depends(get_current_user)):
    """Retorna a agenda completa de um técnico para uma data. Leitura para todos os perfis."""
    return {"agenda": buscar_agenda_dia(tecnico_id, data)}


@router.post("/api/disponibilidade/toggle")
async def api_toggle_disponibilidade(body: ToggleHoraBody, _=_atendente):
    """Alterna um slot entre disponível e bloqueado. Apenas admin e atendente."""
    novo_estado = toggle_disponibilidade(body.tecnico_id, body.data, body.hora)
    return {"disponivel": novo_estado}


@router.post("/api/disponibilidade/liberar")
async def api_liberar_hora(body: ToggleHoraBody, _=_atendente):
    """Força a liberação de um slot bloqueado. Apenas admin e atendente."""
    liberar_hora(body.tecnico_id, body.data, body.hora)
    return {"disponivel": True}


# ── Endpoints de agendamentos ─────────────────────────────────────────────────

@router.get("/api/agendamentos")
async def api_listar_agendamentos(data: str, tecnico_id: int = None, _=Depends(get_current_user)):
    """Lista agendamentos de uma data. Filtro opcional por técnico."""
    return {"agendamentos": buscar_agendamentos_por_data(data, tecnico_id=tecnico_id)}


@router.get("/api/agendamentos/pendentes")
async def api_listar_agendamentos_pendentes(_=_atendente):
    """Lista solicitações pendentes. Apenas admin e atendente podem gerenciar pendentes."""
    return {"agendamentos": buscar_agendamentos_pendentes()}


@router.get("/api/agendamentos/busca")
async def api_buscar_agendamentos_por_nome(q: str = "", _=Depends(get_current_user)):
    """Busca agendamentos por nome do paciente, independente de data."""
    if not q or len(q.strip()) < 1:
        return {"agendamentos": []}
    return {"agendamentos": buscar_agendamentos_por_nome(q.strip())}


@router.post("/api/agendamentos/{agendamento_id}/confirmar")
async def api_confirmar_agendamento(agendamento_id: int, body: ConfirmarBody = None, current_user: dict = _atendente):
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

    # Envia confirmação ao paciente via WhatsApp imediatamente após confirmar.
    # Feito ANTES da criação de paciente/ficha para garantir que o cliente seja
    # notificado mesmo se houver falha na criação do registro clínico.
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

    # Auto-cria paciente e ficha após notificar.
    # Envolvido em try/except para que uma falha aqui não impeça a notificação
    # nem reverta a confirmação já registrada no banco.
    if ag and ag.get("cliente_id"):
        try:
            pac = buscar_paciente_por_cliente_id(ag["cliente_id"])
            if not pac:
                paciente_id = criar_paciente(
                    nome=ag.get("nome_paciente") or "Paciente",
                    telefone=ag.get("numero_whatsapp"),
                    cliente_id=ag["cliente_id"],
                    atendido_por_id=current_user["id"],
                    atendido_por_nome=current_user["nome"],
                )
            else:
                paciente_id = pac["id"]

            if not buscar_ficha_por_agendamento(agendamento_id):
                ficha_id = criar_ficha(
                    paciente_id=paciente_id,
                    tipo_servico=ag.get("tipo_consulta") or "Outras",
                    agendamento_id=agendamento_id,
                )
                adicionar_historico(
                    ficha_id=ficha_id,
                    etapa="Atendimento",
                    usuario_id=current_user["id"],
                    usuario_nome=current_user["nome"],
                    descricao=f"Agendamento confirmado por {current_user['nome']}.",
                )
        except Exception as exc:
            print(f"[WARN] confirmar {agendamento_id}: falha ao criar paciente/ficha — {exc}")

    return {"status": "confirmado"}


@router.post("/api/agendamentos/{agendamento_id}/cancelar")
async def api_cancelar_agendamento(agendamento_id: int, _=_atendente):
    """
    Cancela (recusa) um agendamento e libera os slots dos técnicos envolvidos.
    Notifica o cliente sobre a recusa via WhatsApp.
    """
    ag = buscar_agendamento_por_id(agendamento_id)
    status_anterior = ag.get("status") if ag else None
    atualizar_status_agendamento(agendamento_id, "cancelado")

    # Libera os slots bloqueados pelos técnicos principal e secundário
    if ag and ag.get("data_agendamento") and ag.get("horario"):
        data = ag["data_agendamento"].strftime("%Y-%m-%d")
        hora = int(ag["horario"].split(":")[0])
        if ag.get("tecnico_id"):
            liberar_hora(ag["tecnico_id"], data, hora)
        if ag.get("tecnico_id_2"):
            liberar_hora(ag["tecnico_id_2"], data, hora)

    # Mensagem diferenciada: pendente = solicitação recusada; confirmado = cancelamento
    if ag and ag.get("numero_whatsapp"):
        paciente = ag.get("nome_paciente") or "paciente"
        if status_anterior == "confirmado":
            msg = (
                f"Olá, {paciente}. Seu agendamento na Ortopedia Geral foi cancelado.\n\n"
                f"Para reagendar ou mais informações: (17) 99793-1926"
            )
        else:
            msg = (
                f"Olá, {paciente}. Infelizmente não foi possível confirmar sua solicitação "
                f"de agendamento na Ortopedia Geral.\n\n"
                f"Para reagendar ou mais informações: (17) 99793-1926"
            )
        await enviar_mensagem(ag["numero_whatsapp"], msg)

    return {"status": "cancelado"}


@router.get("/api/notificacoes")
async def api_listar_notificacoes(nao_lidas: bool = False, _=Depends(get_current_user)):
    """Retorna notificações do painel. Filtra apenas não lidas se nao_lidas=true."""
    items = buscar_notificacoes(apenas_nao_lidas=nao_lidas)
    # Serializa datetimes para ISO string
    for n in items:
        if hasattr(n.get("created_at"), "isoformat"):
            n["created_at"] = n["created_at"].isoformat()
    return {"notificacoes": items, "total_nao_lidas": sum(1 for n in items if not n["lida"])}


@router.post("/api/notificacoes/{notificacao_id}/lida")
async def api_marcar_lida(notificacao_id: int, _=Depends(get_current_user)):
    """Marca uma notificação específica como lida."""
    marcar_notificacao_lida(notificacao_id)
    return {"status": "ok"}


@router.post("/api/notificacoes/todas-lidas")
async def api_marcar_todas_lidas(_=Depends(get_current_user)):
    """Marca todas as notificações como lidas."""
    marcar_todas_notificacoes_lidas()
    return {"status": "ok"}


@router.post("/api/agendamentos/manual")
async def api_criar_agendamento_manual(body: AgendamentoManualBody, _=_atendente):
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
async def api_editar_agendamento(agendamento_id: int, body: AgendamentoEditBody, _=_atendente):
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
