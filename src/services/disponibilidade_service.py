from db.mysql import get_connection


def configurar_disponibilidade(
    tecnico_id: int,
    data: str,
    horas: list[int]
):
    """
    Configura a agenda disponível de um técnico para uma data.

    Estratégia:
    - Remove qualquer configuração anterior daquele dia.
    - Recria apenas os horários enviados.

    Exemplo:
        configurar_disponibilidade(
            tecnico_id=1,
            data="2026-06-18",
            horas=[8, 10, 11, 14]
        )

    Resultado:
        Técnico disponível às 08h, 10h, 11h e 14h.
    """

    # Abre conexão com o banco
    conn = get_connection()

    # Cursor padrão para comandos de escrita
    cursor = conn.cursor()

    try:

        # Remove disponibilidade anterior do técnico
        # para evitar horários duplicados ou antigos
        cursor.execute("""
            DELETE FROM disponibilidade_tecnicos
            WHERE tecnico_id=%s
            AND data=%s
        """, (
            tecnico_id,
            data
        ))

        # Cria novamente os horários enviados
        for hora in horas:

            cursor.execute("""
                INSERT INTO disponibilidade_tecnicos
                (
                    tecnico_id,
                    data,
                    hora,
                    disponivel
                )
                VALUES
                (
                    %s,
                    %s,
                    %s,
                    TRUE
                )
            """, (
                tecnico_id,
                data,
                hora
            ))

        # Persiste alterações
        conn.commit()

    finally:

        # Libera recursos mesmo em caso de erro
        cursor.close()
        conn.close()


def obter_disponibilidade(
    tecnico_id: int,
    data: str
):
    """
    Consulta os horários configurados para um técnico.

    Args:
        tecnico_id:
            Identificador do técnico.

        data:
            Data no formato YYYY-MM-DD.

    Returns:
        Lista contendo:

        [
            {
                "hora": 8,
                "disponivel": True
            },
            {
                "hora": 10,
                "disponivel": False
            }
        ]
    """

    # Conexão com banco
    conn = get_connection()

    # Cursor em modo dicionário para retorno estruturado
    cursor = conn.cursor(dictionary=True)

    try:

        # Busca horários cadastrados para o dia
        cursor.execute("""
            SELECT
                hora,
                disponivel
            FROM disponibilidade_tecnicos
            WHERE tecnico_id=%s
            AND data=%s
            ORDER BY hora
        """, (
            tecnico_id,
            data
        ))

        return cursor.fetchall()

    finally:

        # Fecha conexão e cursor
        cursor.close()
        conn.close()