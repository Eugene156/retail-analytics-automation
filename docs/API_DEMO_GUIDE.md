# REST API demo: OpenAPI and Postman

## Observed FastAPI contract

On2026-10-11, authenticated `GET http://127.0.0.1:18090/openapi.json`
returned200 with17 paths. Authentication applies before body parsing. Source
hash, explicit timezone offsets, a31-day limit and historical/DST guards remain.
Calculation JSON preserves SQL NUMERIC text; avoid treating JavaScript floating
point comparison as proof of exact financial arithmetic.

The runtime documents health/readiness, comparison calculation, report requests,
case/revision/preview reads, approval-proposal/v2 issuance and reviewer reads.
Request models exist for CalculationRequest, ApprovalRequestV2 and inherited
proposal fields. Many JSON response shapes are unspecified/generic. The runtime
schema names CalculationToken/OwnerReadToken but contains no token values.
Reviewer routes have a separate guard; the schema is not authority to call them.
P2 read tools have no public OpenAPI endpoint; MCP and approval UI are separate.

`/docs` and `/redoc` returned404: built-in Swagger/ReDoc are disabled intentionally.
This task did not enable routes, restart services or alter existing API behavior.

## Public documentation projection

[openapi_demo.json](openapi_demo.json) is OpenAPI3.1, a reviewed eight-path
projection, not a replacement for the full runtime schema. It preserves the
generated CalculationRequest constraints and documents minimum truthful
response shapes, auth, errors, examples and mutation flags. Owner review,
approval, publication and internal tool routes are omitted. Examples are
synthetic; the projection does not invent report results or credentials.

For Swagger visual documentation without changing the local service, optionally
open [Swagger Editor](https://editor.swagger.io/) and import/paste only this
public projection. It supports OpenAPI visualization; see
[official documentation](https://swagger.io/open-source/swagger-editor/).
This is an external viewer, not a newly deployed local Swagger UI. Do not paste
tokens, import the private observed snapshot, authorize, or use Try it out there.
No browser upload or external API operation was performed during this task.
Enabling a local runtime Swagger UI would require separately authorized API
documentation-route changes and deployment; it is not required for this export.

## Postman setup

1. In your existing Postman, import [postman_collection.json](postman_collection.json)
   and [postman_environment.template.json](postman_environment.template.json).
   Postman was not installed or launched by this task.
2. Select the imported environment. Set `base_url` to the isolated demo API,
   normally `http://127.0.0.1:18090`. Requests use variables, not embedded hosts.
3. Supply `api_token` only as a private local secret/current value, or adapt the
   variable to your existing local Vault. Obtain the fresh demo token locally
   from `.local/p1-demo/api/token`; never paste it into a shared collection,
   shared/cloud environment, screenshot, saved response or Git. Masked type
   alone does not prove that a Postman workspace keeps values off the cloud.
4. Keep `allow_state_changes=false`, `demo_target_confirmed=false` and
   `idempotency_key` blank. Filled environment exports are ignored by Git when
   named `*.postman_environment.json`; do not overwrite the blank template.
5. Run **Safe smoke (no business writes)** first. Calculator timeout can reach
   120s; configure your client timeout above that if needed. No LLM is involved.

## Requests and authority

| Folder | Requests | Preconditions/effect |
| --- | --- | --- |
| Safe smoke | Health, authenticated readiness/OpenAPI, anonymous readiness401, comparison POST, invalid comparison422 | Six requests; calculation POST is read-only, invalid body is rejected before SQL |
| Read existing case | Case metadata, immutable revision, HTML preview | Three GETs; supply an existing demo `case_id` and `revision=1`; skipped when unprepared |
| STATE CHANGING | Create report draft | One POST; skipped by default; persists a draft, without approval/publication |

Ten requests total: seven GETs and three POSTs. Collection auth uses `api_token`;
public health and anonymous401 override it with noauth. Tests check status and
small JSON response schemas or HTML content type. Saved responses are explicitly
synthetic and not live test evidence. The loopback guard rejects a non-loopback
base URL before sending; it is a client convenience, not backend authorization.

For draft creation, first obtain owner approval for that specific action and
confirm the target is the isolated demo. Then set both opt-in flags to `true`
and a fresh8-128-character alphanumeric/underscore/hyphen `idempotency_key`.
Run that individual request. Expect200 or202 with Location; on202, reuse the
**same key and payload** to resume, never change the payload under that key.
Set the returned case UUID manually for reads. Reset the flags after use.
Approval/publication requests are intentionally absent from this collection.

Guards use the supported pre-request
[pm.execution.skipRequest](https://learning.postman.com/v11/docs/tests-and-scripts/write-scripts/postman-sandbox-reference/pm-execution).
Check your Postman client's support before any optional mutation. Import and
Runner behavior require manual confirmation; no Postman runtime run is claimed.

## Verification and remaining manual checks

CI runs portable pytest checks of route/projection consistency, internal refs,
minimum response examples, request constraints, variables/blank secrets, auth,
mutation marks and skip-script presence. This is structural validation of the
features used here, not a full official OpenAPI/Postman JSON Schema validator.
Local Node syntax and mocked skip behavior are checked separately; no REST
POST, case creation, Docker operation, LLM call or filled export is performed.

Pending manual checks: Swagger rendering, Postman import, skip behavior in your
client, safe smoke assertions against the live API and prepared case reads.
Optional mutation requires its own authorization. These are not CI deployment
or live integration claims. Publication safety must be checked again before
including any new screenshots or real saved responses.
