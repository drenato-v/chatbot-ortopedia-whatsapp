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
    Disponível por padrão — só fica bloqueado se houver registro
    explícito com disponivel=FALSE na tabela disponibilidade_tecnicos.
    """
    with db_cursor(dictionary=True) as (_, cursor):
        cursor.execute("""
            SELECT t.*
            FROM tecnicos t
            WHERE t.setor = %s
              AND t.ativo = TRUE
              AND NOT EXISTS (
                SELECT 1 FROM disponibilidade_tecnicos dt
                WHERE dt.tecnico_id = t.id
                  AND dt.data = %s
                  AND dt.hora = %s
                  AND dt.disponivel = FALSE
              )
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
    Todos os horários começam disponíveis; apenas os com
    bloqueio explícito (disponivel=FALSE) reduzem o contador.
    """

    inicio = datetime.strptime(data_inicio, "%Y-%m-%d")
    fim = inicio + timedelta(days=dias - 1)

    with db_cursor(dictionary=True) as (_, cursor):
        cursor.execute(
            "SELECT COUNT(*) AS total FROM tecnicos WHERE setor = %s AND ativo = TRUE",
            (setor,)
        )
        total_tecnicos = cursor.fetchone()["total"]

    resultado = {}
    for i in range(dias):
        data = (inicio + timedelta(days=i)).strftime("%Y-%m-%d")
        resultado[data] = [
            {
                "hora": f"{h:02d}:00",
                "disponivel": total_tecnicos > 0,
                "tecnicos_livres": total_tecnicos
            }
            for h in HORARIOS_ATENDIMENTO
        ]

    if total_tecnicos == 0:
        return resultado

    data_ini_str = inicio.strftime("%Y-%m-%d")
    data_fim_str = fim.strftime("%Y-%m-%d")

    with db_cursor(dictionary=True) as (_, cursor):
        # Conta técnicos distintos bloqueados por data/hora, considerando:
        # 1. Bloqueios manuais em disponibilidade_tecnicos
        # 2. Agendamentos confirmados (técnico principal)
        # 3. Agendamentos confirmados (segundo técnico)
        cursor.execute("""
            SELECT data, hora, COUNT(DISTINCT tecnico_id) AS bloqueados
            FROM (
                SELECT dt.tecnico_id, dt.data, dt.hora
                FROM disponibilidade_tecnicos dt
                INNER JOIN tecnicos t ON dt.tecnico_id = t.id
                WHERE t.setor = %s AND t.ativo = TRUE
                  AND dt.disponivel = FALSE
                  AND dt.data BETWEEN %s AND %s

                UNION

                SELECT a.tecnico_id,
                       DATE(a.data_agendamento) AS data,
                       CAST(SUBSTRING_INDEX(a.horario, ':', 1) AS UNSIGNED) AS hora
                FROM agendamentos a
                INNER JOIN tecnicos t ON a.tecnico_id = t.id
                WHERE t.setor = %s AND t.ativo = TRUE
                  AND a.status NOT IN ('cancelado', 'em_progresso')
                  AND DATE(a.data_agendamento) BETWEEN %s AND %s
                  AND a.horario IS NOT NULL

                UNION

                SELECT a.tecnico_id_2,
                       DATE(a.data_agendamento) AS data,
                       CAST(SUBSTRING_INDEX(a.horario, ':', 1) AS UNSIGNED) AS hora
                FROM agendamentos a
                INNER JOIN tecnicos t2 ON a.tecnico_id_2 = t2.id
                WHERE t2.setor = %s AND t2.ativo = TRUE
                  AND a.status NOT IN ('cancelado', 'em_progresso')
                  AND DATE(a.data_agendamento) BETWEEN %s AND %s
                  AND a.horario IS NOT NULL
                  AND a.tecnico_id_2 IS NOT NULL
            ) AS ocupados
            GROUP BY data, hora
        """, (
            setor, data_ini_str, data_fim_str,
            setor, data_ini_str, data_fim_str,
            setor, data_ini_str, data_fim_str,
        ))
        bloqueios = cursor.fetchall()

    for item in bloqueios:
        data = item["data"].strftime("%Y-%m-%d") \
            if hasattr(item["data"], "strftime") \
            else str(item["data"])
        hora = item["hora"]
        if data in resultado:
            indice = hora - 8
            if 0 <= indice < len(resultado[data]):
                livres = total_tecnicos - item["bloqueados"]
                resultado[data][indice] = {
                    "hora": f"{hora:02d}:00",
                    "disponivel": livres > 0,
                    "tecnicos_livres": livres
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
    Reserva horário. Cria o registro se ainda não existir.
    """

    with db_cursor() as (_, cursor):

        cursor.execute("""
            INSERT INTO disponibilidade_tecnicos
                (tecnico_id, data, hora, disponivel)
            VALUES (%s, %s, %s, FALSE)
            ON DUPLICATE KEY UPDATE disponivel = FALSE
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
    Libera horário reservado. Remove o registro para voltar ao padrão disponível.
    """

    with db_cursor() as (_, cursor):

        cursor.execute("""
            DELETE FROM disponibilidade_tecnicos
            WHERE tecnico_id = %s AND data = %s AND hora = %s
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
    Retorna status e agendamento de cada hora do dia para um técnico.
    Horas sem bloqueio explícito aparecem como disponíveis.
    """

    with db_cursor(dictionary=True) as (_, cursor):
        cursor.execute("""
            SELECT hora, disponivel
            FROM disponibilidade_tecnicos
            WHERE tecnico_id = %s AND data = %s
        """, (tecnico_id, data))
        registros = cursor.fetchall()

    existentes = {r["hora"]: bool(r["disponivel"]) for r in registros}

    with db_cursor(dictionary=True) as (_, cursor):
        cursor.execute("""
            SELECT
                CAST(SUBSTRING_INDEX(a.horario, ':', 1) AS UNSIGNED) AS hora,
                a.id, a.nome_paciente, a.tipo_consulta, a.status,
                a.observacoes, a.origem, a.tecnico_id_2,
                c.nome AS cliente_nome, c.numero_whatsapp,
                t2.nome AS tecnico_nome_2
            FROM agendamentos a
            LEFT JOIN clientes c  ON a.cliente_id   = c.id
            LEFT JOIN tecnicos t2 ON a.tecnico_id_2 = t2.id
            WHERE (a.tecnico_id = %s OR a.tecnico_id_2 = %s)
              AND DATE(a.data_agendamento) = %s
              AND a.status NOT IN ('cancelado', 'em_progresso')
              AND a.horario IS NOT NULL
        """, (tecnico_id, tecnico_id, data))
        agendamentos = cursor.fetchall()

    agendamentos_map = {
        int(ag["hora"]): ag
        for ag in agendamentos
        if ag.get("hora") is not None
    }

    return [
        {
            "hora": hora,
            "disponivel": existentes.get(hora, True),
            "agendamento": agendamentos_map.get(hora)
        }
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
        novo_estado = not bool(row["disponivel"]) if row else False

        cursor.execute("""
            INSERT INTO disponibilidade_tecnicos
            (tecnico_id, data, hora, disponivel)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                disponivel = VALUES(disponivel)
        """, (tecnico_id, data, hora, novo_estado))

    return novo_estado