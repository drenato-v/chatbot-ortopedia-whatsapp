# Context manager para gerenciar conexão/cursor de forma segura
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import List, Optional

from db.mysql import get_connection


# Horários de atendimento da clínica: 08h às 16h (range não inclui o 17)
HORARIOS_ATENDIMENTO = range(8, 17)


@contextmanager
def db_cursor(dictionary: bool = False):
    """
    Context manager que abre conexão, fornece cursor e fecha tudo automaticamente.

    Realiza commit ao final do bloco with; rollback em caso de exceção.
    Garante que conexões não fiquem abertas mesmo em erros inesperados.
    """
    conn   = get_connection()
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


def buscar_tecnico_cliente(cliente_id: int, setor: str) -> Optional[dict]:
    """
    Retorna o técnico que já atendeu este cliente neste setor (fidelização).

    Usado para manter consistência no atendimento — o mesmo técnico
    atende o mesmo paciente sempre que possível.
    Retorna None se não houver histórico de atendimento.
    """
    with db_cursor(dictionary=True) as (_, cursor):
        cursor.execute("""
            SELECT t.*
            FROM cliente_tecnico ct
            INNER JOIN tecnicos t ON ct.tecnico_id = t.id
            WHERE ct.cliente_id = %s
              AND ct.setor = %s
            LIMIT 1
        """, (cliente_id, setor))
        return cursor.fetchone()


def buscar_tecnicos_disponiveis(data: str, hora: int, setor: str) -> List[dict]:
    """
    Lista técnicos ativos do setor que estão disponíveis no horário solicitado.

    Lógica de disponibilidade (opt-out):
    Um técnico está disponível por padrão. Só fica bloqueado se houver um registro
    explícito com disponivel=FALSE em disponibilidade_tecnicos para aquele slot.
    Isso evita a necessidade de pré-configurar a agenda todos os dias.

    Ordenação: individual > flexivel > compartilhado
    (técnicos individuais têm prioridade para não desperdiçar slots compartilhados)
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
                  AND dt.data       = %s
                  AND dt.hora       = %s
                  AND dt.disponivel = FALSE
              )
            ORDER BY
                CASE t.modo_atendimento
                    WHEN 'individual'    THEN 1
                    WHEN 'flexivel'      THEN 2
                    WHEN 'compartilhado' THEN 3
                END
        """, (setor, data, hora))
        return cursor.fetchall()


