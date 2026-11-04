# WP1 process models

Status: BPMN XML and diagram references verified in the current environment; business behavior remains planned. The models follow the [OMG BPMN 2.0.2 specification](https://www.omg.org/spec/BPMN/2.0.2), but they have not been validated against the complete OMG XSD set or visually reviewed in a BPMN editor.

| Model | File | Interpretation |
| --- | --- | --- |
| AS-IS | `docs/WP1_AS_IS.bpmn` | Illustrative manual procedure for the owner's baseline exercise. It is **not** an observed workflow of the historical retailer. The local file/spreadsheet lane represents assumed manual aids; no elapsed time is asserted. |
| TO-BE | `docs/WP1_TO_BE.bpmn` | Planned local automation. Deterministic SQL evidence precedes optional model text, human approval binds the exact revision, and only then can an outbox action publish. |

The TO-BE model routes invalid source evidence to an unpublished end, invalid or timed-out local-model output to a deterministic-only draft, rejection and expired/changed approval to no-action ends, and uncertain publication to operator reconciliation before a safe retry decision. These are design controls, not implemented or end-to-end tested behavior. The 30-second model timer is a diagram assumption to confirm against actual service performance and policy; it is not a measured SLA.

Run `pwsh -NoProfile -File scripts/validate-wp1-bpmn.ps1` from the repository root. This checks XML parsing, unique IDs, lane coverage, flow endpoints and incoming/outgoing declarations, all diagram shapes/edges, and the key timeout/rejection/reconciliation routes. It does not prove BPMN schema conformance, editor readability, executable n8n behavior, or owner-observed AS-IS timing.

Next evidence: observe and time the owner's actual manual procedure using `docs/MEASUREMENT.md`, then revise AS-IS if the observed steps differ. Later implementation and tests must reconcile TO-BE to the released workflow before AC-26 can pass.
