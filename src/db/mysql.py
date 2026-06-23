# Driver MySQL para Python
import mysql.connector
# Leitura das credenciais via variáveis de ambiente
import os
from datetime import datetime


def get_connection():
    """
    Abre e retorna uma nova conexão com o banco MySQL.

    Credenciais lidas do ambiente (.env) para nunca ficarem hardcoded.
    Cada função que usa o banco abre e fecha sua própria conexão —
    evita conexões abertas sem uso mas adiciona overhead por chamada.
    """
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DB", "chatbot"),
    )


# ── Clientes ──────────────────────────────────────────────────────────────────

def criar_cliente(numero_whatsapp: str, nome: str = None, email: str = None) -> int:
    """
    Insere um novo cliente e retorna o ID gerado.
    Chamado na primeira mensagem recebida de um número ainda não cadastrado.
    """
    conn   = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO clientes (numero_whatsapp, nome, email) VALUES (%s, %s, %s)",
            (numero_whatsapp, nome, email),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        conn.close()


def buscar_cliente_por_numero(numero_whatsapp: str) -> dict:
    """Busca um cliente pelo número do WhatsApp. Retorna None se não existir."""
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT * FROM clientes WHERE numero_whatsapp = %s",
            (numero_whatsapp,),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()


def atualizar_nome_cliente(cliente_id: int, nome: str):
    """
    Atualiza o nome do cliente somente se ainda estiver em branco.

    Condição 'AND nome IS NULL' evita sobrescrever um nome já cadastrado
    caso o cliente mande uma segunda mensagem durante o fluxo.
    """
    conn   = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE clientes SET nome = %s WHERE id = %s AND nome IS NULL",
            (nome, cliente_id),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


# ── Conversas ─────────────────────────────────────────────────────────────────

def salvar_conversa(cliente_id: int, mensagem_usuario: str, resposta_bot: str):
    """
    Persiste cada interação usuário↔bot no MySQL.
    Usado para auditoria, análise posterior e histórico completo.
    """
    conn   = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO conversas (cliente_id, mensagem_usuario, resposta_bot)
            VALUES (%s, %s, %s)
            """,
            (cliente_id, mensagem_usuario, resposta_bot),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def buscar_historico(cliente_id: int, limite: int = 10) -> list:
    """
    Retorna as últimas N interações de um cliente em ordem cronológica.
    Busca em ordem DESC e inverte para manter a sequência correta.
    """
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT * FROM conversas
            WHERE cliente_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (cliente_id, limite),
        )
        return list(reversed(cursor.fetchall()))
    finally:
        cursor.close()
        conn.close()


# ── Agendamentos ──────────────────────────────────────────────────────────────

def criar_agendamento_em_progresso(cliente_id: int) -> int:
    """
    Cria um registro parcial de agendamento com status 'em_progresso'.

    Criado logo no início do fluxo (quando o serviço é identificado) para
    permitir atualizações incrementais à medida que o bot coleta os dados.
    Retorna o ID gerado para ser armazenado na sessão Redis.
    """
    conn   = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO agendamentos
                (cliente_id, data_agendamento, tipo_consulta, status, origem)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (cliente_id, None, None, "em_progresso", "whatsapp"),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        conn.close()


def atualizar_agendamento(agendamento_id: int, **kwargs):
    """
    Atualiza somente os campos passados como kwargs.

    Usa geração dinâmica de SQL para não precisar de uma função por campo.
    Ignora chamadas sem kwargs para evitar SQL inválido.
    """
    if not kwargs:
        return

    conn   = get_connection()
    cursor = conn.cursor()
    try:
        # Monta "campo1=%s, campo2=%s, ..." para cada kwarg recebido
        campos = ", ".join(f"{k} = %s" for k in kwargs.keys())
        valores = list(kwargs.values()) + [agendamento_id]
        cursor.execute(f"UPDATE agendamentos SET {campos} WHERE id = %s", valores)
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def buscar_agendamento_em_progresso(cliente_id: int) -> dict:
    """
    Retorna o agendamento mais recente com status 'em_progresso' para o cliente.

    Usado como fallback de recuperação: se a sessão Redis perdeu o agendamento_id
    (reinicialização do servidor, expiração de TTL), o webhook pode restaurá-lo
    consultando o banco para não interromper o fluxo em andamento.
    """
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT * FROM agendamentos
            WHERE cliente_id = %s AND status = 'em_progresso'
            ORDER BY id DESC LIMIT 1
            """,
            (cliente_id,),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()


