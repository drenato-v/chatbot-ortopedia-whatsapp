from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from db.mysql import (
    listar_tecnicos,
    buscar_agendamentos_por_data,
    atualizar_status_agendamento,
    criar_agendamento_manual,
    atualizar_agendamento
)
from services.tecnico_service import (
    buscar_agenda_dia,
    toggle_disponibilidade,
    marcar_hora_como_ocupada,
    liberar_hora
)

# Painel interno das atendentes.
# Sem autenticação por decisão do time: roda só na máquina
# da clínica (localhost). Não expor isso na internet sem
# adicionar login antes.
router = APIRouter(
    prefix="/painel",
    tags=["painel"]
)


class ToggleHoraBody(BaseModel):
    tecnico_id: int
    data: str
    hora: int


class AgendamentoManualBody(BaseModel):
    tecnico_id: int
    data: str
    hora: int
    tipo_consulta: str
    nome_paciente: str
    observacoes: Optional[str] = None
    tecnico_id_2: Optional[int] = None


class AgendamentoEditBody(BaseModel):
    nome_paciente: str
    tipo_consulta: str
    observacoes: Optional[str] = None
    tecnico_id_2_old: Optional[int] = None
    tecnico_id_2_new: Optional[int] = None
    data: str
    hora: int


@router.get("/api/tecnicos")
async def api_listar_tecnicos():
    return {"tecnicos": listar_tecnicos()}


@router.get("/api/disponibilidade")
async def api_buscar_disponibilidade(tecnico_id: int, data: str):
    return {"agenda": buscar_agenda_dia(tecnico_id, data)}


@router.post("/api/disponibilidade/toggle")
async def api_toggle_disponibilidade(body: ToggleHoraBody):
    novo_estado = toggle_disponibilidade(body.tecnico_id, body.data, body.hora)
    return {"disponivel": novo_estado}


@router.post("/api/disponibilidade/liberar")
async def api_liberar_hora(body: ToggleHoraBody):
    liberar_hora(body.tecnico_id, body.data, body.hora)
    return {"disponivel": True}


@router.get("/api/agendamentos")
async def api_listar_agendamentos(data: str):
    return {"agendamentos": buscar_agendamentos_por_data(data)}


@router.post("/api/agendamentos/{agendamento_id}/confirmar")
async def api_confirmar_agendamento(agendamento_id: int):
    atualizar_status_agendamento(agendamento_id, "confirmado")
    return {"status": "confirmado"}


@router.post("/api/agendamentos/{agendamento_id}/cancelar")
async def api_cancelar_agendamento(agendamento_id: int):
    atualizar_status_agendamento(agendamento_id, "cancelado")
    return {"status": "cancelado"}


@router.post("/api/agendamentos/manual")
async def api_criar_agendamento_manual(body: AgendamentoManualBody):
    data_hora = datetime.strptime(
        f"{body.data} {body.hora:02d}:00", "%Y-%m-%d %H:%M"
    )
    horario_str = f"{body.hora:02d}:00"
    agendamento_id = criar_agendamento_manual(
        tecnico_id=body.tecnico_id,
        data_agendamento=data_hora,
        horario=horario_str,
        tipo_consulta=body.tipo_consulta,
        nome_paciente=body.nome_paciente,
        observacoes=body.observacoes,
        tecnico_id_2=body.tecnico_id_2
    )
    marcar_hora_como_ocupada(body.tecnico_id, body.data, body.hora)
    if body.tecnico_id_2:
        marcar_hora_como_ocupada(body.tecnico_id_2, body.data, body.hora)
    return {"status": "ok", "agendamento_id": agendamento_id}


@router.put("/api/agendamentos/{agendamento_id}")
async def api_editar_agendamento(agendamento_id: int, body: AgendamentoEditBody):
    atualizar_agendamento(
        agendamento_id,
        nome_paciente=body.nome_paciente,
        tipo_consulta=body.tipo_consulta,
        observacoes=body.observacoes,
        tecnico_id_2=body.tecnico_id_2_new
    )
    # Atualiza slot do segundo técnico se mudou
    if body.tecnico_id_2_old != body.tecnico_id_2_new:
        if body.tecnico_id_2_old:
            liberar_hora(body.tecnico_id_2_old, body.data, body.hora)
        if body.tecnico_id_2_new:
            marcar_hora_como_ocupada(body.tecnico_id_2_new, body.data, body.hora)
    return {"status": "ok"}