import redis
import os

client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    decode_responses=True
)

def salvar_sessao(numero: str, dados: str, ttl: int = 3600):
    client.setex(numero, ttl, dados)

def buscar_sessao(numero: str):
    return client.get(numero)