-- Banco de dados do Chatbot Ortopedia Geral
-- Execute: mysql -u root -p < schema.sql

CREATE DATABASE IF NOT EXISTS chatbot
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE chatbot;

-- ── Clientes ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS clientes (
    id               INT          AUTO_INCREMENT PRIMARY KEY,
    numero_whatsapp  VARCHAR(20)  NOT NULL UNIQUE,
    nome             VARCHAR(100),
    email            VARCHAR(150),
    created_at       TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

-- ── FAQ ───────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS faq (
    id         INT       AUTO_INCREMENT PRIMARY KEY,
    pergunta   TEXT      NOT NULL,
    resposta   TEXT      NOT NULL,
    categoria  VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ── Técnicos ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tecnicos (
    id               INT          AUTO_INCREMENT PRIMARY KEY,
    nome             VARCHAR(100) NOT NULL,
    setor            VARCHAR(50)  NOT NULL,
    modo_atendimento ENUM('individual', 'compartilhado', 'flexivel')
                     NOT NULL DEFAULT 'individual',
    ativo            BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

-- ── Agendamentos ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agendamentos (
    id                INT         AUTO_INCREMENT PRIMARY KEY,
    cliente_id        INT,
    tecnico_id        INT,
    data_agendamento  DATETIME,
    horario           VARCHAR(5),
    tipo_consulta     VARCHAR(50),
    status            ENUM('em_progresso','pendente','confirmado','cancelado')
                      NOT NULL DEFAULT 'em_progresso',
    origem            ENUM('whatsapp','manual') NOT NULL DEFAULT 'whatsapp',
    nome_paciente     VARCHAR(100),
    observacoes       TEXT,
    created_at        TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (cliente_id)  REFERENCES clientes(id) ON DELETE CASCADE,
    FOREIGN KEY (tecnico_id)  REFERENCES tecnicos(id) ON DELETE SET NULL
);

-- ── Conversas ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conversas (
    id                INT       AUTO_INCREMENT PRIMARY KEY,
    cliente_id        INT       NOT NULL,
    mensagem_usuario  TEXT      NOT NULL,
    resposta_bot      TEXT      NOT NULL,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE
);

-- ── Disponibilidade dos técnicos ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS disponibilidade_tecnicos (
    id          INT      AUTO_INCREMENT PRIMARY KEY,
    tecnico_id  INT      NOT NULL,
    data        DATE     NOT NULL,
    hora        TINYINT  NOT NULL,   -- 8 a 16
    disponivel  BOOLEAN  NOT NULL DEFAULT TRUE,
    UNIQUE KEY uq_tecnico_data_hora (tecnico_id, data, hora),
    FOREIGN KEY (tecnico_id) REFERENCES tecnicos(id) ON DELETE CASCADE
);

-- ── Vínculo cliente → técnico (fidelização) ───────────────────────────────────
CREATE TABLE IF NOT EXISTS cliente_tecnico (
    cliente_id  INT         NOT NULL,
    tecnico_id  INT         NOT NULL,
    setor       VARCHAR(50) NOT NULL,
    PRIMARY KEY (cliente_id, setor),
    FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE,
    FOREIGN KEY (tecnico_id) REFERENCES tecnicos(id) ON DELETE CASCADE
);
