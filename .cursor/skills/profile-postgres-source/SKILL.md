---
name: profile-postgres-source
description: Safely profile one PostgreSQL clinic database.
disable-model-invocation: true
---

Profile exactly one configured PostgreSQL source.

Local profiling code may read complete rows.

Raw values must not be printed, logged or returned to Cursor.

The skill may calculate aggregates and identify relationships using
row-level processing inside the local runtime.

Order:

1. Validate that the connection to the original restored database is read-only.
2. Record PostgreSQL version and database metadata.
3. Discover schemas, tables, views and materialized views.
4. Discover columns and data types.
5. Discover primary keys, foreign keys and indexes.
6. Produce estimated row counts.
7. Classify potentially sensitive columns from names and types.
8. Run approved profiling (aggregates, relationship detection, local row-level analysis).
9. Generate sanitized artifacts for Git and agent context.

Stop if write permissions or unsafe configuration are detected on the original restored database.
