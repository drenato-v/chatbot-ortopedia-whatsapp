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
    Retorna técnicos disponíveis considerando modo_atendimento.
    - individual: só aparece se o horário estiver livre
    - compartilhado: aparece mesmo se já tiver agendamento (divide com outro)
    - flexivel: aparece sozinho ou junto dependendo da demanda
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
            ORDER BY
                CASE t.modo_atendimento
                    WHEN 'individual' THEN 1
                    WHEN 'flexivel' THEN 2
                    WHEN 'compartilhado' THEN 3
                END
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

def buscar_agenda_dia(
    tecnico_id: int,
    data: str
) -> List[dict]:
    """
    Retorna o status (disponível ou não) de cada hora do dia
    para um técnico específico. Horas sem registro no banco
    aparecem como indisponíveis (ainda não configuradas).

    Usada pelo painel das atendentes.
    """

    with db_cursor(dictionary=True) as (_, cursor):

        cursor.execute("""
            SELECT hora, disponivel
            FROM disponibilidade_tecnicos
            WHERE tecnico_id = %s
              AND data = %s
        """, (tecnico_id, data))

        registros = cursor.fetchall()

    existentes = {r["hora"]: bool(r["disponivel"]) for r in registros}

    return [
        {"hora": hora, "disponivel": existentes.get(hora, False)}
        for hora in HORARIOS_ATENDIMENTO
    ]


def toggle_disponibilidade(
    tecnico_id: int,
    data: str,
    hora: int
) -> bool:
    """
    Alterna uma hora específica entre disponível/indisponível
    para um técnico em uma data. Cria o registro se não existir.

    Retorna o novo estado (True = ficou disponível).

    Usada pelo painel das atendentes.
    """

    with db_cursor(dictionary=True) as (_, cursor):

        cursor.execute("""
            SELECT disponivel
            FROM disponibilidade_tecnicos
            WHERE tecnico_id = %s
              AND data = %s
              AND hora = %s
        """, (tecnico_id, data, hora))

        row = cursor.fetchone()
        novo_estado = not bool(row["disponivel"]) if row else True

        cursor.execute("""
            INSERT INTO disponibilidade_tecnicos
            (tecnico_id, data, hora, disponivel)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                disponivel = VALUES(disponivel)
        """, (tecnico_id, data, hora, novo_estado))

    return novo_estado