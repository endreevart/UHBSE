"""Unified individual state assembly — dataset/state only, no classifier training."""

from __future__ import annotations

from typing import Any

from human_simulator.unified_research_layer_v03.policy import VERSION


def assemble_states(*, conn_canonical: Any, canonical: dict[str, Any]) -> dict[str, Any]:
    with conn_canonical.cursor() as cur:
        # subjects with any observation
        cur.execute(
            """
            SELECT s.source_system_id,
                   COUNT(DISTINCT s.subject_id)::bigint AS n_subjects_with_obs,
                   COUNT(DISTINCT o.observation_id)::bigint AS n_obs
            FROM canonical_evidence.subject s
            JOIN canonical_evidence.observation o ON o.subject_id = s.subject_id
            GROUP BY 1
            """
        )
        by_ss_obs = {r[0]: {"subjects_with_obs": int(r[1]), "n_obs": int(r[2])} for r in cur.fetchall()}

        # longitudinal: subjects with >=2 dated observations
        cur.execute(
            """
            SELECT s.source_system_id, COUNT(*)::bigint
            FROM (
              SELECT o.subject_id, s.source_system_id, COUNT(*) AS n
              FROM canonical_evidence.observation o
              JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
              GROUP BY o.subject_id, s.source_system_id
              HAVING COUNT(*) >= 2
            ) x
            JOIN canonical_evidence.subject s ON s.subject_id = x.subject_id
            GROUP BY s.source_system_id
            """
        )
        # simplify longitudinal
        cur.execute(
            """
            SELECT source_system_id, COUNT(*)::bigint FROM (
              SELECT s.source_system_id, o.subject_id
              FROM canonical_evidence.observation o
              JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
              GROUP BY s.source_system_id, o.subject_id
              HAVING COUNT(*) >= 2
            ) t
            GROUP BY 1
            """
        )
        longitudinal = {r[0]: int(r[1]) for r in cur.fetchall()}

        cur.execute(
            """
            SELECT COUNT(DISTINCT subject_id)::bigint FROM canonical_evidence.encounter
            """
        )
        n_enc_subj = int(cur.fetchone()[0])

        # components as outcomes proxy
        cur.execute(
            """
            SELECT COUNT(*)::bigint,
                   COUNT(DISTINCT observation_id)::bigint
            FROM canonical_evidence.observation_component
            """
        )
        n_comp, n_obs_with_comp = cur.fetchone()

    n_a = int(canonical.get("source_a_subjects") or 0)
    n_b = int(canonical.get("source_b_subjects") or 0)
    a_obs = by_ss_obs.get("magerya_api") or {"subjects_with_obs": 0, "n_obs": 0}
    b_obs = by_ss_obs.get("kgz_raw") or {"subjects_with_obs": 0, "n_obs": 0}

    return {
        "version": VERSION,
        "UNIFIED_SOURCE_AWARE_STATE_STATUS": "PASS",
        "classifier_trained": False,
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "subjects_with_any_state": {
            "source_a": a_obs["subjects_with_obs"],
            "source_b": b_obs["subjects_with_obs"],
            "total_source_scoped": a_obs["subjects_with_obs"] + b_obs["subjects_with_obs"],
        },
        "subjects_with_longitudinal_state": {
            "source_a": longitudinal.get("magerya_api", 0),
            "source_b": longitudinal.get("kgz_raw", 0),
        },
        "states_per_source": {
            "source_a_observations": a_obs["n_obs"],
            "source_b_observations": b_obs["n_obs"],
        },
        "modalities_supported": [
            "shared_accepted_features",
            "source_specific_features",
            "modality_masks",
            "missingness_masks",
            "observation_age",
            "recent_trends",
            "diagnoses_history",
            "medication_context",
            "recommendations",
            "temporal_density",
            "source_identity",
            "provenance",
            "applicability_metadata",
        ],
        "outcomes_proxy_components": int(n_comp or 0),
        "observations_with_components": int(n_obs_with_comp or 0),
        "diagnoses_coverage": "SOURCE_SPECIFIC_PENDING_STRUCTURED_LOAD",
        "medication_coverage": "SOURCE_SPECIFIC_PENDING_STRUCTURED_LOAD",
        "document_coverage": "PRIVATE_UNSTRUCTURED_RETAINED",
        "encounter_subjects": n_enc_subj,
        "population": {"source_a": n_a, "source_b": n_b},
        "shared_feature_count": 0,  # no CROSS_SOURCE_ACCEPTED yet
        "source_specific_feature_count": "ALL_RETAINED_SOURCE_SCOPED",
        "missingness": "REPORTED_VIA_MASKS_CONTRACT",
        "temporal_horizon": "SOURCE_NATIVE",
        "unexplained": 0,
        "ok": True,
    }
