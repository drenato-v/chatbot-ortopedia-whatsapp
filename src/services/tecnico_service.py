from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import List, Optional

from db.mysql import get_connection


HORARIOS_ATENDIMENTO = range(8, 17)


@contextmanager
def db_cursor(dictionary: bool = False):
    """
    Gerencia automaticamente conexão e cursor.

    Fecha recursos mesmo em caso de exceção e realiza rollback
    quando necessário.
    """

    conn = get_connection()
    cursor = conn.cursor(dictionary=dictionary)

    try:
        yield conn, cursor
        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()


def buscar_tecnico_cliente(
    cliente_id: int,
    setor: str
) -> Optional[dict]:
    """
    Retorna o técnico previamente associado ao cliente.
    """

    with db_cursor(dictionary=True) as (_, cursor):

        cursor.execute("""
            SELECT t.*
            FROM cliente_tecnico ct
            INNER JOIN tecnicos t
                ON ct.tecnico_id = t.id
            WHERE ct.cliente_id = %s
              AND ct.setor = %s
            LIMIT 1
        """, (cliente_id, setor))

        return cursor.fetchone()


def buscar_tecnicos_disponiveis(
    data: str,
    hora: int,
    setor: str
) -> List[dict]:
    """
    Retorna técnicos ativos disponíveis.
    """

    with db_cursor(dictionary=True) as (_, cursor):

        cursor.execute("""
            SELECT t.*
            FROM tecnicos t
            INNER JOIN disponibilidade_tecnicos dt
                ON t.id = dt.tecnico_id
            WHERE
                t.setor = %s
                AND t.ativo = TRUE
                AND dt.data = %s
                AND dt.hora = %s
                AND dt.disponivel = TRUE
        """, (setor, data, hora))

        return cursor.fetchall()


def buscar_horarios_disponiveis(
    setor: str,
    data_inicio: str,
    dias: int = 7
) -> dict:
    """
    Retorna disponibilidade consolidada por dia e hora.

    Otimização:
    Faz apenas UMA consulta ao banco.
    """

    inicio = datetime.strptime(data_inicio, "%Y-%m-%d")
    fim = inicio + timedelta(days=dias - 1)

    resultado = {}

    for i in range(dias):
        data = (inicio + timedelta(days=i)).strftime("%Y-%m-%d")

        resultado[data] = [
            {
                "hora": f"{h:02d}:00",
                "disponivel": False,
                "tecnicos_livres": 0
            }
            for h in HORARIOS_ATENDIMENTO
        ]

    with db_cursor(dictionary=True) as (_, cursor):

        cursor.execute("""
            SELECT
                dt.data,
                dt.hora,
                COUNT(*) AS total
            FROM disponibilidade_tecnicos dt

            INNER JOIN tecnicos t
                ON dt.tecnico_id = t.id

            WHERE
                t.setor = %s
                AND t.ativo = TRUE
                AND dt.disponivel = TRUE
                AND dt.data BETWEEN %s AND %s

            GROUP BY
                dt.data,
                dt.hora
        """, (
            setor,
            inicio.strftime("%Y-%m-%d"),
            fim.strftime("%Y-%m-%d")
        ))

        registros = cursor.fetchall()

    for item in registros:

        data = item["data"].strftime("%Y-%m-%d") \
            if hasattr(item["data"], "strftime") \
            else str(item["data"])

        hora = item["hora"]

        if data in resultado:

            indice = hora - 8

            if 0 <= indice < len(resultado[data]):

                resultado[data][indice] = {
                    "hora": f"{hora:02d}:00",
                    "disponivel": item["total"] > 0,
                    "tecnicos_livres": item["total"]
                }

    return resultado


def atribuir_tecnico_cliente(
    cliente_id: int,
    tecnico_id: int,
    setor: str
):
    """
    Cria ou atualiza vínculo cliente → técnico.
    """

    with db_cursor() as (_, cursor):

        cursor.execute("""
            INSERT INTO cliente_tecnico
            (
                cliente_id,
                tecnico_id,
                setor
            )
            VALUES (%s, %s, %s)

            ON DUPLICATE KEY UPDATE
                tecnico_id = VALUES(tecnico_id)
        """, (
            cliente_id,
            tecnico_id,
            setor
        ))


def marcar_hora_como_ocupada(
    tecnico_id: int,
    data: str,
    hora: int
):
    """
    Reserva horário.
    """

    with db_cursor() as (_, cursor):

        cursor.execute("""
            UPDATE disponibilidade_tecnicos
            SET disponivel = FALSE
            WHERE
                tecnico_id = %s
                AND data = %s
                AND hora = %s
        """, (
            tecnico_id,
            data,
            hora
        ))


def liberar_hora(
    tecnico_id: int,
    data: str,
    hora: int
):
    """
    Libera horário reservado.
    """

    with db_cursor() as (_, cursor):

        cursor.execute("""
            UPDATE disponibilidade_tecnicos
            SET disponivel = TRUE
            WHERE
                tecnico_id = %s
                AND data = %s
                AND hora = %s
        """, (
            tecnico_id,
            data,
            hora
        ))