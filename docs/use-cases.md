# Casos de uso de disputa (Sprint 1 — Issue #1)

Fuente: muestra de `complaints` + `transactions` del bucket
`factored-datathon-2026-s3-157725502942-us-east-2-an` (prefijo `data/`),
descargada localmente bajo `data/raw/` (gitignored).

## Hallazgos del dataset (relevantes al grafo)

| Hallazgo | Implicación |
|----------|-------------|
| `complaints.description` es plantilla (`Queja relacionada con {category}`), no NL libre | El intake NL (ES/PT) se modela desde categoría/subcategoría + monto + canal; el texto rico está en `call_transcripts.full_text` |
| Señales de decisión útiles en `complaints` | `category`, `subcategory`, `claimed_amount`, `currency`, `priority`, `status`, `sla_breached`, `case_type` |
| Señales de fraude en `transactions` | `is_fraud` (bool), `fraud_score` (**escala ~0–100**, no 0–1) |
| En la muestra no hubo join `customer_id` entre quejas y txns `is_fraud=True` | El grafo debe **verificar la transacción disputada** por id/heurística, no asumir que la queja ya trae el label de fraude |
| Transcripts muestreados | Casi todos `detected_language=es`; cobertura PT a completar en eval |

Umbrales de política actuales (`backend/app/policy/rules.py`): monto alto ≥ 1000, escalar ≥ 5000, auto-resolve si `is_fraud` y score ≥ 0.85 — **hay que normalizar `fraud_score/100`** al cablear el nodo `decide`.

---

## Los 3 arquetipos

### 1) Fraude claro → resolución automática (`auto_resolve`)

**Intención del cliente:** “No reconozco este cargo / fue fraude.”  
**Condición de decisión:** tras `understand` + lookup de transacción, `is_fraud=True` y `fraud_score/100 ≥ 0.85` (y no hay señales de escalamiento crítico/SLA).

**Ejemplo real — lado queja (intake tipificado):**

| Campo | Valor |
|-------|-------|
| `complaint_id` | `CMP-P7HVN55QJQFLDZ4HRU55` |
| `customer_id` | `CLI-PFYINQ8JMS43` |
| `case_type` | Claim |
| `category` / `subcategory` | Transactions / Cargo no reconocido |
| `claimed_amount` | 4948.14 COP |
| `priority` | Medium |
| `status` (histórico) | Resolved |
| `sla_breached` | False |
| `description` | Queja relacionada con transactions |

**Ejemplo real — lado verificación de fraude (txn):**

| Campo | Valor |
|-------|-------|
| `transaction_id` | `TRX-VV2MMGPU6842YMOC1BHN` |
| `customer_id` | `CLI-CS5CUV8NS0B5` |
| `amount` | 45.51 USD |
| `merchant_name` | Empresa Telefónica |
| `is_fraud` | True |
| `fraud_score` | **97.45** (~0.97 normalizado) |

**NL de referencia (ES) para diseño del grafo** (anclado a la subcategoría + monto de la queja):

> No reconozco un cargo de 4948.14 COP en mi producto. Quiero reclamar ese movimiento.

**NL de referencia (PT):**

> Não reconheço uma cobrança de 4948.14 COP no meu produto. Quero contestar essa movimentação.

**Flujo esperado en el grafo:**

```
understand → decide(auto_resolve) → act(crear/ajustar caso + compensación si aplica) → verify → FIN
```

No pasa por `escalate`.

---

### 2) Ambiguo / falta información → clarificación o abstención (`clarify`)

**Intención:** posible cargo no reconocido, pero faltan monto, moneda o datos mínimos.  
**Condición:** `claimed_amount` nulo y/o entidades incompletas; `fraud_score` en zona gris (0.40–0.85) si hay txn; prioridad Low; no Critical/SLA roto.

**Ejemplo real:**

