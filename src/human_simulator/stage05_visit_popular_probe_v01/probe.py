"""Find the most common prescription label and compare records for that label only."""

from __future__ import annotations

import json
from typing import Any

STAGE_SQL = r"""
SET statement_timeout = '90s';
CREATE TEMP TABLE rx_tokens AS
SELECT r.appointment_id,
       lower(regexp_replace(btrim(item ->> 'name'), '[[:space:]]+', ' ', 'g')) AS label,
       'recommendation'::text AS store
FROM magerya_api.document_recommendation r
CROSS JOIN LATERAL jsonb_array_elements(r.document -> 'recommendations') elem
CROSS JOIN LATERAL jsonb_array_elements(elem -> 'items') item
WHERE jsonb_typeof(r.document -> 'recommendations') = 'array'
  AND jsonb_typeof(elem -> 'items') = 'array'
  AND (
    position('медикамент' IN lower(coalesce(elem ->> 'title', ''))) > 0
    OR position('препараты и витамины' IN lower(coalesce(elem ->> 'title', ''))) > 0
  )
  AND btrim(coalesce(item ->> 'name', '')) <> ''
UNION ALL
SELECT ar.appointment_id,
       lower(regexp_replace(btrim(med.name), '[[:space:]]+', ' ', 'g')) AS label,
       'catalog'::text AS store
FROM magerya_api.document_appointmentanalysisresult ar
JOIN magerya_api.django_content_type ct ON ct.id = ar.content_type_id
 AND ct.app_label = 'diagnosis' AND ct.model = 'medicineappointments'
JOIN magerya_api.diagnosis_medicineappointments m ON m.id::text = ar.object_id
JOIN magerya_api.diagnosis_medicines med ON med.id = m.medicine_id
WHERE m.status = 'added'
  AND btrim(coalesce(med.name, '')) <> '';

CREATE TEMP TABLE label_counts AS
SELECT label,
       count(DISTINCT appointment_id) AS visits,
       count(DISTINCT appointment_id) FILTER (WHERE store = 'recommendation') AS recommendation_visits,
       count(DISTINCT appointment_id) FILTER (WHERE store = 'catalog') AS catalog_visits
FROM rx_tokens
WHERE char_length(label) >= 2
GROUP BY label;

CREATE TEMP TABLE winner AS
SELECT label, visits, recommendation_visits, catalog_visits
FROM label_counts
ORDER BY visits DESC, label
LIMIT 1;

CREATE TEMP TABLE winner_visits AS
SELECT DISTINCT t.appointment_id
FROM rx_tokens t
JOIN winner w ON w.label = t.label;

CREATE TEMP TABLE chain_pairs AS
WITH ordered AS (
  SELECT a.id, a.patient_id, a.completed_at,
         row_number() OVER (PARTITION BY a.patient_id ORDER BY a.completed_at, a.id) AS seq
  FROM magerya_api.appointment_appointment a
  WHERE a.status = 'completed' AND a.completed_at IS NOT NULL
)
SELECT a.id AS prev_id, b.id AS next_id, a.completed_at AS prev_at, b.completed_at AS next_at
FROM ordered a
JOIN ordered b ON b.patient_id = a.patient_id AND b.seq = a.seq + 1
JOIN winner_visits wv ON wv.appointment_id = a.id
JOIN magerya_api.document_doctorquestionnaire dn ON dn.appointment_id = b.id;

CREATE INDEX ON chain_pairs (prev_id);
CREATE INDEX ON chain_pairs (next_id);

CREATE TEMP TABLE chain_ids AS
SELECT prev_id AS appointment_id FROM chain_pairs
UNION
SELECT next_id FROM chain_pairs;
CREATE INDEX ON chain_ids (appointment_id);

CREATE TEMP TABLE exam AS
SELECT dq.appointment_id, e ->> 'code' AS code,
       bool_or(btrim(coalesce(e ->> 'answer', '')) <> '') AS filled,
       min(md5(lower(btrim(e ->> 'answer')))) FILTER (
         WHERE btrim(coalesce(e ->> 'answer', '')) <> ''
       ) AS answer_hash
FROM magerya_api.document_doctorquestionnaire dq
JOIN chain_ids ids ON ids.appointment_id = dq.appointment_id
CROSS JOIN LATERAL jsonb_array_elements(dq.document -> 'examination') e
WHERE jsonb_typeof(dq.document -> 'examination') = 'array'
  AND e ->> 'code' IN ('goal', 'complaints', 'anamnesis', 'objective_status', 'local_status')
GROUP BY dq.appointment_id, e ->> 'code';
CREATE INDEX ON exam (appointment_id, code);

CREATE TEMP TABLE exam_counts AS
SELECT c.code,
       count(*) AS pairs,
       count(*) FILTER (WHERE NOT coalesce(pe.filled, false) AND NOT coalesce(ne.filled, false)) AS both_empty,
       count(*) FILTER (WHERE coalesce(pe.filled, false) AND NOT coalesce(ne.filled, false)) AS only_previous,
       count(*) FILTER (WHERE NOT coalesce(pe.filled, false) AND coalesce(ne.filled, false)) AS only_next,
       count(*) FILTER (
         WHERE coalesce(pe.filled, false) AND coalesce(ne.filled, false) AND pe.answer_hash = ne.answer_hash
       ) AS same_text,
       count(*) FILTER (
         WHERE coalesce(pe.filled, false) AND coalesce(ne.filled, false)
           AND pe.answer_hash IS DISTINCT FROM ne.answer_hash
       ) AS text_changed
FROM chain_pairs p
CROSS JOIN (
  VALUES ('goal'), ('complaints'), ('anamnesis'), ('objective_status'), ('local_status')
) AS c(code)
LEFT JOIN exam pe ON pe.appointment_id = p.prev_id AND pe.code = c.code
LEFT JOIN exam ne ON ne.appointment_id = p.next_id AND ne.code = c.code
GROUP BY c.code;

CREATE TEMP TABLE lab_fp AS
SELECT ar.appointment_id, res.analysis_id,
       md5(coalesce(string_agg(
         md5(lower(btrim(coalesce(it.name, ''))) || '|' || lower(btrim(coalesce(it.value, ''))) || '|' || lower(btrim(coalesce(it.flag, '')))),
         ',' ORDER BY it.id
       ), '')) AS fp
FROM magerya_api.document_appointmentanalysisresult ar
JOIN chain_ids i ON i.appointment_id = ar.appointment_id
JOIN magerya_api.django_content_type ct ON ct.id = ar.content_type_id
 AND ct.app_label = 'document' AND ct.model = 'analysisresult'
JOIN magerya_api.document_analysisresult res ON res.id::text = ar.object_id
LEFT JOIN magerya_api.document_analysisresultitem it ON it.analysis_result_id = res.id
WHERE res.status = 'received'
GROUP BY ar.appointment_id, res.analysis_id;

CREATE TEMP TABLE lab_pair AS
SELECT p.prev_id, p.next_id,
       count(*) AS shared,
       count(*) FILTER (WHERE a.fp IS DISTINCT FROM b.fp) AS diffs
FROM chain_pairs p
JOIN lab_fp a ON a.appointment_id = p.prev_id
JOIN lab_fp b ON b.appointment_id = p.next_id AND b.analysis_id = a.analysis_id
GROUP BY p.prev_id, p.next_id;

SELECT json_build_object(
  'probe_label', w.label,
  'visits', w.visits,
  'recommendation_visits', w.recommendation_visits,
  'catalog_visits', w.catalog_visits,
  'tie_count', (SELECT count(*) FROM label_counts c WHERE c.visits = w.visits),
  'pairs', (SELECT count(*) FROM chain_pairs),
  'examination', (
    SELECT coalesce(json_object_agg(code, json_build_object(
      'pairs', pairs,
      'both_empty', both_empty,
      'only_previous', only_previous,
      'only_next', only_next,
      'same_text', same_text,
      'text_changed', text_changed
    )), '{}'::json)
    FROM exam_counts
  ),
  'shared_lab_pairs', (SELECT count(*) FROM lab_pair),
  'shared_lab_values_unchanged_pairs', (SELECT count(*) FROM lab_pair WHERE diffs = 0),
  'shared_lab_values_changed_pairs', (SELECT count(*) FROM lab_pair WHERE diffs > 0),
  'GATE_2_STATUS', 'CLOSED',
  'eligible_cells', 0,
  'effect_claimed', false
)
FROM winner w;
"""


