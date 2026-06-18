# Cliente Redis
import redis
# Variáveis de ambiente
import os

# Conexão compartilhada
# usada por toda aplicação
client = redis.Redis(
    host=os.getenv(
        "REDIS_HOST",
        "localhost"
    ),

    port=int(
        os.getenv(
            "REDIS_PORT",
            6379
        )
    ),

    # Converte bytes → string
    decode_responses=True
)

def salvar_sessao(
    numero: str,
    dados: str,
    ttl: int = 3600
):
    """
    Salva dados temporários.

    TTL padrão:
    1 hora.
    """

    client.setex(

        numero,
        ttl,
        dados
    )

def buscar_sessao(
    numero: str
):
    """
    Recupera sessão.

    Retorna None
    se não existir.
    """

    return client.get(
        numero
    )