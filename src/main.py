import os
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.responses import FileResponse
from routes.webhook import router as webhook_router
from routes.admin import router as admin_router
from routes.painel import router as painel_router
from routes.disponibilidade import router as disponibilidade_router

app = FastAPI(title="Chatbot Ortopedia", docs_url="/docs")

app.include_router(webhook_router)
app.include_router(admin_router)
app.include_router(painel_router)
app.include_router(disponibilidade_router)

_BASE = os.path.dirname(__file__)

@app.get("/", include_in_schema=False)
def home():
    return {"status": "Servidor rodando"}

@app.get("/painel", include_in_schema=False)
def painel_ui():
    return FileResponse(os.path.join(_BASE, "static", "painel.HTML"))
