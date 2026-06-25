from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from typing import Optional

from db.mysql import buscar_usuario_por_email, criar_usuario, listar_usuarios, atualizar_usuario
from services.auth_service import (
    COOKIE_NAME,
    criar_token,
    get_current_user,
    hash_senha,
    require_roles,
    verificar_senha,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    email: str
    senha: str


@router.post("/login")
def login(body: LoginBody, response: Response):
    """
    Autentica o usuário e define o cookie JWT HttpOnly na resposta.

    HttpOnly: o JavaScript do cliente não consegue ler o token (proteção contra XSS).
    SameSite=lax: bloqueia envio do cookie em requisições cross-site (mitiga CSRF).
    """
    user = buscar_usuario_por_email(body.email)

    # Mensagem genérica intencional — não revela se o e-mail existe no sistema
    # (evita user enumeration attack)
    if (
        not user
        or not user.get("ativo")
        or not verificar_senha(body.senha, user["password_hash"])
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais inválidas.",
        )

    token = criar_token(user["id"], user["role"], user["nome"],
                        user.get("especialidade"), user.get("tecnico_id"))

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,   # Inacessível ao JavaScript
        samesite="lax",  # Mitiga CSRF
        max_age=28800,   # 8 horas em segundos (EXPIRE_H × 3600)
    )
    return {"role": user["role"], "nome": user["nome"]}


@router.post("/logout")
def logout(response: Response):
    """Remove o cookie de sessão, encerrando a autenticação."""
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    """
    Retorna os dados do usuário autenticado (id, role, nome).

    Chamado pelo frontend no carregamento do painel para determinar o role
    e configurar quais abas e ações ficam visíveis.
    """
    return user


# ── Gerenciamento de usuários (somente admin) ─────────────────────────────────

# Dependência reutilizável que garante acesso exclusivo ao admin
_so_admin = Depends(require_roles())  # Sem roles extras: apenas admin passa


class UsuarioCreateBody(BaseModel):
    nome:          str
    email:         str
    senha:         str
    role:          str
    especialidade: Optional[str] = None
    tecnico_id:    Optional[int] = None


class UsuarioUpdateBody(BaseModel):
    nome:          Optional[str]  = None
    role:          Optional[str]  = None
    ativo:         Optional[bool] = None
    senha:         Optional[str]  = None
    especialidade: Optional[str]  = None
    tecnico_id:    Optional[int]  = None


@router.get("/usuarios")
def listar(user: dict = _so_admin):
    """Lista todos os usuários cadastrados. Somente admin."""
    # password_hash é excluído na query — nunca deve trafegar para o frontend
    return {"usuarios": listar_usuarios()}


@router.post("/usuarios", status_code=201)
def criar(body: UsuarioCreateBody, user: dict = _so_admin):
    """Cria um novo usuário do painel. Somente admin."""
    roles_validos = {"admin", "atendente", "estoquista", "tecnico"}
    if body.role not in roles_validos:
        raise HTTPException(status_code=400, detail="Role inválido.")

    # Verifica duplicidade antes de tentar inserir para retornar mensagem clara
    if buscar_usuario_por_email(body.email):
        raise HTTPException(status_code=409, detail="E-mail já cadastrado.")

    eh_tecnico = body.role == "tecnico"
    esp        = body.especialidade if eh_tecnico else None
    tec_id     = body.tecnico_id    if eh_tecnico else None
    novo_id = criar_usuario(body.nome, body.email, hash_senha(body.senha), body.role,
                            especialidade=esp, tecnico_id=tec_id)
    return {"id": novo_id}


@router.put("/usuarios/{usuario_id}")
def atualizar(usuario_id: int, body: UsuarioUpdateBody, user: dict = _so_admin):
    """
    Atualiza nome, role, status (ativo/inativo) ou senha de um usuário.
    Somente admin. Campos não enviados são ignorados.
    """
    # Admin não pode se desativar para evitar ficar sem acesso ao sistema
    if body.ativo is False and usuario_id == user["id"]:
        raise HTTPException(status_code=400, detail="Você não pode desativar sua própria conta.")

    kwargs = {}
    if body.nome  is not None: kwargs["nome"]          = body.nome
    if body.role  is not None: kwargs["role"]          = body.role
    if body.ativo is not None: kwargs["ativo"]         = body.ativo
    if body.senha is not None: kwargs["password_hash"] = hash_senha(body.senha)
    # especialidade e tecnico_id só fazem sentido para técnico; limpa para outros roles
    novo_role = body.role
    eh_tecnico = novo_role == "tecnico" if novo_role else None
    if body.especialidade is not None or (eh_tecnico is not None and not eh_tecnico):
        kwargs["especialidade"] = body.especialidade if eh_tecnico != False else None
    if body.tecnico_id is not None or (eh_tecnico is not None and not eh_tecnico):
        kwargs["tecnico_id"] = body.tecnico_id if eh_tecnico != False else None

    if kwargs:
        atualizar_usuario(usuario_id, **kwargs)
    return {"ok": True}
