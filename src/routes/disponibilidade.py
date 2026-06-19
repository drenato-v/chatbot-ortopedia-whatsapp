from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services.disponibilidade_service import configurar_disponibilidade, obter_disponibilidade
from db.mysql import get_connection

router = APIRouter(prefix="/disponibilidade", tags=["disponibilidade"])

class DisponibilidadeInput(BaseModel):
    tecnico_id: int
    data: str
    horas: list[int]

@router.post("/configurar")
async def configurar(dados: DisponibilidadeInput):
    try:
        configurar_disponibilidade(dados.tecnico_id, dados.data, dados.horas)
        return {"status": "sucesso"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/tecnico/{tecnico_id}/{data}")
async def obter(tecnico_id: int, data: str):
    try:
        horarios = obter_disponibilidade(tecnico_id, data)
        return {"tecnico_id": tecnico_id, "data": data, "horarios": horarios}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/tecnicos")
async def listar_tecnicos():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT id, nome, setor, modo_atendimento 
            FROM tecnicos 
            WHERE ativo = TRUE 
            ORDER BY setor, nome
        """)
        return {"tecnicos": cursor.fetchall()}
    finally:
        cursor.close()
        conn.close()