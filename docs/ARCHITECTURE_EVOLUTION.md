# Architecture Evolution

The proposed four-phase evolution is needed, but it should frame the roadmap rather than expand the 7-day MVP scope.

## Phase 1: Modular Refactor And Clean Codebase

This MVP implements Phase 1 foundations:

- Modular Python monorepo.
- Shared bus, HITL, taxonomy, ledger, KG, and common packages.
- Layer boundaries enforced through typed events.
- Tests around critical behavior.
- Documentation separating implementation-owned setup from client-provided secrets/access.

## Phase 2: Agent Capabilities And Workflows

This MVP implements a narrow Phase 2 slice:

- External signal ingestion.
- Deterministic relationship matching.
- General outreach draft/approval/send guard.
- Six specialist drafting adapters behind the approval queue.

Deep agent expansion remains future work after the happy path is proven.

## Phase 3: Orchestration And Memory Systems

Not in MVP scope. Future work should add:

- Durable workflow orchestration.
- Long-term memory and richer relationship intelligence.
- Production knowledge graph client.
- NATS JetStream or equivalent production bus.

## Phase 4: Production Readiness

Not in MVP scope. Future work should add:

- Production monitoring and alerts.
- Scalability and resilience hardening.
- Public/internal APIs.
- Real portal integrations with counsel/regulatory review.
- External ledger anchoring.

