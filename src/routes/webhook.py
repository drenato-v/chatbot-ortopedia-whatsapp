# Ferramentas de roteamento e utilitários HTTP do FastAPI
from fastapi import APIRouter, Request, Query
from fastapi.responses import PlainTextResponse, JSONResponse

# Geração de resposta pela IA (Claude)
from services.claude_service import gerar_resposta

# Gerenciamento de sessão em Redis (estado atual + histórico + dados do agendamento)
from services.session_service import (
    EstadosConversa, obter_sessao, salvar_sessao,
    obter_agendamento_id,
)

# Serviços de técnicos: busca de disponibilidade, fidelização e controle de agenda
from services.tecnico_service import (
    buscar_tecnico_cliente, buscar_tecnicos_disponiveis,
    buscar_horarios_disponiveis, atribuir_tecnico_cliente,
    marcar_hora_como_ocupada, liberar_hora,
)

# Envio de mensagens ao cliente via WhatsApp Business API
from services.whatsapp import enviar_mensagem

# Funções de acesso ao banco de dados MySQL
from db.mysql import (
    buscar_cliente_por_numero, criar_cliente, salvar_conversa,
    criar_agendamento_em_progresso, atualizar_agendamento,
    buscar_agendamento_em_progresso, buscar_agendamento_por_id,
    buscar_servicos_cliente, atualizar_nome_cliente,
    buscar_agendamento_ativo_por_cliente,
    verificar_paciente_por_nome_telefone,
    buscar_agendamento_por_cliente_e_data,
    verificar_presenca_paciente,
    verificar_cpf_paciente,
    criar_notificacao,
    buscar_paciente_por_cliente_id, criar_paciente,
)
from datetime import datetime
import re
import os

router = APIRouter()

# Token de verificação registrado no painel da Meta — deve bater exatamente
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "ortopedia_token")

# Lista de serviços disponíveis na clínica
SETORES = [
    "Prótese", "Palmilha", "Tutor", "Órteses",
    "Órtese Individual", "Cadeira de Rodas", "Escaneamento 3D", "Outras",
]


# ── Verificação do webhook ────────────────────────────────────────────────────

@router.get("/webhook")
async def verificar_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """
    Endpoint de verificação exigido pela Meta ao cadastrar o webhook.
    Retorna o hub.challenge apenas se o token conferir.
    """
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return PlainTextResponse(content=hub_challenge)
    return PlainTextResponse(content="Token inválido", status_code=403)


# ── Helpers de detecção ───────────────────────────────────────────────────────

def detectar_setor(mensagem: str) -> str:
    """
    Identifica qual serviço da clínica foi mencionado na mensagem.

    Usa termos específicos em vez de varrer a lista SETORES para evitar
    falsos positivos — ex: "outras dúvidas" não deve ativar o setor "Outras".
    Retorna None se nenhum serviço for reconhecido.

    Ordem importa: "Órtese Individual" é verificada antes de "Órteses"
    para evitar que a versão genérica consuma o termo mais específico.
    """
    msg = mensagem.lower()
    if any(p in msg for p in ["ortese individual", "órtese individual"]):
        return "Órtese Individual"
    if any(p in msg for p in ["prótese", "protese", "membro artificial"]):
        return "Prótese"
    if any(p in msg for p in ["palmilha"]):
        return "Palmilha"
    if any(p in msg for p in ["tutor"]):
        return "Tutor"
    if any(p in msg for p in ["órtese", "ortese"]):
        return "Órteses"
    if any(p in msg for p in ["cadeira de rodas", "cadeira"]):
        return "Cadeira de Rodas"
    if any(p in msg for p in ["3d", "escaneamento", "scan", "colete"]):
        return "Escaneamento 3D"
    return None


# Estados em que há um agendamento ativamente sendo preenchido.
# Evita que uma nova menção de serviço reinicie o fluxo do zero.
_ESTADOS_EM_FLUXO = {
    EstadosConversa.AGENDAMENTO_PENDENTE,
    EstadosConversa.AGUARDANDO_NOME,
    EstadosConversa.AGUARDANDO_TELEFONE,
    EstadosConversa.AGUARDANDO_DATA,
    EstadosConversa.AGUARDANDO_HORARIO,
    EstadosConversa.AGUARDANDO_TIPO,
    EstadosConversa.REAGENDAMENTO_NOME,
    EstadosConversa.REAGENDAMENTO_TELEFONE,
    EstadosConversa.REAGENDAMENTO_DATA_ANTIGA,
    EstadosConversa.CANCELAMENTO_NOME,
    EstadosConversa.CANCELAMENTO_TELEFONE,
    EstadosConversa.CANCELAMENTO_CPF,
    EstadosConversa.CANCELAMENTO_DATA,
}

# Estados do fluxo de reagendamento — impedem re-disparo da intercepção.
_ESTADOS_REAGENDAMENTO = {
    EstadosConversa.REAGENDAMENTO_NOME,
    EstadosConversa.REAGENDAMENTO_TELEFONE,
    EstadosConversa.REAGENDAMENTO_DATA_ANTIGA,
}

# Estados do fluxo de cancelamento — impedem re-disparo da intercepção.
_ESTADOS_CANCELAMENTO = {
    EstadosConversa.CANCELAMENTO_NOME,
    EstadosConversa.CANCELAMENTO_TELEFONE,
    EstadosConversa.CANCELAMENTO_CPF,
    EstadosConversa.CANCELAMENTO_DATA,
}


