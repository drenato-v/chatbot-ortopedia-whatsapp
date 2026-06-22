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