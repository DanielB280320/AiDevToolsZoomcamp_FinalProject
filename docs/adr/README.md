# Architecture decision records

Each ADR records one design decision with trade-offs: its context, the decision, the alternatives and the consequences. The short list of all product decisions is the [spec decisions log (§19)](../spec.md#19-decisions-log); ADRs explain the ones that shape the architecture. The overview is in [architecture.md](../architecture.md).

| ADR | Title | Status |
|---|---|---|
| [0000](0000-template.md) | Template | n/a |
| [0001](0001-stack-fastapi-react-postgres.md) | Use FastAPI, React and PostgreSQL as the stack | Accepted |
| [0002](0002-ec2-docker-compose-deployment.md) | Deploy with Docker Compose on two EC2 instances | Accepted |
| [0003](0003-plain-http-known-limitation.md) | Serve the MVP over plain HTTP as a documented limitation | Accepted |
| [0004](0004-pure-calculation-engines.md) | Keep calculation engines pure, deterministic and explainable | Accepted |
| [0005](0005-contract-first-openapi.md) | Make openapi.yaml the API source of truth | Accepted |
| [0006](0006-self-hosted-observability-on-prod.md) | Self-host the observability stack on the prod EC2 instance | Accepted |
| [0007](0007-on-call-agent-with-allow-listed-mitigations.md) | Limit the on-call agent to allow-listed runtime mitigations | Accepted |

## Adding an ADR

1. Copy [0000-template.md](0000-template.md) to `NNNN-kebab-case-title.md` with the next free number.
2. Fill in every section; link the spec sections it relates to.
3. Add it to the table above, to [architecture.md §6](../architecture.md#6-key-design-decisions) and, if it changes behaviour, to the spec in the same PR ([process.md §8](../process.md#8-changing-the-spec)).
4. ADRs are never deleted or renumbered. A changed decision gets a new ADR, and the old one is marked "Superseded by".
