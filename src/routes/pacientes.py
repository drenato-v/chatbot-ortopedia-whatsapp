from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional

from db.mysql import (
    buscar_pacientes,
    buscar_paciente_por_id,
    criar_paciente,
    atualizar_paciente,
    buscar_fichas_do_paciente,
    criar_ficha,
    atualizar_ficha,
    adicionar_historico,
    buscar_ficha_por_agendamento,
)
from services.auth_service import get_current_user, require_roles

router = APIRouter(tags=["pacientes"])

# Dependências reutilizáveis
_atendente       = Depends(require_roles("atendente"))
_atendente_ou_tecnico = Depends(require_roles("atendente", "tecnico"))


# ── Modelos de entrada ────────────────────────────────────────────────────────

class PacienteCreateBody(BaseModel):
    nome:               str
    tipo_servico:       str          # obrigatório para criar a ficha inicial
    telefone:           Optional[str] = None
    cpf:                Optional[str] = None
    data_nascimento:    Optional[str] = None
    endereco:           Optional[str] = None
    plano_saude:        Optional[str] = None
    medico_responsavel: Optional[str] = None


class PacienteUpdateBody(BaseModel):
    nome:               Optional[str] = None
    telefone:           Optional[str] = None
    cpf:                Optional[str] = None
    data_nascimento:    Optional[str] = None
    endereco:           Optional[str] = None
    plano_saude:        Optional[str] = None
    medico_responsavel: Optional[str] = None


class FichaCreateBody(BaseModel):
    tipo_servico: str


class HistoricoBody(BaseModel):
    etapa:            str
    descricao:        Optional[str] = None
    status_orcamento: Optional[str] = None  # em_analise | aprovado | rejeitado


# ── Endpoints de pacientes ────────────────────────────────────────────────────

@router.get("/pacientes")
def buscar(q: str = "", _=Depends(get_current_user)):
    """
    Busca pacientes por nome ou telefone.
    Query vazia retorna todos (limitado a 30 pelo banco).
    """
    return {"pacientes": buscar_pacientes(q.strip())}


@router.get("/pacientes/{paciente_id}")
def detalhe(paciente_id: int, _=Depends(get_current_user)):
    """Retorna os dados completos de um paciente."""
    pac = buscar_paciente_por_id(paciente_id)
    if not pac:
        raise HTTPException(status_code=404, detail="Paciente não encontrado.")
    return pac


@router.post("/pacientes", status_code=201)
def criar(body: PacienteCreateBody, current_user: dict = _atendente):
    """
    Cria um novo paciente presencial e abre automaticamente a primeira ficha.
    Usado quando o paciente vem sem agendamento prévio pelo WhatsApp.
    """
    paciente_id = criar_paciente(
        nome=body.nome,
        telefone=body.telefone,
        cpf=body.cpf or None,
        data_nascimento=body.data_nascimento or None,
        endereco=body.endereco or None,
        plano_saude=body.plano_saude or None,
        medico_responsavel=body.medico_responsavel or None,
        atendido_por_id=current_user["id"],
        atendido_por_nome=current_user["nome"],
    )

    # Cria a ficha imediatamente junto com o paciente
    ficha_id = criar_ficha(paciente_id, body.tipo_servico)

    # Primeira entrada no histórico: quem iniciou o atendimento
    adicionar_historico(
        ficha_id=ficha_id,
        etapa="Atendimento",
        usuario_id=current_user["id"],
        usuario_nome=current_user["nome"],
        descricao=f"Atendimento iniciado por {current_user['nome']}.",
    )
    return {"paciente_id": paciente_id, "ficha_id": ficha_id}


@router.put("/pacientes/{paciente_id}")
def atualizar(paciente_id: int, body: PacienteUpdateBody, _=_atendente):
    """
    Atualiza os dados cadastrais de um paciente existente.
    Usado pela atendente ao completar o cadastro de um paciente do WhatsApp
    que veio presencialmente pela primeira vez.
    """
    kwargs = {k: v for k, v in body.model_dump().items() if v is not None}
    if kwargs:
        atualizar_paciente(paciente_id, **kwargs)
    return {"ok": True}


# ── Endpoints de fichas ───────────────────────────────────────────────────────

@router.get("/pacientes/{paciente_id}/fichas")
def listar_fichas(paciente_id: int, _=Depends(get_current_user)):
    """Lista todas as fichas do paciente com o histórico completo de cada uma."""
    return {"fichas": buscar_fichas_do_paciente(paciente_id)}


@router.post("/pacientes/{paciente_id}/fichas", status_code=201)
def criar_ficha_manual(paciente_id: int, body: FichaCreateBody, current_user: dict = _atendente):
    """
    Abre uma nova ficha para um paciente já existente.
    Usado quando um paciente retorna para um novo serviço ou processo.
    """
    ficha_id = criar_ficha(paciente_id, body.tipo_servico)
    adicionar_historico(
        ficha_id=ficha_id,
        etapa="Atendimento",
        usuario_id=current_user["id"],
        usuario_nome=current_user["nome"],
    )
    return {"ficha_id": ficha_id}


# ── Endpoints de histórico ────────────────────────────────────────────────────

@router.post("/fichas/{ficha_id}/historico")
def registrar_etapa(ficha_id: int, body: HistoricoBody, current_user: dict = _atendente_ou_tecnico):
    """
    Registra uma nova etapa na ficha e atualiza a etapa atual.
    Admin, atendente e técnico podem registrar etapas.
    Cada registro é imutável — o histórico completo é sempre preservado.
    """
    adicionar_historico(
        ficha_id=ficha_id,
        etapa=body.etapa,
        usuario_id=current_user["id"],
        usuario_nome=current_user["nome"],
        descricao=body.descricao,
    )
    # Atualiza o snapshot da etapa atual na ficha para consultas rápidas
    atualizar_ficha(ficha_id, body.etapa, body.status_orcamento)
    return {"ok": True}
