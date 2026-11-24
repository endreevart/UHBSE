# Owner questions — exposure source discovery v0.2

Do not answer these inside the pipeline. Do not send mail, messages, or calendar events.
Until a decision matching `semantic-decision.schema.json` is recorded, every field meaning
stays `UNKNOWN_PENDING_HUMAN_REVIEW`.

1. `magerya_api` `document_recommendation.document.recommendations[].code` — Какие коды разделов содержат назначения препаратов и БАДов?
2. `magerya_api` `document_recommendation.document.recommendations[].items` — Что именно находится в recommendations[].items?
3. `magerya_api` `document_recommendation` — Является ли документ финальной версией, показанной или выданной пациенту?
4. `kgz_raw` `public.feedback` — Кто заполняет feedback?
5. `kgz_raw` `public.feedback.created_at` — Заполняется ли feedback перед следующей консультацией?
6. `kgz_raw` `public.feedback` — Какой период должен описывать респондент?
7. `kgz_raw` `public.feedback.user_id` — Указывает ли feedback.user_id на того же субъекта, что consultations.patient_id?
8. `kgz_raw` `public.feedback.drugs` — Что означают drugs, drugs_first и vitamins?
9. `kgz_raw` `public.feedback.change_drugs` — Что означают change_drugs и decline_drugs?
10. `kgz_raw` `public.feedback.change_drugs` — Относится ли изменение к рекомендации конкретного врача или консультации?
11. `kgz_raw` `public.feedback.positive_changes` — Что означает positive_changes и к какому периоду оно относится?
12. `kgz_raw` `public.feedback` — Являются ли короткие значения вроде «нет» и «да» штатными вариантами формы?