| Campo | Valor |
|-------|-------|
| `complaint_id` | `CMP-UIWYTUU391C10NH7TVZT` |
| `customer_id` | `CLI-RAGV3OBQTWL1` |
| `case_type` | Complaint |
| `category` / `subcategory` | Transactions / Cargo no reconocido |
| `claimed_amount` / `currency` | **null / null** |
| `priority` | Low |
| `status` | Open |
| `sla_breached` | False |
| `reception_channel` | Call Center |
| `description` | Queja relacionada con transactions |

En la muestra hay **~50** quejas Transactions Low/Open-InProcess **sin monto** — patrón frecuente.

**NL ES:**

> Creo que me cobraron algo que no reconozco, pero no tengo el monto ni la fecha exacta.

**NL PT:**

> Acho que cobraram algo que não reconheço, mas não tenho o valor nem a data exata.

**Flujo esperado:**

```
understand → decide(clarify) → act(pedir monto/fecha/comercio) → verify(pregunta registrada) → FIN (espera respuesta)
```

Abstención: no inventar resolución ni escalar “por si acaso”.

---

### 3) Requiere humano → escalamiento (`escalate`)

**Intención:** disputa de alto riesgo operativo.  
**Condición (cualquiera):** `priority` Critical/High, `status=Escalated`, `sla_breached=True`, o monto ≥ umbral de escalamiento; o fraude no concluyente con impacto alto.

**Ejemplo real:**

| Campo | Valor |
|-------|-------|
| `complaint_id` | `CMP-W9KJLENI8RSM8TU99NXZ` |
| `customer_id` | `CLI-IDKD41Z51JP1` |
| `case_type` | Complaint |
| `category` / `subcategory` | Transactions / Cargo no reconocido |
| `claimed_amount` | 2984.58 COP |
| `priority` | **Critical** |
| `status` | **Escalated** |
| `sla_breached` | **True** |
| `assigned_agent_id` | AGT-LF09IF9QQL |
| `description` | Queja relacionada con transactions |

**NL ES:**

> Disputo un cargo no reconocido de 2984.58 COP; el caso es crítico y el SLA ya se venció. Necesito atención humana.

**NL PT:**

> Contesto uma cobrança não reconhecida de 2984.58 COP; o caso é crítico e o SLA já venceu. Preciso de atendimento humano.

**Flujo esperado:**

```
understand → decide(escalate) → act(preparar handoff) → verify → escalate(handoff estructurado)
```

Handoff **nunca** incluye transcript crudo: hechos verificados, categoría, score de fraude, acciones tomadas, evidencia, preguntas abiertas (ver issue #3).

---

## Mapa decisión → nodos

| Arquetipo | Señales (datos reales) | `decide` | Nodos posteriores |
|-----------|------------------------|----------|-------------------|
| Fraude claro | `is_fraud` + `fraud_score/100 ≥ 0.85`; monto/categoría presentes | `auto_resolve` | act → verify |
| Ambiguo | monto/fecha/comercio faltantes; score gris; Low | `clarify` | act(preguntas) → verify |
| Humano | Critical/High, Escalated, SLA breach, monto alto | `escalate` | act → verify → escalate |

## Conteos en la muestra (~1749 quejas, 30 shards)

| Señal | Aprox. |
|-------|--------|
| category = Transactions | 328 |
| subcategory = Cargo no reconocido | 288 |
| Transactions + sin `claimed_amount` + Low + Open/In Process | 50 |
| Transactions + (Critical/High \| Escalated \| sla_breached \| amount≥5000) | 135 |
| txns `is_fraud=True` (5 días jun-2023) | 14 |

## Próximos pasos desbloqueados

1. Issue #3 — cerrar contrato JSON de handoff usando el arquetipo 3.  
2. Issue #2 / #7 — skeleton + nodos usando estos tres caminos.  
3. Ajustar política: normalizar `fraud_score` 0–100 → 0–1.  
4. Eval: casos ES/PT en `eval/cases` anclados a estos `complaint_id`.
