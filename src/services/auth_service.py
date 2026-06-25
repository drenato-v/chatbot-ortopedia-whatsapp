import os
import bcrypt as _bcrypt
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, Request, status
from jose import JWTError, jwt

# Nome do cookie HttpOnly que carrega o JWT em toda requisição autenticada
COOKIE_NAME = "access_token"

# Lida com o segredo de assinatura do JWT — gerado com `openssl rand -hex 32` em produção
SECRET_KEY = os.getenv("SECRET_KEY", "troque-em-producao-use-openssl-rand-hex-32")
ALGORITHM  = "HS256"
EXPIRE_H   = 8  # Token expira em 8 horas (equivalente a uma jornada de trabalho)


def hash_senha(senha: str) -> str:
    """Gera hash bcrypt da senha em texto puro. Nunca armazenar senha sem passar por aqui."""
    return _bcrypt.hashpw(senha.encode(), _bcrypt.gensalt()).decode()


def verificar_senha(senha: str, hash_armazenado: str) -> bool:
    """Compara senha em texto puro com o hash bcrypt armazenado."""
    return _bcrypt.checkpw(senha.encode(), hash_armazenado.encode())


def criar_token(user_id: int, role: str, nome: str,
                especialidade: Optional[str] = None,
                tecnico_id: Optional[int] = None) -> str:
    payload = {
        "sub":           str(user_id),
        "role":          role,
        "nome":          nome,
        "especialidade": especialidade,
        "tecnico_id":    tecnico_id,
        "exp":           datetime.now(timezone.utc) + timedelta(hours=EXPIRE_H),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _decodificar_token(token: str) -> Optional[dict]:
    """Decodifica e valida o JWT. Retorna None se inválido, expirado ou mal-formado."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def get_current_user(request: Request) -> dict:
    """
    Dependência FastAPI: extrai o usuário autenticado a partir do cookie JWT.

    Levanta 401 se o cookie estiver ausente ou o token for inválido/expirado.
    Usada diretamente nas rotas que precisam saber quem é o usuário, mas sem
    restrição de role (qualquer usuário autenticado pode acessar).
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não autenticado",
        )
    payload = _decodificar_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessão expirada. Faça login novamente.",
        )
    return {
        "id":            int(payload["sub"]),
        "role":          payload["role"],
        "nome":          payload["nome"],
        "especialidade": payload.get("especialidade"),
        "tecnico_id":    payload.get("tecnico_id"),
    }


def require_roles(*roles: str):
    """
    Fábrica de dependências: retorna um Depends que só permite os roles informados.

    Admin sempre tem acesso, independente dos roles listados — evita precisar
    incluir 'admin' em toda chamada.

    Uso: Depends(require_roles("atendente", "estoquista"))
    """
    def _verificar(request: Request) -> dict:
        user = get_current_user(request)
        # Admin tem acesso irrestrito a todas as rotas protegidas
        if user["role"] == "admin":
            return user
        if user["role"] not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Seu perfil não tem permissão para esta ação.",
            )
        return user
    return _verificar
