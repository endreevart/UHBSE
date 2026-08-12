"""Canonical storage foundation for Stage 03 Implementation Changeset 01.

Scope: an isolated, empty PostgreSQL 16 derived database plus forward-only migrations for
the Source A pilot entities. This package performs DDL and catalog reads only. It contains
no extraction, no transformation and no load of clinical rows.
"""
