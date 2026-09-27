# Limitations (pre-production)

What this hackathon system does **not** yet cover for real production:

| Area | Gap |
|------|-----|
| Capacity | No load testing, autoscaling, or rate limits defined |
| Monitoring | No metrics/alerts beyond basic logs (Sprint 3 tracing TBD) |
| Data retention | No formal retention/deletion policy for transcripts or PII |
| Portuguese coverage | Held-out PT cases exist as placeholders; full eval coverage TBD |
| AuthN/AuthZ | API is open locally; no customer identity binding yet |
| Tool reliability | Create-dispute verification and fallbacks are stubs |
| Model risk | Classifier vs baseline comparison not yet run on real held-out data |
| Compliance | No formal audit trail export for regulators |

Update this file in Sprint 3 with concrete findings from evaluation and deploy.
