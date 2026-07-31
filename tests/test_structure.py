from human_simulator.audit.discover import discover_schema
from human_simulator.audit.structure import profile_structure


def test_profile_empty_table(disposable_engine) -> None:
    schema = discover_schema(disposable_engine)
    profile = profile_structure(disposable_engine, schema)
    empty = next(t for t in profile["tables"] if t["name"] == "empty_table")
    assert empty["estimated_rows"] == 0
    assert empty["columns"][1]["null_pct"] == 0.0


def test_profile_null_only_column(disposable_engine) -> None:
    schema = discover_schema(disposable_engine)
    profile = profile_structure(disposable_engine, schema)
    table = next(t for t in profile["tables"] if t["name"] == "null_only")
    null_col = next(c for c in table["columns"] if c["name"] == "always_null")
    assert null_col["null_pct"] == 100.0


def test_profile_malformed_date_column(disposable_engine) -> None:
    schema = discover_schema(disposable_engine)
    profile = profile_structure(disposable_engine, schema)
    table = next(t for t in profile["tables"] if t["name"] == "patients")
    raw = next(c for c in table["columns"] if c["name"] == "visit_date_raw")
    assert raw["null_pct"] == 0.0
