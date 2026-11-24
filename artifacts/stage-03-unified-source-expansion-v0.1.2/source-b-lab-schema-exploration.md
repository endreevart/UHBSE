# Source B (`kgz_raw`) laboratory schema exploration

**Scope:** Unified Source Expansion v0.1.2 prep  
**Method:** read-only `human_simulator.unified.source_b_adapter.source_b_connection`  
**Safety:** aggregates / catalog names only — no patient values, IDs, or PII  
**Row universe:** `quest_digital.analyses_constructor` exact count **2 183 297**

---

## 1. Columns + types

### `quest_digital.analyses_constructor`

| column | type | nullable |
|--------|------|----------|
| id | integer (int4) | NO |
| user_id | integer | YES |
| consultation_id | integer | YES |
| pool_id | integer | YES |
| created_at | timestamp | YES |
| updated_at | timestamp | YES |
| catalog_id | integer | NO |
| weight_id | integer | YES |
| date | timestamp | YES |
| status | integer | NO |
| value | text | YES |
| extra | text | YES |
| has_result | boolean | YES |

### `quest_digital.analyses_catalog`

| column | type | nullable |
|--------|------|----------|
| id | integer | NO |
| code | varchar(50) | YES |
| name_ru | text | YES |
| name_en | text | YES |
| material | text | YES |
| weight_id | integer | NO |
| created_at | timestamp | YES |
| updated_at | timestamp | YES |
| name_alt | text | YES |
| priority | integer | NO |
| deleted_at | timestamp | YES |
| type | varchar(20) | NO |

Catalog exact row count: **1 886**.

---

## 2. `weight_id` targets

| Finding | Detail |
|---------|--------|
| Unit/weight tables | `quest_digital.analyses_weight` (100 rows), `quest_digital.catalog_weights` (651 rows junction) |
| No `units` / `measure` app tables | only PostGIS `tiger.secondary_unit_lookup` (irrelevant) |
| `analyses_weight` columns | id, created_at, updated_at, **name**, **code**, **name_en**, **code_en**, deleted_at, priority |
| Constructor FK | `weight_id` → `quest_digital.analyses_weight.id` (`fk_a8f3f3dd350035dc`) |
| Catalog `weight_id` | present; **no declared FK** in `pg_constraint`; all 1 886 catalog rows resolve to `analyses_weight` by value match |
| `catalog_weights` | `(catalog_id, weight_id)` bridge — not the constructor FK target |

**Interpretation:** `analyses_weight` is the unit/measure reference catalog (name/code), not body-weight.

---

## 3. Constructor FK graph

| column | references | non-null | resolved |
|--------|------------|----------|----------|
| consultation_id | `public.consultations.id` | 2 183 297 | 2 183 297 |
| catalog_id | `quest_digital.analyses_catalog.id` | 2 183 297 | 2 183 297 |
| user_id | `public.users.id` | 2 183 297 | 2 183 297 |
| pool_id | `quest_digital.analyses_pool.id` | 2 183 297 | 2 183 297 |
| weight_id | `quest_digital.analyses_weight.id` | 1 978 355 | 1 978 355 |

All five FKs are declared in PostgreSQL. `weight_id` is the only nullable of the five in practice (~9.4% null).

---

## 4. Ownership (`user_id` vs `consultations.patient_id`)

Join on `consultation_id`:

| aggregate | count |
|-----------|------:|
| total rows | 2 183 297 |
| `user_id` = `patient_id` | 2 183 297 |
| differs | 0 |
| `user_id` null | 0 |
| consultation orphan / patient null | 0 |

**Verdict:** constructor `user_id` is always the consultation patient in this dump.

---

## 5. Pool / grouping collisions

| metric | value |
|--------|------:|
| distinct `pool_id` | 59 741 |
| pools with >1 distinct `patient_id` | **0** |
| pools with >1 `consultation_id` | **0** |
| pools with exactly one patient / one consultation | 59 741 / 59 741 |

Candidate grouping key multi-patient collision counts (all **0**):

| key | n_groups |
|-----|--------:|
| `pool_id` | 59 741 |
| `consultation_id` | 59 737 |
| `pool_id` + `consultation_id` | 59 741 |
| `consultation_id` + `date_trunc(day, date)` | 266 615 |
| `user_id` + `date_trunc(day, date)` | 265 247 |
| `catalog_id` + `consultation_id` | 2 042 931 |

**Verdict:** `pool_id` is a clean 1:1 patient/consultation grouping key in this snapshot (no cross-patient pool collisions). Slightly more pools than consultations (59 741 vs 59 737).

---

## 6. Value representation classification

Mutually exclusive `CASE` on trimmed `value` text patterns only (no raw values returned). Total **2 183 297**.

| category | count |
|----------|------:|
| decimal_comma | 1 064 889 |
| plain_integer | 410 305 |
| other | 380 143 |
| with_unit_suffix | 191 636 |
| plain_decimal_dot | 85 567 |
| empty | 50 319 |
| signed | 330 |
| less_than | 87 |
| range | 15 |
| greater_than | 6 |
| scientific | 0 |

Dominant pattern is comma-decimal numeric text; large `other` residual needs a follow-up parser taxonomy for Observation load.

---

## 7. Catalog columns that look like unit / code / name

From `analyses_catalog` column names only:

- `code`
- `name_ru`, `name_en`, `name_alt`
- `material`
- `weight_id` (FK-like unit pointer)
- `type`

Related unit labels live on `analyses_weight`: `name`, `code`, `name_en`, `code_en`.

---

## 8. `extra` column

| question | answer |
|----------|--------|
| Is `extra` jsonb? | **No** — `text` (`udt_name=text`) |
| JSON object/array prefix rows | **0** |
| Top-level `jsonb_object_keys` frequency | **empty / N/A** (nothing castable as JSON object) |
| null | 2 011 257 |
| empty / whitespace | ~3 105 |
| non-empty non-JSON text | 168 935 |

Structural pattern aggregates (non-empty): mostly `other_text` / contains comma or colon; not JSON. Length mostly 1–50 chars.

---

## Reuse: existing Source B modules

### Shared adapter / v0.1

| module | reuse pattern |
|--------|----------------|
| `human_simulator.unified.source_b_adapter` | RO connection, access probe, relation count aggregates |
| `human_simulator.unified.source_b_integration` | draft mapping load, status classify, semantic populate gates |

### `unified_v011` Source B–related

| module | reuse pattern |
|--------|----------------|
| `unified_v011.source_b_semantics` | role graph, consultation semantics, lab column/FK rates, grouping candidates |
| `unified_v011.source_b_mapping` | promote EXACT/SUPPORTED/HYPOTHESIS from draft + runtime evidence |
| `unified_v011.source_b_load` | PARTIAL Subject/Encounter load; Observation stays unsupported/HYPOTHESIS |
| `unified_v011.orchestrator` | wires semantics → mapping → load |
| `unified_v011.cross_source_v011` | transfer exploration gates (no A/B identity merge) |
| `unified_v011.policy` | `SOURCE_B_SYSTEM_ID = kgz_raw`, decision enums |
| `unified_v011.cli` / `publish` | run/verify/publish plumbing |

**Suggested v0.1.2 extension points:** deepen value parser + unit resolution (`weight_id` → `analyses_weight`) inside semantics/mapping before any Observation promotion; keep using `source_b_connection` for aggregate-only evidence.

---

## Non-claims

- No Observation semantic promotion.
- No A/B identity merge.
- No review ZIP published from this exploration.
- No patient-level data in this artifact.
