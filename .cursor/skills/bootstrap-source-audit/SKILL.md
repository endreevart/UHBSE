---
name: bootstrap-source-audit
description: Bootstrap the Stage 01 clinic database audit tool.
disable-model-invocation: true
---

Read AGENTS.md and all project rules.

Create only the infrastructure needed for Stage 01.

Use:

- Python 3.12;
- SQLAlchemy;
- psycopg;
- Pydantic Settings;
- Polars;
- PyArrow;
- pytest;
- structlog or standard structured logging.

Implemented CLI commands:

- audit connection-check;
- audit discover-schema;
- audit profile-structure;
- audit profile-aggregates;
- audit profile-source;
- audit classify-entities;
- audit draft-report;
- audit generate-report;
- audit verify-stage.

Do not connect to a real database during bootstrap.

Create tests using a disposable test database.
