# Ferramentas de roteamento e tratamento de erros do FastAPI
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# Serviços de configuração e consulta de disponibilidade de técnicos
from services.disponibilidade_service import configurar_disponibilidade, obter_disponibilidade

# Acesso direto ao banco para listar técnicos
from db.mysql import get_connection

router = APIRouter(prefix="/disponibilidade", tags=["disponibilidade"])


class DisponibilidadeInput(BaseModel):
    """Dados para configurar a agenda de um técnico em uma data."""
    tecnico_id: int
    data:       str        # formato YYYY-MM-DD
    horas:      list[int]  # ex: [8, 9, 10, 14, 15] — horas que o técnico estará disponível


@router.post("/configurar")
async def configurar(dados: DisponibilidadeInput):
    """
    Substitui a agenda de disponibilidade de um técnico para uma data.
    Remove os registros anteriores e recria apenas as horas informadas.
    """
    try:
        configurar_disponibilidade(dados.tecnico_id, dados.data, dados.horas)
        return {"status": "sucesso"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tecnico/{tecnico_id}/{data}")
async def obter(tecnico_id: int, data: str):
    """Retorna os horários configurados para um técnico em uma data específica."""
    try:
        horarios = obter_disponibilidade(tecnico_id, data)
        return {"tecnico_id": tecnico_id, "data": data, "horarios": horarios}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tecnicos")
async def listar_tecnicos():
    """Lista todos os técnicos ativos com seus setores e modos de atendimento."""
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, nome, setor, modo_atendimento FROM tecnicos WHERE ativo = TRUE ORDER BY setor, nome"
        )
        return {"tecnicos": cursor.fetchall()}
    finally:
        cursor.close()
        conn.close()
