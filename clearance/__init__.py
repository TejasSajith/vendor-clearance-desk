"""Clearance service layer. New modules around the engine (core, pipeline, policy, decision); it never changes a verdict rule.

  ops        ops_config.json (daily cap, breaker, retention, request limits, size bands; all PROPOSED)
  guard      wraps the check sources: daily cap, circuit breaker, malformed responses -> unreachable, cap alerts, cache-hit log
  schema     purpose-limited request schema
  audit      append-only audit log (approvals, rejections, executions, contests, purges, model calls)
  explain    stored explanation per verdict; contest and linked re-check runs
  retention  purge_personal
  executors  local-only executor (nothing is sent)
  service    one entry point that puts these together
  doctor     health check
CLI: python -m clearance --help
"""
