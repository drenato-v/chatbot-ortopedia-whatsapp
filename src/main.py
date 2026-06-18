from fastapi import FastAPI
# Importa os grupos de rotas da aplicação.
# O alias evita conflito de nome entre os objetos router.
from routes.webhook import router as webhook_router
from routes.admin import router as admin_router

# Cria a instância principal da API.
# Esse objeto será executado pelo servidor ASGI (ex.: Uvicorn).
app = FastAPI()

# Registra as rotas responsáveis pela comunicação com o WhatsApp.
# Tudo que chegar nesses endpoints será tratado pelo módulo webhook.
app.include_router(webhook_router)

# Registra rotas administrativas
# (monitoramento, testes, gestão ou endpoints internos).
app.include_router(admin_router)

# Endpoint simples para verificar se a aplicação está ativa.
# Pode ser usado para teste local ou health check.
@app.get("/")
def home():

    # Retorna um JSON indicando que o servidor está operacional.
    return {
        "status": "Servidor rodando"
    }