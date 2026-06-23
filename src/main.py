# Carrega variáveis de ambiente do arquivo .env antes de qualquer import
import os
from dotenv import load_dotenv
load_dotenv(override=True)

# Framework web assíncrono
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse

# Roteadores de cada módulo da aplicação
from routes.webhook import router as webhook_router          # Recebe mensagens do WhatsApp
from routes.admin import router as admin_router              # Gerencia FAQ via API
from routes.painel import router as painel_router            # Painel interno das atendentes
from routes.disponibilidade import router as disponibilidade_router  # Configura agenda dos técnicos

# Instância principal da aplicação FastAPI
app = FastAPI(title="Chatbot Ortopedia", docs_url="/docs")

# Registra os roteadores com seus prefixos e grupos de tags
app.include_router(webhook_router)
app.include_router(admin_router)
app.include_router(painel_router)
app.include_router(disponibilidade_router)

# Diretório base para localizar arquivos estáticos
_BASE = os.path.dirname(__file__)


@app.get("/", include_in_schema=False)
def home():
    """Endpoint de health check — confirma que o servidor está rodando."""
    return {"status": "Servidor rodando"}


@app.get("/painel", include_in_schema=False)
def painel_ui():
    """Serve o painel HTML das atendentes. Acesso apenas pela rede local da clínica."""
    return FileResponse(os.path.join(_BASE, "static", "painel.HTML"))


@app.get("/privacidade", include_in_schema=False)
def privacidade():
    """
    Página de política de privacidade exigida pela Meta para aprovação do app
    no WhatsApp Business API. URL deve ser informada no painel da Meta.
    """
    return HTMLResponse(content="""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Política de Privacidade — Ortopedia Geral</title>
  <style>
    body { font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #333; line-height: 1.7; }
    h1 { color: #1557a8; }
    h2 { color: #1557a8; margin-top: 30px; }
  </style>
</head>
<body>
  <h1>Política de Privacidade</h1>
  <p><strong>Última atualização:</strong> junho de 2026</p>

  <p>A <strong>Ortopedia Geral</strong> respeita a sua privacidade. Esta política descreve como coletamos e usamos suas informações ao interagir com nosso atendimento via WhatsApp.</p>

  <h2>1. Dados coletados</h2>
  <p>Coletamos apenas o número de telefone e as mensagens trocadas durante o atendimento, exclusivamente para fins de agendamento e suporte.</p>

  <h2>2. Uso dos dados</h2>
  <p>Os dados são utilizados para:</p>
  <ul>
    <li>Realizar e confirmar agendamentos</li>
    <li>Responder dúvidas sobre nossos serviços</li>
    <li>Melhorar a qualidade do atendimento</li>
  </ul>

  <h2>3. Compartilhamento</h2>
  <p>Não compartilhamos suas informações com terceiros, exceto quando exigido por lei.</p>

  <h2>4. Armazenamento</h2>
  <p>Os dados são armazenados de forma segura e mantidos apenas pelo tempo necessário para a prestação do serviço.</p>

  <h2>5. Seus direitos</h2>
  <p>Você pode solicitar a exclusão dos seus dados a qualquer momento pelo próprio WhatsApp ou pelo telefone <strong>(17) 99793-1926</strong>.</p>

  <h2>6. Contato</h2>
  <p>Dúvidas sobre esta política: <strong>(17) 99793-1926</strong><br>
  Rua General Glicério, 3841 — São José do Rio Preto, SP</p>
</body>
</html>
""")
