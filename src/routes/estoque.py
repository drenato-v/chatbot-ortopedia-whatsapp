from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional

from services.auth_service import get_current_user, require_roles
from fastapi import HTTPException
from db.mysql import (
    listar_estoque_produtos,
    buscar_estoque_produto_por_id,
    criar_estoque_produto,
    atualizar_estoque_produto,
    registrar_movimento_estoque,
    buscar_movimentos_produto,
    excluir_movimento,
    excluir_historico_produto,
    criar_solicitacao_estoque,
    listar_solicitacoes_estoque,
    responder_solicitacao_estoque,
)

router = APIRouter(prefix="/painel/api/estoque", tags=["estoque"])

_gestor    = Depends(require_roles("estoquista"))
_qualquer  = Depends(get_current_user)
_solicitante = Depends(require_roles("atendente", "estoquista"))


# ── Schemas ───────────────────────────────────────────────────────────────────

class ProdutoBody(BaseModel):
    nome:              str
    categoria:         str
    unidade:           str = "un"
    quantidade_minima: int = 0
    descricao:         Optional[str] = None
    lado:              Optional[str] = None
    cor:               Optional[str] = None
    tamanho:           Optional[str] = None


class MovimentoBody(BaseModel):
    produto_id: int
    tipo:       str   # "entrada" | "saida" | "ajuste"
    quantidade: int
    motivo:     str


class SolicitacaoBody(BaseModel):
    produto_id: int
    tipo:       str   # "entrada" | "saida"
    quantidade: int
    motivo:     str


class RespostaBody(BaseModel):
    aprovado:   bool
    observacao: Optional[str] = None


# ── Produtos ──────────────────────────────────────────────────────────────────

@router.get("/produtos")
async def api_listar_produtos(_=_qualquer):
    produtos = listar_estoque_produtos()
    for p in produtos:
        if hasattr(p.get("created_at"), "isoformat"):
            p["created_at"] = p["created_at"].isoformat()
    return {"produtos": produtos}


@router.post("/produtos")
async def api_criar_produto(body: ProdutoBody, user=_gestor):
    pid = criar_estoque_produto(
        nome=body.nome,
        categoria=body.categoria,
        unidade=body.unidade,
        quantidade_minima=body.quantidade_minima,
        descricao=body.descricao,
        lado=body.lado,
        cor=body.cor,
        tamanho=body.tamanho,
    )
    return {"status": "ok", "id": pid}


@router.put("/produtos/{produto_id}")
async def api_editar_produto(produto_id: int, body: ProdutoBody, _=_gestor):
    atualizar_estoque_produto(
        produto_id,
        nome=body.nome,
        categoria=body.categoria,
        unidade=body.unidade,
        quantidade_minima=body.quantidade_minima,
        descricao=body.descricao,
        lado=body.lado or None,
        cor=body.cor or None,
        tamanho=body.tamanho or None,
    )
    return {"status": "ok"}


@router.delete("/produtos/{produto_id}")
async def api_desativar_produto(produto_id: int, _=_gestor):
    atualizar_estoque_produto(produto_id, ativo=False)
    return {"status": "ok"}


# ── Movimentos diretos (estoquista) ───────────────────────────────────────────

@router.post("/movimentos")
async def api_registrar_movimento(body: MovimentoBody, user=_gestor):
    if body.tipo not in ("entrada", "saida", "ajuste"):
        from fastapi import HTTPException
        raise HTTPException(400, "tipo deve ser entrada, saida ou ajuste")
    registrar_movimento_estoque(
        produto_id=body.produto_id,
        tipo=body.tipo,
        quantidade=body.quantidade,
        usuario_id=user["id"],
        usuario_nome=user["nome"],
        motivo=body.motivo,
    )
    return {"status": "ok"}


@router.get("/movimentos/{produto_id}")
async def api_historico_movimentos(produto_id: int, _=_qualquer):
    return {"movimentos": buscar_movimentos_produto(produto_id)}


@router.delete("/movimentos/item/{movimento_id}")
async def api_excluir_movimento(movimento_id: int, _=_gestor):
    if not excluir_movimento(movimento_id):
        raise HTTPException(404, "Movimentação não encontrada.")
    return {"status": "ok"}


@router.delete("/movimentos/produto/{produto_id}")
async def api_excluir_historico(produto_id: int, _=_gestor):
    total = excluir_historico_produto(produto_id)
    return {"status": "ok", "removidos": total}


# ── Solicitações (atendente solicita, estoquista responde) ────────────────────

@router.get("/solicitacoes")
async def api_listar_solicitacoes(status: str = None, _=_qualquer):
    return {"solicitacoes": listar_solicitacoes_estoque(status_filtro=status)}


@router.post("/solicitacoes")
async def api_criar_solicitacao(body: SolicitacaoBody, user=_solicitante):
    sid = criar_solicitacao_estoque(
        produto_id=body.produto_id,
        tipo=body.tipo,
        quantidade=body.quantidade,
        motivo=body.motivo,
        solicitante_id=user["id"],
        solicitante_nome=user["nome"],
    )
    return {"status": "ok", "id": sid}


@router.post("/solicitacoes/{solicitacao_id}/responder")
async def api_responder_solicitacao(solicitacao_id: int, body: RespostaBody, user=_gestor):
    sol = responder_solicitacao_estoque(
        solicitacao_id=solicitacao_id,
        aprovado=body.aprovado,
        aprovador_id=user["id"],
        aprovador_nome=user["nome"],
        observacao=body.observacao,
    )
    if sol is None:
        from fastapi import HTTPException
        raise HTTPException(404, "Solicitação não encontrada ou já respondida.")
    return {"status": "ok"}
