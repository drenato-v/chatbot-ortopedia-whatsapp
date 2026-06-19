import mysql.connector
import os
# Utilizado em agendamentos
from datetime import datetime

def get_connection():
    """
    Cria conexão com MySQL.

    Lê configurações do ambiente
    para evitar credenciais fixas.
    """

    return mysql.connector.connect(

        host=os.getenv(
            "MYSQL_HOST",
            "localhost"
        ),

        user=os.getenv(
            "MYSQL_USER",
            "root"
        ),

        # Senha idealmente vinda do .env
        password=os.getenv(
            "MYSQL_PASSWORD"
        ),

        database=os.getenv(
            "MYSQL_DB",
            "chatbot"
        )
    )

# CLIENTES
def criar_cliente(
    numero_whatsapp: str,
    nome: str = None,
    email: str = None
) -> int:
    
    """
    Cria novo cliente.

    Retorna ID gerado.
    """

    conn = get_connection()

    cursor = conn.cursor()

    try:

        cursor.execute(

            """
            INSERT INTO clientes
            (
                numero_whatsapp,
                nome,
                email
            )
            VALUES
            (%s,%s,%s)
            """,

            (
                numero_whatsapp,
                nome,
                email
            )
        )

        conn.commit()

        return cursor.lastrowid

    finally:

        cursor.close()

        conn.close()



def buscar_cliente_por_numero(
    numero_whatsapp: str
) -> dict:
    """
    Busca cliente pelo número.
    """

    conn = get_connection()

    cursor = conn.cursor(
        dictionary=True
    )

    try:

        cursor.execute(

            """
            SELECT *
            FROM clientes
            WHERE numero_whatsapp=%s
            """,

            (
                numero_whatsapp,
            )
        )

        return cursor.fetchone()

    finally:

        cursor.close()

        conn.close()

# CONVERSAS
def salvar_conversa(
    cliente_id: int,
    mensagem_usuario: str,
    resposta_bot: str
):
    """
    Persiste interação.
    """

    conn = get_connection()

    cursor = conn.cursor()

    try:

        cursor.execute(

            """
            INSERT INTO conversas
            (
                cliente_id,
                mensagem_usuario,
                resposta_bot
            )
            VALUES
            (%s,%s,%s)
            """,

            (
                cliente_id,
                mensagem_usuario,
                resposta_bot
            )
        )

        conn.commit()

    finally:

        cursor.close()

        conn.close()



def buscar_historico(
    cliente_id: int,
    limite: int = 10
) -> list:
    """
    Recupera últimas conversas.
    """

    conn = get_connection()

    cursor = conn.cursor(
        dictionary=True
    )

    try:

        cursor.execute(

            """
            SELECT *
            FROM conversas
            WHERE cliente_id=%s
            ORDER BY created_at DESC
            LIMIT %s
            """,

            (
                cliente_id,
                limite
            )
        )

        # Retorna cronologicamente
        return list(
            reversed(
                cursor.fetchall()
            )
        )

    finally:

        cursor.close()

        conn.close()

# AGENDAMENTOS
def criar_agendamento_em_progresso(
    cliente_id: int
) -> int:
    """
    Cria registro parcial.

    Permite completar dados
    durante conversa.
    """

    conn = get_connection()

    cursor = conn.cursor()

    try:

        cursor.execute(

            """
            INSERT INTO agendamentos
            (
                cliente_id,
                data_agendamento,
                tipo_consulta,
                status
            )

            VALUES
            (%s,%s,%s,%s)
            """,

            (
                cliente_id,
                None,
                None,
                "em_progresso"
            )
        )

        conn.commit()

        return cursor.lastrowid

    finally:

        cursor.close()

        conn.close()

def atualizar_agendamento(
    agendamento_id: int,
    **kwargs
):
    """
    Atualiza somente campos enviados.
    """

    conn = get_connection()

    cursor = conn.cursor()

    try:

        campos = ", ".join(

            [
                f"{k}=%s"

                for k

                in kwargs.keys()
            ]
        )

        valores = (
            list(kwargs.values())
            +
            [agendamento_id]
        )

        cursor.execute(

            f"""
            UPDATE agendamentos
            SET {campos}
            WHERE id=%s
            """,

            valores
        )

        conn.commit()

    finally:

        cursor.close()

        conn.close()



# =====================
# FAQ
# =====================

def buscar_faq(
    categoria: str = None
):
    """
    Busca FAQ completo
    ou filtrado.
    """

    conn = get_connection()

    cursor = conn.cursor(
        dictionary=True
    )

    try:

        if categoria:

            cursor.execute(

                """
                SELECT *
                FROM faq
                WHERE categoria=%s
                """,

                (
                    categoria,
                )
            )

        else:

            cursor.execute(

                """
                SELECT *
                FROM faq
                """
            )

        return cursor.fetchall()

    finally:

        cursor.close()

        conn.close()

def adicionar_faq(
    pergunta: str,
    resposta: str,
    categoria: str = None
):
    """
    Insere nova entrada na FAQ.
    """
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(

            """
            INSERT INTO faq
            (
                pergunta,
                resposta,
                categoria
            )
            VALUES
            (%s, %s, %s)
            """,

            (
                pergunta,
                resposta,
                categoria
            )
        )
        conn.commit()

    finally:
        cursor.close()
        conn.close()

def buscar_agendamento_em_progresso(cliente_id: int) -> dict:
    """
    Busca o agendamento que o cliente está preenchendo
    no momento (status em_progresso). Usada pelo webhook
    para continuar um agendamento já iniciado.
    """
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT *
            FROM agendamentos
            WHERE cliente_id=%s
            AND status='em_progresso'
            ORDER BY id DESC
            LIMIT 1
            """,
            (cliente_id,)
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()


def listar_tecnicos(ativo: bool = True) -> list:
    """
    Lista técnicos cadastrados, agrupáveis por setor.
    """
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT * FROM tecnicos WHERE ativo=%s ORDER BY setor, nome",
            (ativo,)
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def buscar_agendamentos_por_data(data: str) -> list:
    """
    Lista agendamentos de um dia, já com nome do cliente
    e nome/setor do técnico. Usada pelo painel.
    """
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT
                a.id,
                a.data_agendamento,
                a.tipo_consulta,
                a.status,
                c.nome AS cliente_nome,
                c.numero_whatsapp,
                t.nome AS tecnico_nome,
                t.setor AS tecnico_setor
            FROM agendamentos a
            JOIN clientes c ON a.cliente_id = c.id
            LEFT JOIN tecnicos t ON a.tecnico_id = t.id
            WHERE DATE(a.data_agendamento) = %s
            ORDER BY a.data_agendamento
            """,
            (data,)
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def atualizar_status_agendamento(agendamento_id: int, status: str):
    """
    Atualiza somente o status (usada pelo painel
    para confirmar/cancelar agendamentos).
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE agendamentos SET status=%s WHERE id=%s",
            (status, agendamento_id)
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()