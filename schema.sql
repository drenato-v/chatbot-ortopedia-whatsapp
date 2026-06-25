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
    tecnico_id_2      INT         NULL,
    data_agendamento  DATETIME,
    horario           VARCHAR(5),
    tipo_consulta     VARCHAR(50),
    status            ENUM('em_progresso','pendente','confirmado','cancelado')
                      NOT NULL DEFAULT 'em_progresso',
    origem            ENUM('whatsapp','manual') NOT NULL DEFAULT 'whatsapp',
    nome_paciente     VARCHAR(100),
    telefone_paciente VARCHAR(20),
    observacoes       TEXT,
    created_at        TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (cliente_id)   REFERENCES clientes(id)  ON DELETE CASCADE,
    FOREIGN KEY (tecnico_id)   REFERENCES tecnicos(id)  ON DELETE SET NULL,
    FOREIGN KEY (tecnico_id_2) REFERENCES tecnicos(id)  ON DELETE SET NULL
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

-- ── Pacientes ────────────────────────────────────────────────────────────────
-- Registro único por pessoa. Pode ou não ter vínculo com um cliente do WhatsApp.
-- Campos extras (CPF, endereço etc.) são preenchidos no atendimento presencial.
CREATE TABLE IF NOT EXISTS pacientes (
    id                  INT          AUTO_INCREMENT PRIMARY KEY,
    cliente_id          INT          NULL,           -- vínculo com clientes (WhatsApp), se houver
    nome                VARCHAR(100) NOT NULL,
    telefone            VARCHAR(20)  NULL,
    cpf                 VARCHAR(14)  NULL UNIQUE,
    data_nascimento     DATE         NULL,
    endereco            TEXT         NULL,
    plano_saude         VARCHAR(100) NULL,
    medico_responsavel  VARCHAR(100) NULL,
    atendido_por_id     INT          NULL,           -- usuário que iniciou o cadastro
    atendido_por_nome   VARCHAR(100) NULL,           -- denormalizado para preservar histórico
    created_at          TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (cliente_id)      REFERENCES clientes(id)  ON DELETE SET NULL,
    FOREIGN KEY (atendido_por_id) REFERENCES usuarios(id)  ON DELETE SET NULL
);

-- ── Fichas de acompanhamento ──────────────────────────────────────────────────
-- Uma ficha por processo (paciente + serviço). Criada automaticamente na
-- confirmação do agendamento ou manualmente para pacientes presenciais.
CREATE TABLE IF NOT EXISTS fichas (
    id               INT         AUTO_INCREMENT PRIMARY KEY,
    paciente_id      INT         NOT NULL,
    agendamento_id   INT         NULL,               -- NULL para presenciais sem agendamento
    tipo_servico     VARCHAR(50) NOT NULL,
    etapa_atual      VARCHAR(50) NOT NULL DEFAULT 'Atendimento',
    status_orcamento ENUM('em_analise','aprovado','rejeitado') NULL,
    created_at       TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP   DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (paciente_id)    REFERENCES pacientes(id)    ON DELETE CASCADE,
    FOREIGN KEY (agendamento_id) REFERENCES agendamentos(id) ON DELETE SET NULL
);

-- ── Histórico de ficha ────────────────────────────────────────────────────────
-- Log imutável de cada mudança de etapa. usuario_nome é denormalizado para
-- preservar o rastro mesmo se o usuário for excluído do sistema.
CREATE TABLE IF NOT EXISTS ficha_historico (
    id           INT          AUTO_INCREMENT PRIMARY KEY,
    ficha_id     INT          NOT NULL,
    etapa        VARCHAR(50)  NOT NULL,
    descricao    TEXT         NULL,
    usuario_id   INT          NULL,
    usuario_nome VARCHAR(100) NOT NULL,
    created_at   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ficha_id)   REFERENCES fichas(id)   ON DELETE CASCADE,
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL
);

-- ── Usuários do sistema (painel web) ──────────────────────────────────────────
-- Cada funcionário tem um role que determina quais abas e ações pode acessar.
-- password_hash armazena apenas o hash bcrypt — nunca a senha em texto puro.
CREATE TABLE IF NOT EXISTS usuarios (
    id            INT          AUTO_INCREMENT PRIMARY KEY,
    nome          VARCHAR(100) NOT NULL,
    email         VARCHAR(150) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role          ENUM('admin','atendente','estoquista','tecnico') NOT NULL,
    ativo         BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);
