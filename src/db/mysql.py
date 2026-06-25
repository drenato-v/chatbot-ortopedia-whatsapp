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


def buscar_agendamentos_por_data(data: str, tecnico_id: int = None) -> list:
    """
    Lista agendamentos confirmados e pendentes de uma data específica.
    Se tecnico_id fornecido, filtra agendamentos onde ele é técnico principal ou secundário.
    """
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        filtro_tec = "AND (a.tecnico_id = %s OR a.tecnico_id_2 = %s)" if tecnico_id else ""
        params     = (data, tecnico_id, tecnico_id) if tecnico_id else (data,)
        cursor.execute(
            f"""
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
              {filtro_tec}
            ORDER BY a.horario, a.data_agendamento
            """,
            params,
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


def buscar_agendamentos_por_nome(nome: str, limite: int = 60) -> list:
    """
    Busca agendamentos por nome do paciente, independente de data.
    Pesquisa tanto em agendamentos manuais (nome_paciente) quanto em clientes
    do WhatsApp (clientes.nome). Útil para localizar um agendamento sem saber a data.
    """
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        like = f"{nome.lower()}%"
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
            WHERE LOWER(COALESCE(a.nome_paciente, c.nome)) LIKE %s
              AND a.status NOT IN ('em_progresso', 'cancelado')
            ORDER BY a.data_agendamento DESC, a.horario
            LIMIT %s
            """,
            (like, limite),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def verificar_paciente_por_nome_telefone(nome: str, telefone: str) -> bool:
    """
    Verifica se existe paciente/cliente com esse nome e telefone no banco.
    Compara os últimos 8 dígitos do telefone para tolerar variações de formato.
    Busca em pacientes, clientes e agendamentos.
    """
    import re as _re
    digits = _re.sub(r'\D', '', telefone)
    if len(digits) < 8:
        return False
    suffix   = digits[-8:]
    like_tel = f"%{suffix}"
    nome_l   = nome.lower().strip()
    conn     = get_connection()
    cursor   = conn.cursor()
    try:
        # Pacientes presenciais
        cursor.execute(
            """SELECT 1 FROM pacientes
               WHERE LOWER(nome) = %s
                 AND REPLACE(REPLACE(REPLACE(REPLACE(IFNULL(telefone,''), '-',''),' ',''),'(',''),')','') LIKE %s
               LIMIT 1""",
            (nome_l, like_tel),
        )
        if cursor.fetchone():
            return True
        # Clientes WhatsApp
        cursor.execute(
            """SELECT 1 FROM clientes
               WHERE LOWER(IFNULL(nome,'')) = %s
                 AND REPLACE(REPLACE(REPLACE(REPLACE(IFNULL(numero_whatsapp,''), '-',''),' ',''),'(',''),')','') LIKE %s
               LIMIT 1""",
            (nome_l, like_tel),
        )
        if cursor.fetchone():
            return True
        # Agendamentos (nome_paciente + telefone_paciente)
        cursor.execute(
            """SELECT 1 FROM agendamentos
               WHERE LOWER(IFNULL(nome_paciente,'')) = %s
                 AND REPLACE(REPLACE(REPLACE(REPLACE(IFNULL(telefone_paciente,''), '-',''),' ',''),'(',''),')','') LIKE %s
               LIMIT 1""",
            (nome_l, like_tel),
        )
        return bool(cursor.fetchone())
    finally:
        cursor.close()
        conn.close()


def verificar_presenca_paciente(nome: str, telefone: str) -> dict:
    """
    Retorna o registro de pacientes (com CPF) se nome + telefone baterem.
    Retorna None quando o paciente nunca foi atendido presencialmente.
    Usado no cancelamento para decidir se pede CPF como verificação extra.
    """
    import re as _re
    digits = _re.sub(r'\D', '', telefone)
    if len(digits) < 8:
        return None
    suffix   = digits[-8:]
    like_tel = f"%{suffix}"
    nome_l   = nome.lower().strip()
    conn     = get_connection()
    cursor   = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """SELECT id, nome, cpf FROM pacientes
               WHERE LOWER(nome) = %s
                 AND REPLACE(REPLACE(REPLACE(REPLACE(IFNULL(telefone,''), '-',''),' ',''),'(',''),')','') LIKE %s
               LIMIT 1""",
            (nome_l, like_tel),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()


def verificar_cpf_paciente(nome: str, cpf: str) -> bool:
    """
    Verifica se o CPF informado corresponde ao paciente no banco.
    Compara apenas dígitos para tolerar variações de formatação (xxx.xxx.xxx-xx).
    """
    import re as _re
    cpf_digits = _re.sub(r'\D', '', cpf)
    if len(cpf_digits) < 11:
        return False
    nome_l = nome.lower().strip()
    conn   = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """SELECT 1 FROM pacientes
               WHERE LOWER(nome) = %s
                 AND REPLACE(REPLACE(cpf, '.', ''), '-', '') = %s
               LIMIT 1""",
            (nome_l, cpf_digits),
        )
        return bool(cursor.fetchone())
    finally:
        cursor.close()
        conn.close()


def buscar_agendamento_por_cliente_e_data(cliente_id: int, data_str: str) -> dict:
    """
    Retorna o agendamento ativo (pendente ou confirmado) do cliente em uma data específica.
    data_str deve estar no formato DD/MM/YYYY.
    """
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        data_mysql = datetime.strptime(data_str, "%d/%m/%Y").strftime("%Y-%m-%d")
        cursor.execute(
            """
            SELECT a.id, a.data_agendamento, a.horario, a.tipo_consulta,
                   a.status, a.tecnico_id, a.tecnico_id_2,
                   a.telefone_paciente,
                   COALESCE(a.nome_paciente, c.nome) AS nome_paciente,
                   c.numero_whatsapp
            FROM agendamentos a
            LEFT JOIN clientes c ON a.cliente_id = c.id
            WHERE a.cliente_id = %s
              AND DATE(a.data_agendamento) = %s
              AND a.status IN ('pendente', 'confirmado')
            ORDER BY a.id DESC
            LIMIT 1
            """,
            (cliente_id, data_mysql),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()


def buscar_agendamento_ativo_por_cliente(cliente_id: int) -> dict:
    """
    Retorna o agendamento mais recente pendente ou confirmado do cliente.
    Usado pelo bot para identificar qual agendamento cancelar ao reagendar.
    """
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT a.id, a.data_agendamento, a.horario, a.tipo_consulta,
                   a.status, a.tecnico_id, a.tecnico_id_2,
                   COALESCE(a.nome_paciente, c.nome) AS nome_paciente,
                   c.numero_whatsapp
            FROM agendamentos a
            LEFT JOIN clientes c ON a.cliente_id = c.id
            WHERE a.cliente_id = %s
              AND a.status IN ('pendente', 'confirmado')
            ORDER BY a.data_agendamento DESC, a.id DESC
            LIMIT 1
            """,
            (cliente_id,),
        )
        return cursor.fetchone()
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