def detectar_intencao(mensagem: str, estado: str) -> str:
    """
    Determina o próximo estado da conversa com base no texto e no estado atual.

    Funciona como uma máquina de estados simplificada:
    - Dentro do fluxo de agendamento, mensagens são interpretadas como respostas
      às perguntas do bot (nome, telefone, data, horário).
    - Fora do fluxo, palavras-chave de agendamento ou serviços iniciam o processo.
    - Data, horário e setor detectados avançam o fluxo para a etapa seguinte.
    """
    msg = mensagem.lower()

    # Detecta padrões estruturados na mensagem
    tem_data    = bool(re.search(r'\d{2}/\d{2}/\d{4}', mensagem))
    tem_horario = bool(re.search(r'\d{1,2}[:h]\d{2}', mensagem))

    # Aceita hora sem minutos (ex: "14", "9") somente quando aguardando horário.
    # Fora desse contexto, "14" poderia ser confundido com parte de texto ou data.
    if not tem_horario and estado == EstadosConversa.AGUARDANDO_HORARIO:
        bare = re.match(r'^\s*(\d{1,2})\s*$', mensagem)
        if bare and 8 <= int(bare.group(1)) <= 20:
            tem_horario = True

    tem_setor = bool(detectar_setor(mensagem))

    # Durante coleta de nome, qualquer mensagem é tratada como o nome do paciente
    if estado == EstadosConversa.AGUARDANDO_NOME:
        return EstadosConversa.AGUARDANDO_NOME

    # Palavras explícitas de agendamento fora do fluxo → iniciam o processo
    if any(w in msg for w in ["agendar", "marcar", "consulta", "quero consultar",
                               "quero agendar", "quero marcar"]) \
            and estado not in _ESTADOS_EM_FLUXO:
        return EstadosConversa.AGENDAMENTO_PENDENTE

    # Data informal tipo "dia 25" também é válida para avançar quando aguardando data
    tem_dia_informal = bool(re.search(r'\bdia\s+\d{1,2}\b|\d{1,2}/\d{1,2}(?!/\d)', msg))

    # Qualquer menção de serviço fora do fluxo inicia o agendamento diretamente
    if tem_setor and estado not in _ESTADOS_EM_FLUXO:
        return EstadosConversa.AGENDAMENTO_PENDENTE

    # Data reconhecida → avança para coleta de horário
    if tem_data and estado in (EstadosConversa.AGUARDANDO_DATA,
                                EstadosConversa.AGENDAMENTO_PENDENTE):
        return EstadosConversa.AGUARDANDO_HORARIO

    if tem_dia_informal and estado == EstadosConversa.AGUARDANDO_DATA:
        return EstadosConversa.AGUARDANDO_HORARIO

    # Horário reconhecido → avança para finalização (confirma setor se necessário)
    if tem_horario and estado == EstadosConversa.AGUARDANDO_HORARIO:
        return EstadosConversa.AGUARDANDO_TIPO

    # Setor dentro de AGENDAMENTO_PENDENTE → mantém estado
    # (o handler avança para AGUARDANDO_NOME após salvar o setor)
    if tem_setor and estado == EstadosConversa.AGENDAMENTO_PENDENTE:
        return EstadosConversa.AGENDAMENTO_PENDENTE

    # Dentro de qualquer estado de fluxo ativo → permanece no estado atual
    if estado in _ESTADOS_EM_FLUXO:
        return estado

    return EstadosConversa.CONVERSA_LIVRE


def extrair_data(texto: str):
    """
    Extrai uma data do texto do cliente. Aceita dois formatos:
    - DD/MM/AAAA: formato completo e explícito
    - "dia N": assume mês/ano corrente; avança para o próximo mês se o dia já passou

    Retorna (data_str no formato "%d/%m/%Y", data_obj datetime) ou (None, None).
    """
    # Tenta extrair formato completo DD/MM/AAAA
    m = re.search(r'(\d{2}/\d{2}/\d{4})', texto)
    if m:
        data_str = m.group(1)
        try:
            return data_str, datetime.strptime(data_str, "%d/%m/%Y")
        except ValueError:
            return None, None

    # Tenta extrair formato informal "dia N"
    m = re.search(r'\bdia\s+(\d{1,2})\b', texto.lower())
    if m:
        dia  = int(m.group(1))
        hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            data_obj = hoje.replace(day=dia)
            # Se o dia já passou este mês, assume o mês seguinte
            if data_obj < hoje:
                mes = hoje.month + 1 if hoje.month < 12 else 1
                ano = hoje.year if hoje.month < 12 else hoje.year + 1
                data_obj = data_obj.replace(year=ano, month=mes)
            return data_obj.strftime("%d/%m/%Y"), data_obj
        except ValueError:
            pass

    return None, None


# ── Webhook principal ─────────────────────────────────────────────────────────

