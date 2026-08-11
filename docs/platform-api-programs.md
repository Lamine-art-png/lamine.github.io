# Platform API programs

An active, effective, unexpired enrollment is required when a Phase 2 program
flag is enabled. Organization verification always remains authoritative.

| Program | Normal environment | Billing | Approval |
| --- | --- | --- | --- |
| `internal` | test | internal | platform review |
| `developer_private_beta` | test | none/custom | platform review |
| `developer_self_service` | test; live after review | API plan | enrollment and live review |
| `strategic_partner` | test; negotiated live | contract/invoice | technical and commercial review |
| `enterprise_custom` | explicit | contract/Stripe | enterprise review |

Enrollments carry explicit project, live-project, service-account, key, webhook,
provider, resource, rate, quota, retention, support, and expiry limits. No value
means unlimited; a custom limit must be recorded explicitly.

Suspending an enrollment makes associated keys fail on their next request.
Pending, rejected, blocked, suspended, verification-required, and unknown
organization statuses fail closed.
