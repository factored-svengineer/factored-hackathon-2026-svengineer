"""Held-out evaluation cases for dispute triage (ES / PT).

Grounded in real complaints.csv rows from the Factored Datathon sample
(see docs/use-cases.md). Descriptions are NL stand-ins because the source
`description` field is a category template, not free text.
"""

CASES = [
    # --- Fraude claro / auto_resolve ---
    {
        "id": "es-clear-fraud-001",
        "lang": "es",
        "type": "clear_fraud",
        "source_complaint_id": "CMP-P7HVN55QJQFLDZ4HRU55",
        "source_transaction_id": "TRX-VV2MMGPU6842YMOC1BHN",
        "description": (
            "No reconozco un cargo de 4948.14 COP en mi producto. "
            "Quiero reclamar ese movimiento como fraude."
        ),
        "expected_decision": "auto_resolve",
        "signals": {
            "category": "Transactions",
            "subcategory": "Cargo no reconocido",
            "claimed_amount": 4948.14,
            "currency": "COP",
            "priority": "Medium",
            "is_fraud": True,
            "fraud_score": 97.45,
        },
    },
    {
        "id": "pt-clear-fraud-001",
        "lang": "pt",
        "type": "clear_fraud",
        "source_complaint_id": "CMP-P7HVN55QJQFLDZ4HRU55",
        "source_transaction_id": "TRX-VV2MMGPU6842YMOC1BHN",
        "description": (
            "Não reconheço uma cobrança de 4948.14 COP no meu produto. "
            "Quero contestar essa movimentação como fraude."
        ),
        "expected_decision": "auto_resolve",
        "signals": {
            "category": "Transactions",
            "subcategory": "Cargo no reconocido",
            "claimed_amount": 4948.14,
            "currency": "COP",
            "priority": "Medium",
            "is_fraud": True,
            "fraud_score": 97.45,
        },
    },
    # --- Ambiguo / clarify ---
    {
        "id": "es-ambiguous-001",
        "lang": "es",
        "type": "ambiguous",
        "source_complaint_id": "CMP-UIWYTUU391C10NH7TVZT",
        "source_transaction_id": None,
        "description": (
            "Creo que me cobraron algo que no reconozco, "
            "pero no tengo el monto ni la fecha exacta."
        ),
        "expected_decision": "clarify",
        "signals": {
            "category": "Transactions",
            "subcategory": "Cargo no reconocido",
            "claimed_amount": None,
            "currency": None,
            "priority": "Low",
            "status": "Open",
            "sla_breached": False,
        },
    },
    {
        "id": "pt-ambiguous-001",
        "lang": "pt",
        "type": "ambiguous",
        "source_complaint_id": "CMP-UIWYTUU391C10NH7TVZT",
        "source_transaction_id": None,
        "description": (
            "Acho que cobraram algo que não reconheço, "
            "mas não tenho o valor nem a data exata."
        ),
        "expected_decision": "clarify",
        "signals": {
            "category": "Transactions",
            "subcategory": "Cargo no reconocido",
            "claimed_amount": None,
            "currency": None,
            "priority": "Low",
            "status": "Open",
            "sla_breached": False,
        },
    },
    # --- Requiere humano / escalate ---
    {
        "id": "es-human-001",
        "lang": "es",
        "type": "human_required",
        "source_complaint_id": "CMP-W9KJLENI8RSM8TU99NXZ",
        "source_transaction_id": None,
        "description": (
            "Disputo un cargo no reconocido de 2984.58 COP; "
            "el caso es crítico y el SLA ya se venció. Necesito atención humana."
        ),
        "expected_decision": "escalate",
        "signals": {
            "category": "Transactions",
            "subcategory": "Cargo no reconocido",
            "claimed_amount": 2984.58,
            "currency": "COP",
            "priority": "Critical",
            "status": "Escalated",
            "sla_breached": True,
        },
    },
    {
        "id": "pt-human-001",
        "lang": "pt",
        "type": "human_required",
        "source_complaint_id": "CMP-W9KJLENI8RSM8TU99NXZ",
        "source_transaction_id": None,
        "description": (
            "Contesto uma cobrança não reconhecida de 2984.58 COP; "
            "o caso é crítico e o SLA já venceu. Preciso de atendimento humano."
        ),
        "expected_decision": "escalate",
        "signals": {
            "category": "Transactions",
            "subcategory": "Cargo no reconocido",
            "claimed_amount": 2984.58,
            "currency": "COP",
            "priority": "Critical",
            "status": "Escalated",
            "sla_breached": True,
        },
    },
]