@router.post("/webhook")
async def webhook(request: Request):
    """
    Processa mensagens recebidas do WhatsApp via Meta Business API.

    Fluxo de execução:
    1. Extrai número e texto do payload da Meta
    2. Identifica ou cria o cliente no banco
    3. Recupera a sessão Redis (estado, histórico, dados do agendamento)
    4. Verifica se há follow-up de agendamento já registrado
    5. Detecta a intenção e avança o estado da conversa
    6. Executa o handler específico do estado (coleta dados, busca horários, etc.)
    7. Gera resposta: direta (resposta_direta) ou via Claude
    8. Persiste sessão e conversa; envia resposta ao WhatsApp
    """
    try:
        data = await request.json()

        # Navega pela estrutura aninhada do payload da Meta
        changes  = data.get("entry", [{}])[0].get("changes", [{}])[0]
        messages = changes.get("value", {}).get("messages", [])

        # Ignora notificações de entrega/leitura e eventos sem mensagem de texto
        if not messages:
            return JSONResponse({"status": "ok"})

        mensagem       = messages[0]
        numero_cliente = mensagem.get("from")

        # Descarta mensagens não-texto (imagens, áudios, stickers, etc.)
        if mensagem.get("type") != "text":
            return JSONResponse({"status": "ok"})

        texto_cliente = mensagem.get("text", {}).get("body", "").strip()
        if not numero_cliente or not texto_cliente:
            return JSONResponse({"status": "ok"})

        # ── 1. Identificar cliente ────────────────────────────────────────────
        # Busca cliente existente pelo número ou cria um novo registro
        cliente = buscar_cliente_por_numero(numero_cliente)
        if not cliente:
            cliente_id = criar_cliente(numero_cliente)
        else:
            cliente_id = cliente["id"]

        # ── 2. Recuperar sessão Redis ─────────────────────────────────────────
        sessao            = obter_sessao(numero_cliente)
        estado_atual      = sessao.get("estado", EstadosConversa.INICIAL)
        historico         = sessao.get("historico", [])
        dados_agendamento = sessao.get("dados_agendamento", {})

        # Injeta histórico de serviços do cliente somente na primeira mensagem da sessão,
        # para personalizar o atendimento sem sobrecarregar o contexto do Claude
        perfil_cliente = None
        if not historico and cliente_id:
            servicos = buscar_servicos_cliente(cliente_id)
            if servicos:
                lista = ", ".join(
                    f"{s['tipo_consulta']} ({s['total']}x)" for s in servicos
                )
                perfil_cliente = f"Cliente recorrente. Serviços já solicitados: {lista}."

        # Safety net: se a sessão ficou presa num estado de fluxo mas o agendamento
        # desta sessão já foi confirmado no banco, reseta para conversa livre.
        # Verifica apenas o agendamento_id da sessão atual — não agendamentos anteriores.
        if estado_atual in _ESTADOS_EM_FLUXO:
            ag_id_sessao = sessao.get("agendamento_id")
            if ag_id_sessao:
                ag_sessao = buscar_agendamento_por_id(ag_id_sessao)
                if ag_sessao and ag_sessao.get("status") == "confirmado":
                    estado_atual      = EstadosConversa.CONVERSA_LIVRE
                    dados_agendamento = {}
                    historico         = []
                    sessao.pop("agendamento_id", None)

        # resposta_direta: quando definida, bypassa o Claude completamente.
        # Garante que mensagens críticas de fluxo sejam exatas e previsíveis.
        resposta_direta = None

        # ── 3. Intercepção de reagendamento ──────────────────────────────────
        _PALAVRAS_REAGENDAMENTO = [
            "reagendar", "remarcar", "mudar horário", "mudar data",
            "trocar horário", "não posso comparecer", "nova data",
            "novo horário", "preciso mudar", "quero mudar",
        ]

        # Palavras que encerram o fluxo de reagendamento (inclui "cancelar" = desistir de reagendar)
        _PALAVRAS_SAIR = ["deixa", "desistir", "cancelar", "sair", "esquecer",
                          "não quero", "nao quero", "para", "chega"]
        # Palavras que encerram o fluxo de cancelamento (sem "cancelar" para não conflitar)
        _PALAVRAS_SAIR_CANCELAMENTO = ["deixa", "desistir", "sair", "esquecer",
                                       "não quero", "nao quero", "para", "chega"]

        # Saída do fluxo de reagendamento — detecta quando o cliente desiste
        if (estado_atual in _ESTADOS_REAGENDAMENTO
                and any(w in texto_cliente.lower() for w in _PALAVRAS_SAIR)):
            historico         = []
            dados_agendamento = {}
            sessao.pop("agendamento_id", None)
            resposta_direta = "Tudo bem! Se precisar reagendar ou tiver qualquer dúvida, é só chamar."
            novo_estado = EstadosConversa.CONVERSA_LIVRE

        # Saída do fluxo de cancelamento — detecta quando o cliente desiste
        if (resposta_direta is None
                and estado_atual in _ESTADOS_CANCELAMENTO
                and any(w in texto_cliente.lower() for w in _PALAVRAS_SAIR_CANCELAMENTO)):
            historico         = []
            dados_agendamento = {}
            resposta_direta   = "Tudo bem! Se precisar cancelar ou tiver qualquer dúvida, é só chamar."
            novo_estado       = EstadosConversa.CONVERSA_LIVRE

        # Inicia fluxo de reagendamento — interrompe qualquer estado exceto
        # os próprios estados de reagendamento (evita loop infinito)
        if (resposta_direta is None
                and estado_atual not in _ESTADOS_REAGENDAMENTO
                and any(w in texto_cliente.lower() for w in _PALAVRAS_REAGENDAMENTO)):
            # Limpa estado anterior para evitar contaminação de sessões antigas
            historico         = []
            dados_agendamento = {}
            sessao.pop("agendamento_id", None)
            resposta_direta = (
                "Para reagendar, preciso verificar seus dados.\n\n"
                "Qual é o nome *completo* do paciente? (nome e sobrenome)"
            )
            novo_estado = EstadosConversa.REAGENDAMENTO_NOME

        # Palavras que iniciam o fluxo de cancelamento pelo bot
        _PALAVRAS_CANCELAMENTO = [
            "cancelar", "cancela", "quero cancelar", "desmarcar", "desmarca",
            "não vou comparecer", "nao vou comparecer",
            "não posso ir", "nao posso ir",
            "não vou conseguir", "nao vou conseguir",
            "não vou poder", "nao vou poder",
            "não consigo ir", "nao consigo ir",
            "não poderei", "nao poderei",
            "cancelamento",
        ]

        # Inicia fluxo de cancelamento — não dispara dentro do próprio fluxo
        # nem dentro do fluxo de reagendamento
        if (resposta_direta is None
                and estado_atual not in _ESTADOS_CANCELAMENTO
                and estado_atual not in _ESTADOS_REAGENDAMENTO
                and any(w in texto_cliente.lower() for w in _PALAVRAS_CANCELAMENTO)):
            historico         = []
            dados_agendamento = {}
            sessao.pop("agendamento_id", None)
            resposta_direta = (
                "Para cancelar, preciso verificar seus dados.\n\n"
                "Qual é o nome *completo* do paciente? (nome e sobrenome)"
            )
            novo_estado = EstadosConversa.CANCELAMENTO_NOME

        # ── 4. Follow-up pós-registro ─────────────────────────────────────────
        # Quando o paciente responde após ter um agendamento registrado,
        # consulta o banco para saber o status real antes de responder.
        if resposta_direta is None and estado_atual == EstadosConversa.AGENDAMENTO_CONFIRMADO:
            ag_id = sessao.get("agendamento_id")
            ag    = buscar_agendamento_por_id(ag_id) if ag_id else None

            # Se o painel já tomou uma decisão (confirmou ou recusou), o caso está encerrado
            if ag and ag.get("status") in ("confirmado", "cancelado"):
                resposta_direta = "Posso ajudar com mais alguma coisa?"
            else:
                # Ainda aguardando análise do painel
                resposta_direta = (
                    "Sua solicitação ainda está aguardando análise da nossa equipe. "
                    "Você receberá uma mensagem aqui assim que for confirmado. "
                    "Posso ajudar com mais alguma coisa?"
                )
            novo_estado       = EstadosConversa.CONVERSA_LIVRE
            dados_agendamento = {}
            sessao.pop("agendamento_id", None)  # libera o ID após verificar o status

        # ── 4. Detecção de intenção ───────────────────────────────────────────
        contexto_extra  = ""
        setor_detectado = None

        if resposta_direta is None:
            novo_estado = detectar_intencao(texto_cliente, estado_atual)
            # Preserva setor já coletado em etapas anteriores da mesma sessão
            setor_detectado = detectar_setor(texto_cliente) or dados_agendamento.get("setor")
            agendamento_id  = obter_agendamento_id(numero_cliente)

            # Recupera agendamento_id do banco se a sessão Redis perdeu o valor
            # (pode ocorrer por reinicialização do servidor ou expiração do TTL)
            if agendamento_id is None and estado_atual in _ESTADOS_EM_FLUXO:
                ag_em_prog = buscar_agendamento_em_progresso(cliente_id)
                if ag_em_prog:
                    agendamento_id = ag_em_prog["id"]
                    sessao["agendamento_id"] = agendamento_id
                    print(f"[RECOVER] agendamento_id={agendamento_id} recuperado do banco")

        # ── 5. Handlers por estado ────────────────────────────────────────────

        if resposta_direta is None and novo_estado == EstadosConversa.AGENDAMENTO_PENDENTE:
            # Novo agendamento iniciado — limpa histórico para evitar que o Claude
            # siga padrões de mensagens anteriores (ex: "ligue na clínica")
            if estado_atual not in _ESTADOS_EM_FLUXO:
                historico = []

            # Cria registro parcial no banco para poder atualizar ao longo do fluxo
            if not agendamento_id:
                agendamento_id = criar_agendamento_em_progresso(cliente_id)
                sessao["agendamento_id"] = agendamento_id

            if setor_detectado:
                dados_agendamento["setor"] = setor_detectado
                tecnico_anterior = buscar_tecnico_cliente(cliente_id, setor_detectado)
                contexto_extra = (
                    f"INSTRUÇÃO OBRIGATÓRIA: O cliente quer agendar '{setor_detectado}'. "
                    f"Pergunte AGORA o nome completo do paciente. "
                    f"NÃO mencione telefone. NÃO diga para ligar na clínica. NÃO verifique horários ainda."
                )
                if tecnico_anterior:
                    # Menciona o técnico preferido para personalizar o atendimento
                    contexto_extra += (
                        f" (Após confirmar o nome, mencione que o cliente já foi atendido"
                        f" por {tecnico_anterior['nome']} neste setor.)"
                    )
                novo_estado = EstadosConversa.AGUARDANDO_NOME
            else:
                # Serviço não identificado → pede ao cliente que escolha
                lista = ", ".join(SETORES)
                contexto_extra = (
                    f"INSTRUÇÃO OBRIGATÓRIA: Pergunte qual serviço o cliente precisa para agendar. "
                    f"Opções: {lista}. NÃO mencione telefone nem redirecione para a clínica."
                )

        elif novo_estado == EstadosConversa.AGUARDANDO_NOME:
            nome_paciente = texto_cliente.strip()
            palavras_nome = [p for p in re.split(r'[\s\-]+', nome_paciente) if len(p) > 1]
            if len(palavras_nome) < 2:
                # Exige nome completo — apenas primeiro nome não é aceito
                resposta_direta = (
                    "Por favor, informe o nome *completo* do paciente "
                    "(nome e sobrenome). Não aceitamos apenas o primeiro nome."
                )
                novo_estado = EstadosConversa.AGUARDANDO_NOME
            else:
                dados_agendamento["nome_paciente"] = nome_paciente
                atualizar_nome_cliente(cliente_id, nome_paciente)
                contexto_extra = (
                    f"Nome do paciente registrado: {nome_paciente}. "
                    "Agora pergunte o número de celular do paciente para contato."
                )
                novo_estado = EstadosConversa.AGUARDANDO_TELEFONE

        elif novo_estado == EstadosConversa.AGUARDANDO_TELEFONE:
            # Remove caracteres inválidos mantendo dígitos, +, parênteses, hífen e espaço
            tel = re.sub(r'[^\d+()\- ]', '', texto_cliente).strip() or texto_cliente.strip()
            dados_agendamento["telefone_paciente"] = tel
            contexto_extra = (
                f"Telefone do paciente registrado: {tel}. "
                "Pergunte qual data deseja para o agendamento, no formato DD/MM/AAAA."
            )
            novo_estado = EstadosConversa.AGUARDANDO_DATA

        elif novo_estado == EstadosConversa.AGUARDANDO_DATA:
            # Intercepta horário enviado por engano no lugar da data
            tem_hora_entrada = bool(re.search(r'^\s*\d{1,2}[:h]\d{2}\s*$', texto_cliente))
            if tem_hora_entrada:
                resposta_direta = (
                    "Preciso de uma data, não de um horário. "
                    "Em que data você gostaria de agendar? (ex: 25/06/2026)"
                )
            # Sem interceptação → Claude solicita a data com contexto adequado

        elif novo_estado == EstadosConversa.AGUARDANDO_HORARIO:
            # Usuário acabou de fornecer a data — extrai e busca horários disponíveis
            data_str, data_obj = extrair_data(texto_cliente)
            if data_str and data_obj:
                agora = datetime.now()
                hoje  = agora.replace(hour=0, minute=0, second=0, microsecond=0)

                if data_obj < hoje:
                    # Data anterior a hoje — rejeita diretamente sem acionar o Claude
                    resposta_direta = (
                        "Essa data já passou! Por favor, informe uma data a partir de hoje."
                    )
                    novo_estado = EstadosConversa.AGUARDANDO_DATA
                elif data_obj.weekday() in (5, 6):
                    # Sábado (5) ou domingo (6) — sem atendimento
                    resposta_direta = (
                        "Não realizamos atendimentos aos sábados e domingos. "
                        "Por favor, informe uma data de segunda a sexta."
                    )
                    novo_estado = EstadosConversa.AGUARDANDO_DATA
                else:
                    dados_agendamento["data"] = data_str
                    data_mysql = data_obj.strftime("%Y-%m-%d")
                    if agendamento_id:
                        # Persiste a data imediatamente para não perder em caso de falha posterior
                        atualizar_agendamento(agendamento_id, data_agendamento=data_obj)
                    setor = dados_agendamento.get("setor")
                    if setor:
                        # Busca apenas o dia solicitado (dias=1) para não sobrecarregar a resposta
                        slots_dia   = buscar_horarios_disponiveis(setor, data_mysql, dias=1)
                        disponiveis = [
                            s["hora"] for dia in slots_dia.values()
                            for s in dia if s["disponivel"]
                        ]
                        # Para hoje, remove os horários que já passaram
                        if data_obj.date() == agora.date():
                            disponiveis = [
                                h for h in disponiveis
                                if int(h.split(":")[0]) > agora.hour
                            ]
                        if disponiveis:
                            contexto_extra = (
                                f"Horários disponíveis em {data_str}: {', '.join(disponiveis)}. "
                                "Liste esses horários AGORA e peça ao cliente para escolher um. "
                                "NÃO diga que vai verificar. NÃO invente [SISTEMA]."
                            )
                        else:
                            # Sem horários disponíveis nessa data → volta para pedir nova data
                            contexto_extra = (
                                f"Não há horários disponíveis em {data_str}. "
                                "Informe ao cliente e peça outra data."
                            )
                            novo_estado = EstadosConversa.AGUARDANDO_DATA
            else:
                contexto_extra = "Data não reconhecida. Peça ao cliente para informar no formato DD/MM/AAAA."
                novo_estado    = EstadosConversa.AGUARDANDO_DATA

        elif novo_estado == EstadosConversa.AGUARDANDO_TIPO:
            # Usuário acabou de informar o horário — extrai e normaliza para HH:MM
            horario_match = re.search(r'(\d{1,2})[:h](\d{2})', texto_cliente)
            if horario_match:
                hora_int    = int(horario_match.group(1))
                horario_str = f"{hora_int:02d}:{horario_match.group(2)}"
            else:
                # Hora sem minutos: "14" → "14:00"
                bare = re.match(r'^\s*(\d{1,2})\s*$', texto_cliente)
                if bare and 8 <= int(bare.group(1)) <= 20:
                    hora_int    = int(bare.group(1))
                    horario_str = f"{hora_int:02d}:00"
                else:
                    hora_int    = None
                    horario_str = ""

            if hora_int is not None:
                # Rejeita horário que já passou para agendamentos no dia atual
                data_str_salva = dados_agendamento.get("data")
                if data_str_salva:
                    data_agendada = datetime.strptime(data_str_salva, "%d/%m/%Y")
                    if data_agendada.date() == datetime.now().date() and hora_int <= datetime.now().hour:
                        proxima = datetime.now().hour + 1
                        resposta_direta = (
                            f"Esse horário já passou. Informe um horário disponível "
                            f"a partir das {proxima:02d}:00."
                        )
                        novo_estado = EstadosConversa.AGUARDANDO_HORARIO
                        hora_int = None  # descarta o horário inválido

            if hora_int is not None:
                dados_agendamento["horario"]  = horario_str
                dados_agendamento["hora_int"] = hora_int
                if agendamento_id:
                    atualizar_agendamento(agendamento_id, horario=horario_str)

            # Salva setor se detectado nesta mensagem e ainda não havia sido definido
            if setor_detectado and not dados_agendamento.get("setor"):
                dados_agendamento["setor"] = setor_detectado

            if resposta_direta is None:
                setor_final   = dados_agendamento.get("setor")
                data_final    = dados_agendamento.get("data")
                horario_final = dados_agendamento.get("horario")
                hora_final    = dados_agendamento.get("hora_int")

                if setor_final and data_final and horario_final and hora_final is not None:
                    # Todos os dados coletados — finaliza o agendamento aqui diretamente
                    novo_estado  = EstadosConversa.AGENDAMENTO_CONFIRMADO
                    data_mysql   = datetime.strptime(data_final, "%d/%m/%Y").strftime("%Y-%m-%d")
                    data_hora    = datetime.strptime(f"{data_final} {horario_final}", "%d/%m/%Y %H:%M")
                    tecnicos_disponiveis = buscar_tecnicos_disponiveis(data_mysql, hora_final, setor_final)
                    tecnico_preferido    = buscar_tecnico_cliente(cliente_id, setor_final)
                    if tecnico_preferido and any(t["id"] == tecnico_preferido["id"] for t in tecnicos_disponiveis):
                        tecnico = tecnico_preferido
                    else:
                        tecnico = tecnicos_disponiveis[0] if tecnicos_disponiveis else None
                    campos_update = dict(
                        tipo_consulta=setor_final,
                        status="pendente",
                        data_agendamento=data_hora,
                        horario=horario_final,
                    )
                    nome_pac     = dados_agendamento.get("nome_paciente")
                    telefone_pac = dados_agendamento.get("telefone_paciente")
                    if nome_pac:
                        campos_update["nome_paciente"] = nome_pac
                    if telefone_pac:
                        campos_update["telefone_paciente"] = telefone_pac
                    if tecnico:
                        campos_update["tecnico_id"] = tecnico["id"]
                        atribuir_tecnico_cliente(cliente_id, tecnico["id"], setor_final)
                        marcar_hora_como_ocupada(tecnico["id"], data_mysql, hora_final)
                    if agendamento_id:
                        atualizar_agendamento(agendamento_id, **campos_update)
                    if not buscar_paciente_por_cliente_id(cliente_id):
                        criar_paciente(nome=nome_pac or "", telefone=telefone_pac, cliente_id=cliente_id)
                    nome_exibir = nome_pac or "paciente"
                    if tecnico:
                        resposta_direta = (
                            f"Prontinho, {nome_exibir}! Sua solicitação de agendamento foi enviada para nossa equipe.\n\n"
                            f"Serviço: {setor_final}\n"
                            f"Data: {data_final}\n"
                            f"Horário: {horario_final}\n\n"
                            f"Aguarde — nossa equipe irá analisar e confirmar em breve. "
                            f"Você receberá uma mensagem aqui pelo WhatsApp assim que for confirmado. "
                            f"Não é necessário fazer mais nada agora!"
                        )
                    else:
                        resposta_direta = (
                            f"Sua solicitação para {setor_final} em {data_final} às {horario_final} foi registrada, "
                            f"mas no momento não há técnicos disponíveis nesse horário. "
                            f"Nossa equipe entrará em contato para verificar a melhor alternativa."
                        )
                    dados_agendamento = {}
                elif setor_final:
                    novo_estado = EstadosConversa.AGENDAMENTO_CONFIRMADO
                else:
                    # Setor ainda desconhecido → pede ao cliente
                    lista = ", ".join(SETORES)
                    contexto_extra = f"Pergunte qual o tipo de serviço. Opções: {lista}"

        # ── Handlers do fluxo de reagendamento ───────────────────────────────
        # Bloco separado (if, não elif) com guarda resposta_direta is None
        # para não rodar quando a intercepção de reagendamento já setou a resposta.

        if resposta_direta is None and novo_estado == EstadosConversa.REAGENDAMENTO_NOME:
            nome = texto_cliente.strip()
            palavras = [p for p in re.split(r'[\s\-]+', nome) if len(p) > 1]
            if len(palavras) < 2:
                resposta_direta = (
                    "Preciso do nome *completo* (nome e sobrenome). "
                    "Por favor, informe novamente."
                )
                novo_estado = EstadosConversa.REAGENDAMENTO_NOME
            else:
                dados_agendamento["reagendamento_nome"] = nome
                resposta_direta = (
                    f"Obrigado, {nome.split()[0]}!\n\n"
                    "Agora informe o número de celular cadastrado."
                )
                novo_estado = EstadosConversa.REAGENDAMENTO_TELEFONE

        elif resposta_direta is None and novo_estado == EstadosConversa.REAGENDAMENTO_TELEFONE:
            tel    = texto_cliente.strip()
            digits = re.sub(r'\D', '', tel)
            if len(digits) < 6:
                # Texto sem dígitos suficientes — provavelmente digitou nome por engano
                resposta_direta = (
                    "Isso não parece um número de celular. "
                    "Por favor, informe apenas o número (ex: 17999999999)."
                )
                novo_estado = EstadosConversa.REAGENDAMENTO_TELEFONE
            else:
                nome = dados_agendamento.get("reagendamento_nome", "")
                if verificar_paciente_por_nome_telefone(nome, tel):
                    dados_agendamento["reagendamento_tel"] = tel
                    resposta_direta = (
                        "Dados verificados!\n\n"
                        "Para qual *data* está marcado o agendamento que deseja reagendar? "
                        "(ex: 30/06/2026)"
                    )
                    novo_estado = EstadosConversa.REAGENDAMENTO_DATA_ANTIGA
                else:
                    resposta_direta = (
                        "Nome ou número não encontrado em nosso sistema. "
                        "Verifique os dados e informe novamente o número de celular."
                    )
                    novo_estado = EstadosConversa.REAGENDAMENTO_TELEFONE

        elif resposta_direta is None and novo_estado == EstadosConversa.REAGENDAMENTO_DATA_ANTIGA:
            data_antiga_str, _ = extrair_data(texto_cliente)
            if not data_antiga_str:
                resposta_direta = (
                    "Data não reconhecida. Informe no formato DD/MM/AAAA (ex: 30/06/2026)."
                )
                novo_estado = EstadosConversa.REAGENDAMENTO_DATA_ANTIGA
            else:
                ag_antigo = buscar_agendamento_por_cliente_e_data(cliente_id, data_antiga_str)
                if not ag_antigo:
                    resposta_direta = (
                        f"Não encontrei agendamento ativo para o dia {data_antiga_str}. "
                        "Verifique a data e informe novamente."
                    )
                    novo_estado = EstadosConversa.REAGENDAMENTO_DATA_ANTIGA
                else:
                    # Cancela agendamento antigo e libera slots
                    atualizar_agendamento(ag_antigo["id"], status="cancelado")
                    if ag_antigo.get("tecnico_id") and ag_antigo.get("data_agendamento") and ag_antigo.get("horario"):
                        data_lib = ag_antigo["data_agendamento"].strftime("%Y-%m-%d")
                        hora_lib = int(ag_antigo["horario"].split(":")[0])
                        liberar_hora(ag_antigo["tecnico_id"], data_lib, hora_lib)
                        if ag_antigo.get("tecnico_id_2"):
                            liberar_hora(ag_antigo["tecnico_id_2"], data_lib, hora_lib)
                    # Pré-preenche dados do agendamento antigo para o novo fluxo,
                    # preservando telefone original para não usar o número do WhatsApp.
                    servico_fmt = ag_antigo.get("tipo_consulta") or "o serviço"
                    nome_reag   = dados_agendamento.get("reagendamento_nome") or ag_antigo.get("nome_paciente")
                    tel_reag    = dados_agendamento.get("reagendamento_tel") or ag_antigo.get("telefone_paciente")
                    dados_agendamento = {
                        "setor":             ag_antigo.get("tipo_consulta"),
                        "nome_paciente":     nome_reag,
                        "telefone_paciente": tel_reag,
                    }
                    novo_ag_id = criar_agendamento_em_progresso(cliente_id)
                    sessao["agendamento_id"] = novo_ag_id
                    resposta_direta = (
                        f"Agendamento de {servico_fmt} do dia {data_antiga_str} cancelado!\n\n"
                        "Para qual nova data você gostaria de reagendar? (ex: 05/07/2026)"
                    )
                    novo_estado = EstadosConversa.AGUARDANDO_DATA

        # ── Handlers do fluxo de cancelamento ────────────────────────────────
        # Bloco independente com guarda resposta_direta is None.

        if resposta_direta is None and novo_estado == EstadosConversa.CANCELAMENTO_NOME:
            nome = texto_cliente.strip()
            palavras = [p for p in re.split(r'[\s\-]+', nome) if len(p) > 1]
            if len(palavras) < 2:
                resposta_direta = (
                    "Preciso do nome *completo* (nome e sobrenome). "
                    "Por favor, informe novamente."
                )
                novo_estado = EstadosConversa.CANCELAMENTO_NOME
            else:
                dados_agendamento["cancelamento_nome"] = nome
                resposta_direta = (
                    f"Obrigado, {nome.split()[0]}!\n\n"
                    "Agora informe o número de celular cadastrado."
                )
                novo_estado = EstadosConversa.CANCELAMENTO_TELEFONE

        elif resposta_direta is None and novo_estado == EstadosConversa.CANCELAMENTO_TELEFONE:
            tel    = texto_cliente.strip()
            digits = re.sub(r'\D', '', tel)
            if len(digits) < 6:
                resposta_direta = (
                    "Isso não parece um número de celular. "
                    "Por favor, informe apenas o número (ex: 17999999999)."
                )
                novo_estado = EstadosConversa.CANCELAMENTO_TELEFONE
            else:
                nome = dados_agendamento.get("cancelamento_nome", "")
                if verificar_paciente_por_nome_telefone(nome, tel):
                    dados_agendamento["cancelamento_tel"] = tel
                    # Verifica se o paciente tem registro presencial (tem CPF no banco)
                    pac_presencial = verificar_presenca_paciente(nome, tel)
                    if pac_presencial and pac_presencial.get("cpf"):
                        resposta_direta = (
                            "Dados verificados!\n\n"
                            "Como você já foi atendido presencialmente, precisamos do seu *CPF* "
                            "para confirmar o cancelamento."
                        )
                        novo_estado = EstadosConversa.CANCELAMENTO_CPF
                    else:
                        resposta_direta = (
                            "Dados verificados!\n\n"
                            "Para qual *data* está marcado o agendamento que deseja cancelar? "
                            "(ex: 30/06/2026)"
                        )
                        novo_estado = EstadosConversa.CANCELAMENTO_DATA
                else:
                    resposta_direta = (
                        "Nome ou número não encontrado em nosso sistema. "
                        "Verifique os dados e informe novamente o número de celular."
                    )
                    novo_estado = EstadosConversa.CANCELAMENTO_TELEFONE

        elif resposta_direta is None and novo_estado == EstadosConversa.CANCELAMENTO_CPF:
            nome = dados_agendamento.get("cancelamento_nome", "")
            if verificar_cpf_paciente(nome, texto_cliente.strip()):
                resposta_direta = (
                    "CPF confirmado!\n\n"
                    "Para qual *data* está marcado o agendamento que deseja cancelar? "
                    "(ex: 30/06/2026)"
                )
                novo_estado = EstadosConversa.CANCELAMENTO_DATA
            else:
                resposta_direta = (
                    "CPF não encontrado. Verifique e informe novamente."
                )
                novo_estado = EstadosConversa.CANCELAMENTO_CPF

        elif resposta_direta is None and novo_estado == EstadosConversa.CANCELAMENTO_DATA:
            data_str, _ = extrair_data(texto_cliente)
            if not data_str:
                resposta_direta = (
                    "Data não reconhecida. Informe no formato DD/MM/AAAA (ex: 30/06/2026)."
                )
                novo_estado = EstadosConversa.CANCELAMENTO_DATA
            else:
                ag = buscar_agendamento_por_cliente_e_data(cliente_id, data_str)
                if not ag:
                    resposta_direta = (
                        f"Não encontrei agendamento ativo para o dia {data_str}. "
                        "Verifique a data e informe novamente."
                    )
                    novo_estado = EstadosConversa.CANCELAMENTO_DATA
                else:
                    atualizar_agendamento(ag["id"], status="cancelado")
                    if ag.get("tecnico_id") and ag.get("data_agendamento") and ag.get("horario"):
                        data_lib = ag["data_agendamento"].strftime("%Y-%m-%d")
                        hora_lib = int(ag["horario"].split(":")[0])
                        liberar_hora(ag["tecnico_id"], data_lib, hora_lib)
                        if ag.get("tecnico_id_2"):
                            liberar_hora(ag["tecnico_id_2"], data_lib, hora_lib)
                    servico_fmt  = ag.get("tipo_consulta") or "o serviço"
                    nome_pac     = dados_agendamento.get("cancelamento_nome") or ag.get("nome_paciente") or "Paciente"
                    horario_fmt  = ag.get("horario", "")
                    criar_notificacao(
                        f"Cancelamento via WhatsApp: {nome_pac} cancelou {servico_fmt} "
                        f"do dia {data_str}" + (f" às {horario_fmt}" if horario_fmt else "") + "."
                    )
                    dados_agendamento = {}
                    resposta_direta = (
                        f"Agendamento de *{servico_fmt}* do dia *{data_str}* cancelado com sucesso!\n\n"
                        "Se precisar reagendar ou tiver qualquer dúvida, é só chamar."
                    )
                    novo_estado = EstadosConversa.CONVERSA_LIVRE

        # ── Finalização: bloco separado (não elif) ────────────────────────────
        # Pode ser alcançado diretamente do bloco AGUARDANDO_TIPO acima
        # ou por qualquer outro caminho que resulte em AGENDAMENTO_CONFIRMADO
        if resposta_direta is None and novo_estado == EstadosConversa.AGENDAMENTO_CONFIRMADO:
            setor       = setor_detectado or dados_agendamento.get("setor")
            hora_int    = dados_agendamento.get("hora_int")
            data_str    = dados_agendamento.get("data")
            horario_str = dados_agendamento.get("horario", "")
            print(f"[CONFIRMADO] setor={setor} hora_int={hora_int} data={data_str} horario={horario_str} agend_id={agendamento_id}")

            if setor and hora_int is not None and data_str:
                data_mysql = datetime.strptime(data_str, "%d/%m/%Y").strftime("%Y-%m-%d")
                data_hora  = (
                    datetime.strptime(f"{data_str} {horario_str}", "%d/%m/%Y %H:%M")
                    if horario_str
                    else datetime.strptime(data_str, "%d/%m/%Y")
                )

                # Tenta manter o técnico já conhecido pelo cliente (fidelização)
                tecnicos_disponiveis = buscar_tecnicos_disponiveis(data_mysql, hora_int, setor)
                tecnico_preferido    = buscar_tecnico_cliente(cliente_id, setor)
                if tecnico_preferido and any(
                    t["id"] == tecnico_preferido["id"] for t in tecnicos_disponiveis
                ):
                    tecnico = tecnico_preferido  # usa o técnico fidelizado
                else:
                    tecnico = tecnicos_disponiveis[0] if tecnicos_disponiveis else None

                # Monta campos para atualizar o registro de agendamento no banco
                campos_update = dict(
                    tipo_consulta=setor,
                    status="pendente",         # pendente = aguardando aprovação do painel
                    data_agendamento=data_hora,
                    horario=horario_str,
                )
                nome_pac = dados_agendamento.get("nome_paciente")
                if nome_pac:
                    campos_update["nome_paciente"] = nome_pac
                telefone_pac = dados_agendamento.get("telefone_paciente")
                if telefone_pac:
                    campos_update["telefone_paciente"] = telefone_pac

                if tecnico:
                    campos_update["tecnico_id"] = tecnico["id"]
                    # Registra fidelização e bloqueia o slot na agenda do técnico
                    atribuir_tecnico_cliente(cliente_id, tecnico["id"], setor)
                    marcar_hora_como_ocupada(tecnico["id"], data_mysql, hora_int)

                if agendamento_id:
                    atualizar_agendamento(agendamento_id, **campos_update)

                # Cria paciente no banco caso ainda não exista para este cliente
                if not buscar_paciente_por_cliente_id(cliente_id):
                    criar_paciente(
                        nome=nome_pac or "",
                        telefone=telefone_pac,
                        cliente_id=cliente_id,
                    )

                nome_exibir = nome_pac or "paciente"
                if tecnico:
                    # Mensagem intencional: "enviada para equipe" ≠ "confirmada"
                    # O bot nunca confirma — isso é responsabilidade do painel
                    resposta_direta = (
                        f"Prontinho, {nome_exibir}! Sua solicitação de agendamento foi enviada para nossa equipe.\n\n"
                        f"Serviço: {setor}\n"
                        f"Data: {data_str}\n"
                        f"Horário: {horario_str}\n\n"
                        f"Aguarde — nossa equipe irá analisar e confirmar em breve. "
                        f"Você receberá uma mensagem aqui pelo WhatsApp assim que for confirmado. "
                        f"Não é necessário fazer mais nada agora!"
                    )
                else:
                    # Registra mesmo sem técnico disponível; equipe resolverá manualmente
                    resposta_direta = (
                        f"Sua solicitação para {setor} em {data_str} às {horario_str} foi registrada, "
                        f"mas no momento não há técnicos disponíveis nesse horário. "
                        f"Nossa equipe entrará em contato para verificar a melhor alternativa. "
                        f"Pedimos desculpas pelo inconveniente!"
                    )

                # Limpa dados temporários; mantém agendamento_id para verificar
                # status quando o paciente enviar o próximo follow-up
                dados_agendamento = {}

            else:
                # Dados insuficientes — identifica o que falta e pede diretamente
                # sem acionar o Claude, pois o Claude pode gerar "confirmado" incorretamente
                if not dados_agendamento.get("horario"):
                    resposta_direta = (
                        "Para finalizar seu agendamento, preciso do horário desejado. "
                        "Qual horário você prefere? (ex: 09:00, 14:00)"
                    )
                    novo_estado = EstadosConversa.AGUARDANDO_HORARIO
                elif not dados_agendamento.get("data"):
                    resposta_direta = (
                        "Preciso da data do agendamento. "
                        "Qual data você prefere? (formato DD/MM/AAAA)"
                    )
                    novo_estado = EstadosConversa.AGUARDANDO_DATA
                else:
                    resposta_direta = (
                        "Para finalizar seu agendamento, preciso saber qual serviço você precisa. "
                        f"Opções: {', '.join(SETORES)}"
                    )
                    novo_estado = EstadosConversa.AGENDAMENTO_PENDENTE
                print(f"[WARN] AGENDAMENTO_CONFIRMADO com dados incompletos: "
                      f"setor={setor}, hora_int={hora_int}, data_str={data_str}")

        # ── 6. Conversa livre ─────────────────────────────────────────────────
        # Fora do fluxo de agendamento: Claude responde livremente.
        # Pergunta sobre horários → bot pede o serviço antes de mostrar disponibilidade
        if resposta_direta is None and novo_estado in (EstadosConversa.CONVERSA_LIVRE,
                                                        EstadosConversa.INICIAL):
            pergunta_horario = any(
                w in texto_cliente.lower()
                for w in ["horário", "horario", "disponível", "disponivel",
                           "agenda", "vaga", "quando"]
            )
            if pergunta_horario:
                lista = ", ".join(s for s in SETORES if s != "Outras")
                contexto_extra = (
                    f"O cliente perguntou sobre horários/disponibilidade. "
                    f"Pergunte qual serviço ele precisa para iniciar o agendamento. "
                    f"Opções: {lista}"
                )

        # ── 7. Geração de resposta ────────────────────────────────────────────
        if resposta_direta is not None:
            # Resposta predefinida — bypassa Claude para garantir exatidão
            resposta = resposta_direta
        else:
            # Injeta contexto adicional como bloco [SISTEMA] para guiar o Claude
            msg_para_claude = texto_cliente
            if contexto_extra:
                msg_para_claude += f"\n\n[SISTEMA: {contexto_extra}]"

            resposta = await gerar_resposta(
                numero_cliente,
                msg_para_claude,
                estado=novo_estado,
                historico=historico,
                dados_agendamento=dados_agendamento,
                perfil_cliente=perfil_cliente,
            )
            # Remove qualquer bloco [SISTEMA] que o Claude tenha gerado indevidamente
            resposta = re.sub(r'\[SISTEMA[^\]]*\]', '', resposta, flags=re.DOTALL).strip()

        # ── 8. Persistência e envio ───────────────────────────────────────────
        # Limita o histórico às últimas 10 mensagens para não inflar o contexto do Claude
        historico.append({"role": "user",      "content": texto_cliente})
        historico.append({"role": "assistant", "content": resposta})
        sessao["historico"]         = historico[-10:]
        sessao["estado"]            = novo_estado
        sessao["dados_agendamento"] = dados_agendamento
        salvar_sessao(numero_cliente, sessao)

        # Persiste a interação no MySQL para histórico e auditoria
        salvar_conversa(cliente_id, texto_cliente, resposta)

        # Envia a resposta ao cliente via WhatsApp Business API
        await enviar_mensagem(numero_cliente, resposta)

        print(f"[OK] Estado={novo_estado} | Número={numero_cliente}")
        return JSONResponse({"status": "ok"})

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[ERRO] {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)
