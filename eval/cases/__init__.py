"""Held-out evaluation cases for dispute triage (ES / PT)."""

# Placeholder cases — replace with real samples from complaints.csv in Sprint 1.

CASES = [
    {
        "id": "es-normal-001",
        "lang": "es",
        "type": "normal",
        "description": "No reconozco un cargo de $45.99 en Amazon del 12 de marzo.",
        "expected_decision": "auto_resolve_or_create_case",
    },
    {
        "id": "es-ambiguous-001",
        "lang": "es",
        "type": "ambiguous",
        "description": "Creo que me cobraron algo raro pero no recuerdo la fecha ni el monto exacto.",
        "expected_decision": "clarify",
    },
    {
        "id": "es-human-001",
        "lang": "es",
        "type": "human_required",
        "description": "Disputo una transferencia internacional de $12,000; el comercio no responde y el SLA vence hoy.",
        "expected_decision": "escalate",
    },
    {
        "id": "pt-normal-001",
        "lang": "pt",
        "type": "normal",
        "description": "Não reconheço uma compra de R$120,00 no Mercado Livre em 5 de abril.",
        "expected_decision": "auto_resolve_or_create_case",
    },
    {
        "id": "pt-ambiguous-001",
        "lang": "pt",
        "type": "ambiguous",
        "description": "Acho que houve um débito indevido, mas não tenho o comprovante nem a data.",
        "expected_decision": "clarify",
    },
    {
        "id": "pt-human-001",
        "lang": "pt",
        "type": "human_required",
        "description": "Disputa de compra internacional de alto valor; preciso de atendimento humano urgente.",
        "expected_decision": "escalate",
    },
]
