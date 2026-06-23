# Biblioteca oficial do Redis para Python
import redis
# Leitura das configurações de conexão via variáveis de ambiente
import os

# Conexão única compartilhada por toda a aplicação (padrão singleton).
# decode_responses=True converte automaticamente bytes → string em todas as leituras,
# evitando chamadas manuais a .decode() no restante do código.
client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    decode_responses=True,
)
