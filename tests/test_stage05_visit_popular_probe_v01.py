"""The popular-label probe returns one short label and does not open Gate 2."""

from __future__ import annotations

import json

import pytest

from human_simulator.stage05_visit_popular_probe_v01.probe import STAGE_SQL, parse_stage_payload


def _payload() -> dict:
    return {
        "probe_label": "магний",
        "visits": 10,
        "recommendation_visits": 8,
        "catalog_visits": 3,
        "tie_count": 1,
        "pairs": 4,
        "examination": {
            code: {
                "pairs": 4,
                "both_empty": 1,
                "only_previous": 1,
                "only_next": 0,
                "same_text": 1,
                "text_changed": 1,
            }
            for code in ("goal", "complaints", "anamnesis", "objective_status", "local_status")
        },
        "shared_lab_pairs": 1,
        "shared_lab_values_unchanged_pairs": 1,
        "shared_lab_values_changed_pairs": 0,
        "GATE_2_STATUS": "CLOSED",
        "eligible_cells": 0,
        "effect_claimed": False,
    }


def test_sql_has_no_placeholder_wildcard() -> None:
    assert "%" not in STAGE_SQL
    assert "LIMIT 1" in STAGE_SQL


def test_parser_accepts_one_object() -> None:
    parsed = parse_stage_payload("SET\n" + json.dumps(_payload(), ensure_ascii=False) + "\n")
    assert parsed["probe_label"] == "магний"
    assert parsed["GATE_2_STATUS"] == "CLOSED"


def test_parser_rejects_an_open_gate_and_a_long_label() -> None:
    opened = _payload()
    opened["GATE_2_STATUS"] = "OPEN"
    with pytest.raises(ValueError):
        parse_stage_payload(json.dumps(opened))
    long_label = _payload()
    long_label["probe_label"] = "слово " * 40
    with pytest.raises(ValueError):
        parse_stage_payload(json.dumps(long_label))
