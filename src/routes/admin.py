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
            "Qual é o horário de atendimento?",

        "resposta":
            "Atendemos de segunda a sexta, das 8h às 18h. Sábados sob agendamento.",

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
            "Qual é o valor da consulta?",

        "resposta":
            "Valores variam conforme atendimento.",

        "categoria":
            "preco"
    }
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