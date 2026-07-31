from human_simulator.audit.discover import discover_schema


def test_discover_schema(disposable_engine) -> None:
    result = discover_schema(disposable_engine)
    names = {(t["schema"], t["name"]) for t in result["tables"]}
    assert ("main", "empty_table") in names
    assert ("main", "patients") in names
    assert result["table_count"] >= 4


def test_discover_unknown_type_column(disposable_engine) -> None:
    result = discover_schema(disposable_engine)
    unsupported = next(t for t in result["tables"] if t["name"] == "unsupported")
    assert unsupported["columns"][1]["name"] == "unknown_type_col"
