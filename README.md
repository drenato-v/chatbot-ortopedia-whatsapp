*Chatbot Ortopedia WhatsApp*

Sistema de atendimento automatizado desenvolvido para centralizar o contato entre clientes e a operação da Ortopedia Geral utilizando integração com WhatsApp, inteligência artificial e serviços internos.

Sobre o projeto

O chatbot-ortopedia-whatsapp foi desenvolvido com o objetivo de automatizar e organizar o atendimento ao cliente, permitindo responder dúvidas frequentes, auxiliar em agendamentos e manter uma comunicação contínua através do WhatsApp.

A aplicação conecta serviços de IA com canais de atendimento para criar uma experiência mais rápida e escalável, reduzindo etapas manuais no processo de comunicação.

Além do atendimento automatizado, o projeto foi utilizado como ambiente de aprendizado para aprofundar conceitos de arquitetura de APIs, integração entre serviços e construção de sistemas orientados a comunicação entre modelos de IA e usuários finais.

⸻

Funcionalidades

* Atendimento automatizado ao cliente via WhatsApp;
* Respostas para perguntas frequentes (FAQ);
* Apoio ao processo de agendamento;
* Integração com serviços de inteligência artificial;
* Gerenciamento de contexto e mensagens;
* Persistência e recuperação de dados.

⸻

Tecnologias utilizadas

Backend

* Python
* FastAPI

Integrações e Serviços

* Claude API
* Meta / WhatsApp API
* HTTPX

Persistência

* MySQL
* Redis

Utilitários

* JSON

Ambiente de desenvolvimento

* Visual Studio Code
* macOS

⸻

Estrutura do projeto

src/
├── db/
│   ├── mysql.py
│   └── redis.py
│
├── models/
│   ├── schemas.py
│
├── routes/
│   └── admin.py
│   └── webhook.py
│
├── services/
│   ├── claude_service.py
│   └── disponibilidade_service.py
│   └── session_service.py
│   └── tecnico_service.py
│   └── whatsapp.py
│
└── main.py
.env
requirements.txt

Organização

* main.py → ponto de entrada da aplicação;
* routes/ → definição das rotas e recebimento dos eventos;
* services/ → regras de negócio e integrações externas;
* db/ → conexões e operações com banco de dados.

⸻

Como executar

1. Clone o repositório

git clone https://github.com/drenato-v/chatbot-ortopedia-whatsapp
cd chatbot-ortopedia-whatsapp

2. Crie e ative o ambiente virtual

python -m venv venv
# macOS/Linux
source venv/bin/activate

3. Instale as dependências

pip install -r requirements.txt

4. Configure as variáveis de ambiente

Crie um arquivo .env contendo as credenciais necessárias:

CLAUDE_API_KEY=
META_API_KEY=
MYSQL_HOST=
MYSQL_USER=
MYSQL_PASSWORD=
MYSQL_DATABASE=
REDIS_HOST=

5. Execute o projeto

uvicorn src.main:app --reload

⸻

Objetivo de aprendizado

Este projeto também representa meu processo de aprendizado em construção de sistemas inteligentes orientados por APIs.
O foco foi entender como conectar uma IA ao fluxo real de atendimento, permitindo que o modelo converse tanto com sistemas internos quanto com clientes finais através das integrações com Claude API e Meta WhatsApp API.

Durante o desenvolvimento foram explorados conceitos como:

* arquitetura de serviços;
* comunicação entre APIs;
* gerenciamento de estado com Redis;
* integração com bancos relacionais;
* automação de atendimento.

⸻

Autor

Diego Renato Vasconcelos de Lima
Desenvolvido para a Ortopedia Geral