# ── Usuários do sistema ───────────────────────────────────────────────────────

def buscar_usuario_por_email(email: str) -> dict:
    """
    Busca um usuário pelo e-mail para autenticação.
    Retorna None se não encontrado — o caller verifica ativo e valida a senha.
    """
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM usuarios WHERE email = %s", (email,))
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()


def criar_usuario(nome: str, email: str, password_hash: str, role: str,
                  especialidade: str = None, tecnico_id: int = None) -> int:
    conn   = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO usuarios (nome, email, password_hash, role, especialidade, tecnico_id) VALUES (%s,%s,%s,%s,%s,%s)",
            (nome, email, password_hash, role, especialidade, tecnico_id),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        conn.close()


def listar_usuarios() -> list:
    """Lista todos os usuários cadastrados, ordenados por role e nome."""
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # password_hash excluído intencionalmente — nunca trafegar hashes desnecessariamente
        cursor.execute(
            "SELECT id, nome, email, role, especialidade, tecnico_id, ativo, created_at FROM usuarios ORDER BY role, nome"
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def atualizar_usuario(usuario_id: int, **kwargs):
    """
    Atualiza somente os campos passados como kwargs.
    Segue o mesmo padrão de atualizar_agendamento — dinâmico para não precisar
    de uma função por campo.
    """
    if not kwargs:
        return
    conn   = get_connection()
    cursor = conn.cursor()
    try:
        campos = ", ".join(f"{k} = %s" for k in kwargs.keys())
        valores = list(kwargs.values()) + [usuario_id]
        cursor.execute(f"UPDATE usuarios SET {campos} WHERE id = %s", valores)
        conn.commit()
    finally:
        cursor.close()
        conn.close()


# ── Pacientes ────────────────────────────────────────────────────────────────

def buscar_pacientes(query: str, limite: int = 30) -> list:
    """
    Busca pacientes por nome ou telefone (correspondência parcial, case-insensitive).
    Inclui o número do WhatsApp vinculado e a contagem de fichas abertas.
    """
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # LOWER() nos dois lados garante correspondência case-insensitive
        # independente do collation configurado no servidor MySQL
        like = f"{query.lower()}%"
        cursor.execute(
            """
            SELECT p.id, p.nome, p.telefone, p.cpf, p.created_at,
                   c.numero_whatsapp,
                   (SELECT COUNT(*) FROM fichas f WHERE f.paciente_id = p.id) AS total_fichas
            FROM pacientes p
            LEFT JOIN clientes c ON p.cliente_id = c.id
            WHERE LOWER(p.nome)          LIKE %s
               OR LOWER(p.telefone)      LIKE %s
               OR LOWER(c.numero_whatsapp) LIKE %s
            ORDER BY p.nome
            LIMIT %s
            """,
            (like, like, like, limite),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def buscar_paciente_por_id(paciente_id: int) -> dict:
    """Retorna o paciente com todos os campos e número do WhatsApp se vinculado."""
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT p.*, c.numero_whatsapp
            FROM pacientes p
            LEFT JOIN clientes c ON p.cliente_id = c.id
            WHERE p.id = %s
            """,
            (paciente_id,),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()


def buscar_paciente_por_cliente_id(cliente_id: int) -> dict:
    """Retorna o paciente vinculado ao cliente do WhatsApp, se já existir."""
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM pacientes WHERE cliente_id = %s", (cliente_id,))
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()


def criar_paciente(
    nome: str,
    telefone: str = None,
    cliente_id: int = None,
    cpf: str = None,
    data_nascimento=None,
    endereco: str = None,
    plano_saude: str = None,
    medico_responsavel: str = None,
    atendido_por_id: int = None,
    atendido_por_nome: str = None,
) -> int:
    """Insere um novo paciente e retorna o ID gerado."""
    conn   = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO pacientes
                (nome, telefone, cliente_id, cpf, data_nascimento, endereco,
                 plano_saude, medico_responsavel, atendido_por_id, atendido_por_nome)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (nome, telefone, cliente_id, cpf, data_nascimento, endereco,
             plano_saude, medico_responsavel, atendido_por_id, atendido_por_nome),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        conn.close()


def atualizar_paciente(paciente_id: int, **kwargs):
    """Atualiza somente os campos passados como kwargs."""
    if not kwargs:
        return
    conn   = get_connection()
    cursor = conn.cursor()
    try:
        campos  = ", ".join(f"{k} = %s" for k in kwargs.keys())
        valores = list(kwargs.values()) + [paciente_id]
        cursor.execute(f"UPDATE pacientes SET {campos} WHERE id = %s", valores)
        conn.commit()
    finally:
        cursor.close()
        conn.close()


# ── Fichas ────────────────────────────────────────────────────────────────────

def criar_ficha(paciente_id: int, tipo_servico: str, agendamento_id: int = None) -> int:
    """
    Cria uma nova ficha de acompanhamento iniciando em 'Atendimento'.
    agendamento_id é None para pacientes presenciais sem agendamento prévio.
    """
    conn   = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO fichas (paciente_id, agendamento_id, tipo_servico, etapa_atual)
            VALUES (%s, %s, %s, 'Atendimento')
            """,
            (paciente_id, agendamento_id, tipo_servico),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        conn.close()


def buscar_fichas_do_paciente(paciente_id: int) -> list:
    """
    Retorna todas as fichas do paciente em ordem cronológica inversa,
    cada uma com o histórico completo de etapas.
    """
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT f.*,
                   a.data_agendamento, a.horario
            FROM fichas f
            LEFT JOIN agendamentos a ON f.agendamento_id = a.id
            WHERE f.paciente_id = %s
            ORDER BY f.created_at DESC
            """,
            (paciente_id,),
        )
        fichas = cursor.fetchall()
        for ficha in fichas:
            cursor.execute(
                """
                SELECT * FROM ficha_historico
                WHERE ficha_id = %s
                ORDER BY created_at ASC
                """,
                (ficha["id"],),
            )
            ficha["historico"] = cursor.fetchall()
        return fichas
    finally:
        cursor.close()
        conn.close()


def buscar_ficha_por_agendamento(agendamento_id: int) -> dict:
    """Retorna a ficha vinculada a um agendamento, ou None se não existir."""
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM fichas WHERE agendamento_id = %s", (agendamento_id,))
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()


def atualizar_ficha(ficha_id: int, etapa_atual: str, status_orcamento: str = None):
    """Atualiza a etapa atual e, opcionalmente, o sub-status do orçamento."""
    conn   = get_connection()
    cursor = conn.cursor()
    try:
        if status_orcamento:
            cursor.execute(
                "UPDATE fichas SET etapa_atual = %s, status_orcamento = %s WHERE id = %s",
                (etapa_atual, status_orcamento, ficha_id),
            )
        else:
            cursor.execute(
                "UPDATE fichas SET etapa_atual = %s WHERE id = %s",
                (etapa_atual, ficha_id),
            )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


# ── Histórico de ficha ────────────────────────────────────────────────────────

def adicionar_historico(
    ficha_id: int,
    etapa: str,
    usuario_id: int,
    usuario_nome: str,
    descricao: str = None,
):
    """
    Registra uma nova entrada no histórico da ficha.
    usuario_nome é denormalizado para preservar o rastro auditável mesmo
    se o usuário for excluído ou renomeado futuramente.
    """
    conn   = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO ficha_historico (ficha_id, etapa, descricao, usuario_id, usuario_nome)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (ficha_id, etapa, descricao, usuario_id, usuario_nome),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


# ── Estoque ───────────────────────────────────────────────────────────────────

def listar_estoque_produtos(apenas_ativos: bool = True) -> list:
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        sql = "SELECT * FROM estoque_produtos"
        if apenas_ativos:
            sql += " WHERE ativo = TRUE"
        sql += " ORDER BY categoria, nome"
        cursor.execute(sql)
        return cursor.fetchall()
    finally:
        cursor.close(); conn.close()


def buscar_estoque_produto_por_id(produto_id: int) -> dict:
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM estoque_produtos WHERE id = %s", (produto_id,))
        return cursor.fetchone()
    finally:
        cursor.close(); conn.close()


def criar_estoque_produto(nome: str, categoria: str, unidade: str = "un",
                          quantidade_minima: float = 0, descricao: str = None,
                          lado: str = None, cor: str = None, tamanho: str = None) -> int:
    conn   = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """INSERT INTO estoque_produtos
               (nome, categoria, unidade, quantidade_minima, descricao, lado, cor, tamanho)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (nome, categoria, unidade, quantidade_minima, descricao, lado or None, cor or None, tamanho or None),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        cursor.close(); conn.close()


def atualizar_estoque_produto(produto_id: int, **kwargs):
    if not kwargs:
        return
    conn   = get_connection()
    cursor = conn.cursor()
    try:
        campos = ", ".join(f"{k} = %s" for k in kwargs)
        cursor.execute(f"UPDATE estoque_produtos SET {campos} WHERE id = %s",
                       list(kwargs.values()) + [produto_id])
        conn.commit()
    finally:
        cursor.close(); conn.close()


def registrar_movimento_estoque(produto_id: int, tipo: str, quantidade: float,
                                usuario_id: int, usuario_nome: str,
                                motivo: str = None, solicitacao_id: int = None):
    conn   = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """INSERT INTO estoque_movimentos
               (produto_id, tipo, quantidade, motivo, solicitacao_id, usuario_id, usuario_nome)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (produto_id, tipo, quantidade, motivo, solicitacao_id, usuario_id, usuario_nome),
        )
        # Atualiza quantidade_atual: entrada/ajuste soma, saída subtrai
        if tipo in ("entrada", "ajuste_entrada"):
            cursor.execute(
                "UPDATE estoque_produtos SET quantidade_atual = quantidade_atual + %s WHERE id = %s",
                (quantidade, produto_id),
            )
        elif tipo == "saida":
            cursor.execute(
                "UPDATE estoque_produtos SET quantidade_atual = GREATEST(0, quantidade_atual - %s) WHERE id = %s",
                (quantidade, produto_id),
            )
        elif tipo == "ajuste":
            cursor.execute(
                "UPDATE estoque_produtos SET quantidade_atual = %s WHERE id = %s",
                (quantidade, produto_id),
            )
        conn.commit()
    finally:
        cursor.close(); conn.close()


def buscar_movimentos_produto(produto_id: int, limite: int = 50) -> list:
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """SELECT m.*, p.nome AS produto_nome FROM estoque_movimentos m
               JOIN estoque_produtos p ON m.produto_id = p.id
               WHERE m.produto_id = %s
               ORDER BY m.created_at DESC LIMIT %s""",
            (produto_id, limite),
        )
        rows = cursor.fetchall()
        for r in rows:
            if hasattr(r.get("created_at"), "isoformat"):
                r["created_at"] = r["created_at"].isoformat()
        return rows
    finally:
        cursor.close(); conn.close()


def excluir_movimento(movimento_id: int) -> bool:
    conn   = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM estoque_movimentos WHERE id = %s", (movimento_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close(); conn.close()


def excluir_historico_produto(produto_id: int) -> int:
    conn   = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM estoque_movimentos WHERE produto_id = %s", (produto_id,))
        conn.commit()
        return cursor.rowcount
    finally:
        cursor.close(); conn.close()


def criar_solicitacao_estoque(produto_id: int, tipo: str, quantidade: float,
                              motivo: str, solicitante_id: int, solicitante_nome: str) -> int:
    conn   = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """INSERT INTO estoque_solicitacoes
               (produto_id, tipo, quantidade, motivo, solicitante_id, solicitante_nome)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (produto_id, tipo, quantidade, motivo, solicitante_id, solicitante_nome),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        cursor.close(); conn.close()


def listar_solicitacoes_estoque(status_filtro: str = None) -> list:
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        sql = """SELECT s.*, p.nome AS produto_nome, p.unidade
                 FROM estoque_solicitacoes s
                 JOIN estoque_produtos p ON s.produto_id = p.id"""
        params = []
        if status_filtro:
            sql += " WHERE s.status = %s"
            params.append(status_filtro)
        sql += " ORDER BY s.created_at DESC LIMIT 100"
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        for r in rows:
            for f in ("created_at", "updated_at"):
                if hasattr(r.get(f), "isoformat"):
                    r[f] = r[f].isoformat()
        return rows
    finally:
        cursor.close(); conn.close()


def responder_solicitacao_estoque(solicitacao_id: int, aprovado: bool,
                                  aprovador_id: int, aprovador_nome: str,
                                  observacao: str = None) -> dict:
    """Aprova ou rejeita uma solicitação. Se aprovada, registra o movimento."""
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM estoque_solicitacoes WHERE id = %s", (solicitacao_id,))
        sol = cursor.fetchone()
        if not sol or sol["status"] != "pendente":
            return None
        novo_status = "aprovada" if aprovado else "rejeitada"
        cursor.execute(
            """UPDATE estoque_solicitacoes
               SET status=%s, aprovador_id=%s, aprovador_nome=%s, observacao_resposta=%s
               WHERE id=%s""",
            (novo_status, aprovador_id, aprovador_nome, observacao, solicitacao_id),
        )
        if aprovado:
            if sol["tipo"] == "entrada":
                cursor.execute(
                    "UPDATE estoque_produtos SET quantidade_atual = quantidade_atual + %s WHERE id = %s",
                    (sol["quantidade"], sol["produto_id"]),
                )
            else:
                cursor.execute(
                    "UPDATE estoque_produtos SET quantidade_atual = GREATEST(0, quantidade_atual - %s) WHERE id = %s",
                    (sol["quantidade"], sol["produto_id"]),
                )
            cursor.execute(
                """INSERT INTO estoque_movimentos
                   (produto_id, tipo, quantidade, motivo, solicitacao_id, usuario_id, usuario_nome)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (sol["produto_id"], sol["tipo"], sol["quantidade"],
                 sol.get("motivo"), solicitacao_id, aprovador_id, aprovador_nome),
            )
        conn.commit()
        return sol
    finally:
        cursor.close(); conn.close()


def criar_notificacao(mensagem: str, tipo: str = "cancelamento"):
    """Insere uma nova notificação para o painel."""
    conn   = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO notificacoes (tipo, mensagem) VALUES (%s, %s)",
            (tipo, mensagem),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def buscar_notificacoes(apenas_nao_lidas: bool = False, limite: int = 30) -> list:
    """Retorna notificações em ordem decrescente de criação."""
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        sql = "SELECT * FROM notificacoes"
        if apenas_nao_lidas:
            sql += " WHERE lida = FALSE"
        sql += " ORDER BY created_at DESC LIMIT %s"
        cursor.execute(sql, (limite,))
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def marcar_notificacao_lida(notificacao_id: int):
    """Marca uma notificação específica como lida."""
    conn   = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE notificacoes SET lida = TRUE WHERE id = %s", (notificacao_id,))
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def marcar_todas_notificacoes_lidas():
    """Marca todas as notificações como lidas."""
    conn   = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE notificacoes SET lida = TRUE WHERE lida = FALSE")
        conn.commit()
    finally:
        cursor.close()
        conn.close()


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