def buscar_agendamento_por_id(agendamento_id: int) -> dict:
    """
    Retorna um agendamento completo pelo ID, incluindo número do WhatsApp do cliente
    e nome do técnico principal (necessários para envio da notificação pós-confirmação).
    """
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT a.*, c.numero_whatsapp, t.nome AS tecnico_nome
            FROM agendamentos a
            LEFT JOIN clientes c ON a.cliente_id = c.id
            LEFT JOIN tecnicos  t ON a.tecnico_id  = t.id
            WHERE a.id = %s
            """,
            (agendamento_id,),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()


def atualizar_status_agendamento(agendamento_id: int, status: str):
    """
    Atualiza somente o status de um agendamento.
    Usada pelo painel para confirmar ('confirmado') ou cancelar ('cancelado').
    """
    conn   = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE agendamentos SET status = %s WHERE id = %s",
            (status, agendamento_id),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def buscar_agendamentos_por_data(data: str) -> list:
    """
    Lista agendamentos confirmados e pendentes de uma data específica.
    Inclui dados do cliente, técnicos principal e secundário.
    Exclui agendamentos em_progresso (incompletos) e cancelados.
    """
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT
                a.id,
                a.data_agendamento,
                a.horario,
                a.tipo_consulta,
                a.status,
                a.origem,
                a.observacoes,
                a.tecnico_id,
                a.tecnico_id_2,
                a.telefone_paciente,
                COALESCE(a.nome_paciente, c.nome) AS cliente_nome,
                c.numero_whatsapp,
                t.nome  AS tecnico_nome,
                t.setor AS tecnico_setor,
                t2.nome AS tecnico_nome_2
            FROM agendamentos a
            LEFT JOIN clientes c  ON a.cliente_id  = c.id
            LEFT JOIN tecnicos t  ON a.tecnico_id  = t.id
            LEFT JOIN tecnicos t2 ON a.tecnico_id_2 = t2.id
            WHERE DATE(a.data_agendamento) = %s
              AND a.status NOT IN ('em_progresso', 'cancelado')
            ORDER BY a.horario, a.data_agendamento
            """,
            (data,),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def buscar_agendamentos_pendentes() -> list:
    """
    Lista todos os agendamentos aguardando aprovação do painel (status 'pendente').

    Independente de data — o painel exibe todos os pendentes de qualquer período,
    ordenados por data/hora crescente para facilitar a triagem pelas atendentes.
    """
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT
                a.id,
                a.data_agendamento,
                a.horario,
                a.tipo_consulta,
                a.status,
                a.origem,
                a.observacoes,
                a.tecnico_id,
                a.tecnico_id_2,
                a.telefone_paciente,
                COALESCE(a.nome_paciente, c.nome) AS cliente_nome,
                c.numero_whatsapp,
                t.nome  AS tecnico_nome,
                t.setor AS tecnico_setor,
                t2.nome AS tecnico_nome_2
            FROM agendamentos a
            LEFT JOIN clientes c  ON a.cliente_id   = c.id
            LEFT JOIN tecnicos t  ON a.tecnico_id   = t.id
            LEFT JOIN tecnicos t2 ON a.tecnico_id_2 = t2.id
            WHERE a.status = 'pendente'
            ORDER BY a.data_agendamento ASC, a.horario ASC
            """
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def criar_agendamento_manual(
    tecnico_id: int,
    data_agendamento,
    horario: str,
    tipo_consulta: str,
    nome_paciente: str,
    observacoes: str = None,
    tecnico_id_2: int = None,
) -> int:
    """
    Insere um agendamento criado diretamente pelo painel (origem='manual').
    Já nasce com status 'confirmado' pois a atendente é quem está criando.
    Retorna o ID do registro criado.
    """
    conn   = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO agendamentos
                (tecnico_id, tecnico_id_2, data_agendamento, horario, tipo_consulta,
                 status, origem, nome_paciente, observacoes)
            VALUES (%s, %s, %s, %s, %s, 'confirmado', 'manual', %s, %s)
            """,
            (tecnico_id, tecnico_id_2, data_agendamento, horario,
             tipo_consulta, nome_paciente, observacoes),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        conn.close()


# ── FAQ ───────────────────────────────────────────────────────────────────────

def buscar_faq(categoria: str = None) -> list:
    """
    Retorna todo o FAQ ou apenas entradas de uma categoria específica.
    O resultado é injetado no system prompt do Claude para responder perguntas frequentes.
    """
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        if categoria:
            cursor.execute("SELECT * FROM faq WHERE categoria = %s", (categoria,))
        else:
            cursor.execute("SELECT * FROM faq")
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def adicionar_faq(pergunta: str, resposta: str, categoria: str = None):
    """Insere uma nova entrada na base de conhecimento (FAQ)."""
    conn   = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO faq (pergunta, resposta, categoria) VALUES (%s, %s, %s)",
            (pergunta, resposta, categoria),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


# ── Técnicos ──────────────────────────────────────────────────────────────────

def listar_tecnicos(ativo: bool = True) -> list:
    """
    Lista técnicos cadastrados, ordenados por setor e nome.
    Usado pelo painel para popular selects de técnicos.
    """
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT * FROM tecnicos WHERE ativo = %s ORDER BY setor, nome",
            (ativo,),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


# ── Perfil do cliente ─────────────────────────────────────────────────────────

def buscar_servicos_cliente(cliente_id: int) -> list:
    """
    Retorna os serviços que o cliente já solicitou, ordenados por frequência.

    Usado para injetar perfil de cliente recorrente no system prompt do Claude,
    permitindo um atendimento mais personalizado.
    """
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT tipo_consulta, COUNT(*) AS total
            FROM agendamentos
            WHERE cliente_id = %s
              AND status IN ('confirmado', 'pendente')
              AND tipo_consulta IS NOT NULL
            GROUP BY tipo_consulta
            ORDER BY total DESC
            """,
            (cliente_id,),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()
