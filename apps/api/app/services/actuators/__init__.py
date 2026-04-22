"""Actuator adapters.

Each subpackage turns approved Quorum proposals into real-world mutations
against a specific target system (GitHub, Kubernetes, Slack, etc.). The
executor owns event emission; actuators return typed records and let the
executor wrap them in ``execution_*`` envelopes per ``AGENTS.md``.
"""
