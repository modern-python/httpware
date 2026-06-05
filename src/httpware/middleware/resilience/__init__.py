"""Resilience primitives: Retry middleware and RetryBudget token bucket.

Re-exports land in Task 7 once both classes exist; until then this file is
docstring-only so that importing ``httpware.middleware.resilience.budget``
during the intermediate tasks does not trip an import-time ``ImportError``.
"""
