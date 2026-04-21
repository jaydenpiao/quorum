# Product framing

Quorum is the safety and coordination layer for agentic engineering.

## The problem

Most coding agents behave like a single overprivileged process.

They can:
- inspect code
- inspect telemetry
- propose infrastructure changes

But they do not naturally provide:
- consensus
- policy gating
- rollback
- execution traceability
- post-change recovery logic

## The product

Quorum coordinates multiple specialized agents that:
- inspect different evidence sources
- create structured findings
- propose structured actions
- require quorum before execution
- write every step to an append-only log
- roll back if health checks fail

## The first wedge

The strongest initial wedge is:

**incident investigation + rollback coordinator**

Why:
- high pain
- bounded actions
- clear rollback path
- immediate value
- strong safety story