def parse_stage_payload(raw: str) -> dict[str, Any]:
    lines = [line.strip() for line in raw.splitlines() if line.strip().startswith("{")]
    if len(lines) != 1:
        raise ValueError("stage payload must be one JSON object")
    payload = json.loads(lines[0])
    if not isinstance(payload, dict):
        raise ValueError("stage payload must be an object")
    label = payload.get("probe_label")
    if not isinstance(label, str) or len(label) < 2 or len(label) > 120:
        raise ValueError("probe label is missing or not a short catalog label")
    pairs = payload.get("pairs")
    examination = payload.get("examination")
    if not isinstance(pairs, int) or pairs < 1:
        raise ValueError("probe has no visit pairs")
    if not isinstance(examination, dict):
        raise ValueError("examination block is missing")
    for code, row in examination.items():
        total = (
            row["both_empty"]
            + row["only_previous"]
            + row["only_next"]
            + row["same_text"]
            + row["text_changed"]
        )
        if total != row["pairs"] or row["pairs"] != pairs:
            raise ValueError(f"examination counts do not add up for {code}")
    if payload.get("GATE_2_STATUS") != "CLOSED" or payload.get("eligible_cells") != 0:
        raise ValueError("probe widened the closed gate")
    if payload.get("effect_claimed") is not False:
        raise ValueError("probe claimed an effect")
    return payload
