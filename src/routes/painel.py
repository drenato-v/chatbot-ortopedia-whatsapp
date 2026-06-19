from fastapi import APIRouter
from pydantic import BaseModel

from db.mysql import (
    listar_tecnicos,
    buscar_agendamentos_por_data,
    atualizar_status_agendamento
)
from services.tecnico_service import (
    buscar_agenda_dia,
    toggle_disponibilidade
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
    data: str  # formato YYYY-MM-DD
    hora: int  # 8 a 16


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