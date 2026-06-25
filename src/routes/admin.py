# Ferramentas de roteamento e tratamento HTTP
from fastapi import APIRouter, HTTPException
# Operações da FAQ no banco
from db.mysql import adicionar_faq, buscar_faq
# Schema de validação da entrada
from models.schemas import FAQCreate


# Grupo de rotas administrativas
router = APIRouter(
    prefix="/admin",
    tags=["admin"]
)

@router.post("/faq")
async def adicionar_faq_endpoint(
    faq: FAQCreate
):
    """
    Cria nova pergunta/resposta
    na base de conhecimento.
    """

    try:

        adicionar_faq(
            faq.pergunta,
            faq.resposta,
            faq.categoria
        )

        return {

            "status": "sucesso",

            "message":
                "FAQ adicionada"
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )



@router.get("/faq")
async def listar_faq():
    """
    Lista todas as perguntas
    cadastradas.
    """

    try:
        faqs = buscar_faq()
        return {
            "total": len(faqs),
            "faqs": faqs
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

# Base inicial para popular sistema
FAQINICIAL = [

   {
        "pergunta":
            "Qual é o endereço?",

        "resposta":
            "Rua General Glicério, 3841 - Vila Redentora, São José do Rio Preto - SP, 15015-400",

        "categoria":
            "Clinica"
   },     

   {
        "pergunta":
            "Tem estacionamento?",

        "resposta":
            "Apenas algumas vagas públicas em frente à loja",

        "categoria":
            "Clinica"
   },     

   {
        "pergunta":
            "Tem acessibilidade?",

        "resposta":
            "Sim, temos uma escada principal para entrar na loja, um elevador e uma rampa para pessoas debilitadas!",

        "categoria":
            "Clinica"
   },     

   {
        "pergunta":
            "O que é cada serviço e para quem é indicado?",

        "resposta":
            """
            Próteses: Dispositivo mecânico ou eletrônico que substitui total ou parcialmente um membro, órgão ou parte do corpo que foi amputada ou que não se desenvolveu devido a uma má-formação congênita.
            É indicado para pessoas com dores crônicas nos pés, tornozelos ou joelhos; diagnósticos de fascite plantar, esporão de calcâneo, neuroma de Morton, pé chato (plano), pé cavo, ou atletas que precisam melhorar a absorção de impacto.

            Órteses: Um dispositivo externo aplicado ao corpo para auxiliar, alinhar, imobilizar ou estabilizar um membro que possui a estrutura física, mas perdeu ou reduziu sua função. Elas não substituem o membro. Exemplos comuns incluem tutores longos, talas de punho e órteses suropodálicas (AFOs) para o tornozelo.
            É indicado para pacientes em reabilitação pós-AVC (com sequelas como o pé equino), pessoas com paralisia cerebral, lesões medulares, fraqueza muscular grave ou em recuperação de fraturas e cirurgias.

            Palmilha: Uma órtese plantar personalizada inserida dentro do calçado comum. Ela redistribui os pontos de pressão do pé e corrige a pisada durante a marcha. É feita após um exame de baropodometria (teste da pisada) ou escaneamento 3D.
            É indicado para pessoas com dores crônicas nos pés, tornozelos ou joelhos; diagnósticos de fascite plantar, esporão de calcâneo, neuroma de Morton, pé chato (plano), pé cavo, ou atletas que precisam melhorar a absorção de impacto.
            """,

        "categoria":
            "Servicos"
   },

   {
        "pergunta":
            "Qual é o horário de atendimento?",

        "resposta":
            "Atendemos de segunda a sexta, das 8h às 18h. Sábados sob agendamento, das 8h às 12h.",

        "categoria":
            "horario"
  },

  {
        "pergunta":
            "Qual é o horário de atendimento remoto?",

        "resposta":
            "Atendemos de segunda a sexta, das 8h às 18h. Sabádo das 8h às 12h.",

        "categoria":
            "horario"
    },
    
    {
        "pergunta":
            "Abre aos feriados?",

        "resposta":
            "Feriados previstos em calendário sim, mas os facultativos são avaliados internamente. Verifique com as atendentes!",

        "categoria":
            "horario"
    },

    {
        "pergunta":
            "Como agendar uma consulta?",

        "resposta":
            "Você pode agendar direto neste chat! Basta informar data e horário.",

        "categoria":
            "agendamento"
    },

    {
        "pergunta":
            "Como reagendar uma consulta?",

        "resposta":
            "Solicite ao OrtoBot, assistente virtual da Ortopedia Geral",

        "categoria":
            "agendamento"
    },

    {
        "pergunta":
            "Como cancelar um agendamento",

        "resposta":
            "Solicite ao OrtoBot, assistente virtual da Ortopedia Geral",

        "categoria":
            "agendamento"
    }, 

    {
        "pergunta":
            "Qual é o prazo de confirmação do agendamento?",

        "resposta":
            "Em até um dia útil",

        "categoria":
            "agendamento"
    },

    {
        "pergunta":
            "O que levar na consulta?",

        "resposta":
            "Documentos e ficha de encaminhamento do médico se tiver",

        "categoria":
            "agendamento"
    },

    {
        "pergunta":
            "Qual é o valor da consulta?",

        "resposta":
            "Valores variam conforme atendimento.",

        "categoria":
            "preco"
    },

    {
        "pergunta":
            "Quais são as formas de pagamento?",

        "resposta":
            "Débito, Credito ou Pix",

        "categoria":
            "preco"
    },

    {
        "pergunta":
            "Quais convênios são aceitos?",
        
        "resposta":
            "Unimed e Bensaúde apenas",
        
        "categoria":
            "planos"
    },
]


@router.post(
    "/faq/popular-inicial"
)
async def popular_faq_inicial():
    """
    Insere perguntas padrão.

    Uso recomendado:
    apenas desenvolvimento.
    """

    try:
        for item in FAQINICIAL:
            adicionar_faq(
                item["pergunta"],
                item["resposta"],
                item["categoria"]
            )
        return {
            "status":
                "sucesso",
            "message":
                f"{len(FAQINICIAL)} FAQs adicionadas"
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )