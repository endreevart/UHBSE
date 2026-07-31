from human_simulator.audit.aggregates import profile_aggregates
from human_simulator.audit.discover import discover_schema
from human_simulator.audit.structure import profile_structure


def test_profile_aggregates(disposable_engine) -> None:
    schema = discover_schema(disposable_engine)
    structure = profile_structure(disposable_engine, schema)
    result = profile_aggregates(disposable_engine, structure)
    assert result["column_count"] > 0
    assert any(item["column"] == "always_null" for item in result["tables_with_null_only_columns"])


def test_deterministic_aggregate_order(disposable_engine) -> None:
    schema = discover_schema(disposable_engine)
    structure = profile_structure(disposable_engine, schema)
    first = profile_aggregates(disposable_engine, structure)
    second = profile_aggregates(disposable_engine, structure)
    assert first["summary"] == second["summary"]