def buscar_horarios_disponiveis(setor: str, data_inicio: str, dias: int = 7) -> dict:
    """
    Retorna disponibilidade consolidada por dia e hora para um setor.

    Estrutura retornada:
    {
        "2026-06-25": [
            {"hora": "08:00", "disponivel": True,  "tecnicos_livres": 2},
            {"hora": "09:00", "disponivel": False, "tecnicos_livres": 0},
            ...
        ],
        ...
    }

    Estratégia:
    1. Conta o total de técnicos ativos no setor.
    2. Inicializa todos os slots como disponíveis com esse total.
    3. Subtrai os bloqueios encontrados (manuais + agendamentos confirmados/pendentes).

    Usa UNION para consolidar três fontes de bloqueio:
    - Bloqueios manuais em disponibilidade_tecnicos
    - Agendamentos com tecnico_id (técnico principal)
    - Agendamentos com tecnico_id_2 (segundo técnico)
    """
    inicio = datetime.strptime(data_inicio, "%Y-%m-%d")
    fim    = inicio + timedelta(days=dias - 1)

    # Conta total de técnicos ativos no setor para saber a capacidade máxima
    with db_cursor(dictionary=True) as (_, cursor):
        cursor.execute(
            "SELECT COUNT(*) AS total FROM tecnicos WHERE setor = %s AND ativo = TRUE",
            (setor,)
        )
        total_tecnicos = cursor.fetchone()["total"]

    # Monta estrutura inicial com todos os slots disponíveis
    resultado = {}
    for i in range(dias):
        data = (inicio + timedelta(days=i)).strftime("%Y-%m-%d")
        resultado[data] = [
            {
                "hora":            f"{h:02d}:00",
                "disponivel":      total_tecnicos > 0,
                "tecnicos_livres": total_tecnicos,
            }
            for h in HORARIOS_ATENDIMENTO
        ]

    # Sem técnicos cadastrados no setor — retorna tudo indisponível
    if total_tecnicos == 0:
        return resultado

    data_ini_str = inicio.strftime("%Y-%m-%d")
    data_fim_str = fim.strftime("%Y-%m-%d")

    with db_cursor(dictionary=True) as (_, cursor):
        # Consolida todos os bloqueios do período em uma única query com UNION
        cursor.execute("""
            SELECT data, hora, COUNT(DISTINCT tecnico_id) AS bloqueados
            FROM (
                -- Bloqueios manuais registrados pelas atendentes
                SELECT dt.tecnico_id, dt.data, dt.hora
                FROM disponibilidade_tecnicos dt
                INNER JOIN tecnicos t ON dt.tecnico_id = t.id
                WHERE t.setor = %s AND t.ativo = TRUE
                  AND dt.disponivel = FALSE
                  AND dt.data BETWEEN %s AND %s

                UNION

                -- Agendamentos que ocupam o técnico principal
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

                -- Agendamentos que ocupam o segundo técnico (compartilhado)
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
            setor, data_ini_str, data_fim_str,  # bloqueios manuais
            setor, data_ini_str, data_fim_str,  # técnico principal
            setor, data_ini_str, data_fim_str,  # segundo técnico
        ))
        bloqueios = cursor.fetchall()

    # Aplica os bloqueios sobre a estrutura inicial
    for item in bloqueios:
        # Normaliza o campo data que pode vir como date ou string dependendo do driver
        data = (
            item["data"].strftime("%Y-%m-%d")
            if hasattr(item["data"], "strftime")
            else str(item["data"])
        )
        hora = int(item["hora"])
        if data in resultado:
            indice = hora - 8  # converte hora absoluta (8-16) para índice (0-8)
            if 0 <= indice < len(resultado[data]):
                livres = total_tecnicos - item["bloqueados"]
                resultado[data][indice] = {
                    "hora":            f"{hora:02d}:00",
                    "disponivel":      livres > 0,
                    "tecnicos_livres": livres,
                }

    return resultado


def atribuir_tecnico_cliente(cliente_id: int, tecnico_id: int, setor: str):
    """
    Registra ou atualiza o vínculo cliente → técnico para um setor (fidelização).

    Usa ON DUPLICATE KEY UPDATE para ser idempotente — pode ser chamada
    múltiplas vezes sem criar duplicatas.
    """
    with db_cursor() as (_, cursor):
        cursor.execute("""
            INSERT INTO cliente_tecnico (cliente_id, tecnico_id, setor)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE tecnico_id = VALUES(tecnico_id)
        """, (cliente_id, tecnico_id, setor))


def marcar_hora_como_ocupada(tecnico_id: int, data: str, hora: int):
    """
    Bloqueia um slot na agenda do técnico.

    Usa INSERT … ON DUPLICATE KEY UPDATE para ser idempotente —
    chamar duas vezes para o mesmo slot não gera erro nem duplicata.
    """
    with db_cursor() as (_, cursor):
        cursor.execute("""
            INSERT INTO disponibilidade_tecnicos (tecnico_id, data, hora, disponivel)
            VALUES (%s, %s, %s, FALSE)
            ON DUPLICATE KEY UPDATE disponivel = FALSE
        """, (tecnico_id, data, hora))


def liberar_hora(tecnico_id: int, data: str, hora: int):
    """
    Libera um slot previamente bloqueado na agenda do técnico.

    Remove o registro em vez de marcar disponivel=TRUE para que o slot
    volte ao comportamento padrão de opt-out (disponível por omissão).
    """
    with db_cursor() as (_, cursor):
        cursor.execute("""
            DELETE FROM disponibilidade_tecnicos
            WHERE tecnico_id = %s AND data = %s AND hora = %s
        """, (tecnico_id, data, hora))


def buscar_agenda_dia(tecnico_id: int, data: str) -> List[dict]:
    """
    Retorna a agenda completa de um técnico para um dia específico.

    Para cada hora de atendimento (8h–16h), retorna:
    - disponivel: bool (True = livre, False = bloqueado manualmente)
    - agendamento: dict com dados do paciente, ou None se o slot estiver vazio

    Horas sem registro em disponibilidade_tecnicos são tratadas como disponíveis
    (comportamento padrão de opt-out).
    """
    # Busca bloqueios manuais do dia
    with db_cursor(dictionary=True) as (_, cursor):
        cursor.execute("""
            SELECT hora, disponivel
            FROM disponibilidade_tecnicos
            WHERE tecnico_id = %s AND data = %s
        """, (tecnico_id, data))
        registros = cursor.fetchall()

    # Mapa hora → disponível (apenas horas com registro explícito)
    existentes = {r["hora"]: bool(r["disponivel"]) for r in registros}

    # Busca agendamentos confirmados/pendentes do dia para este técnico
    # (tanto como técnico principal quanto como segundo técnico)
    with db_cursor(dictionary=True) as (_, cursor):
        cursor.execute("""
            SELECT
                CAST(SUBSTRING_INDEX(a.horario, ':', 1) AS UNSIGNED) AS hora,
                a.id, a.nome_paciente, a.tipo_consulta, a.status,
                a.observacoes, a.origem, a.tecnico_id_2,
                c.nome  AS cliente_nome,
                c.numero_whatsapp,
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

    # Indexa agendamentos pela hora para lookup O(1)
    agendamentos_map = {
        int(ag["hora"]): ag
        for ag in agendamentos
        if ag.get("hora") is not None
    }

    # Monta lista final com uma entrada por hora de atendimento
    return [
        {
            "hora":        hora,
            # Horas sem registro explícito são tratadas como disponíveis (opt-out)
            "disponivel":  existentes.get(hora, True),
            "agendamento": agendamentos_map.get(hora),
        }
        for hora in HORARIOS_ATENDIMENTO
    ]


def toggle_disponibilidade(tecnico_id: int, data: str, hora: int) -> bool:
    """
    Alterna um slot entre disponível e indisponível para um técnico.

    - Se não houver registro: cria com disponivel=FALSE (bloqueia).
    - Se existir: inverte o valor atual.

    Retorna o novo estado (True = ficou disponível).
    Usado pelas atendentes para bloquear/liberar horários manualmente no painel.
    """
    with db_cursor(dictionary=True) as (_, cursor):
        cursor.execute("""
            SELECT disponivel
            FROM disponibilidade_tecnicos
            WHERE tecnico_id = %s AND data = %s AND hora = %s
        """, (tecnico_id, data, hora))
        row = cursor.fetchone()

        # Sem registro → slot estava disponível (padrão) → bloqueia (False)
        novo_estado = not bool(row["disponivel"]) if row else False

        cursor.execute("""
            INSERT INTO disponibilidade_tecnicos (tecnico_id, data, hora, disponivel)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE disponivel = VALUES(disponivel)
        """, (tecnico_id, data, hora, novo_estado))

    return novo_estado
