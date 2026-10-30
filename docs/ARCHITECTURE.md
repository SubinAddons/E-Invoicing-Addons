# Architecture

## Data flow

1. `events.before_submit` validates opted-in invoice mappings without network calls.
2. `events.on_submit` creates a unique submission if auto-submit is enabled, in the same ERP database transaction.
3. `service.enqueue` schedules work after the transaction commits. A scheduler recovers queue-loss cases.
4. `jobs.send` locks the submission and the source invoice, verifies eligibility and commits a Sending marker before an external POST/PUT.
5. The worker persists provider identity, response, reconciled totals and processing status. Errors with uncertain outcomes become Unknown.
6. `webhooks.accept` verifies the raw signed body, validates organization/profile and persists a deduplicated event before acknowledging.
7. `webhooks.process` retrieves current provider state through fixed routes. Matched outbound documents refresh; unmatched resources enter a review inbox.
8. `jobs.refresh` is always read-only externally. An Unknown submission is resolved by a unique verified provider match or explicit verified UUID.

## Modules

| Module | Responsibility |
| --- | --- |
| domain.py | Pure Decimal mapping, HMAC signing, reconciliation and status interpretation |
| client.py | Origin validation, token caching, bounded HTTP reads, throttling, no ambiguous write retries |
| service.py | ERP data loading, immutable submission creation, auditing and provider identity validation |
| events.py | ERP Sales Invoice lifecycle hooks and cancellation protection |
| jobs.py | Durable send, status retrieval and scheduled recovery |
| webhooks.py | Signed event inbox and asynchronous processing |
| api.py | Permission-checked Desk actions and public signed callback |
| controllers.py | Protected record mutation and connection identity validation |
| permissions.py | Company/source-document checks and operator authorization |
| install.py | Custom fields, role and Desk workspace |

## Consistency model

Exactly-once delivery cannot be guaranteed across independent databases without provider idempotency. This app chooses a conservative at-most-once automatic creation policy: the Sending marker commits before the HTTP request, and ambiguous failures require reconciliation. It does not invent an idempotency header that the provider has not documented.

Redis locks serialize work on one submission. The database source-key uniqueness prevents repeated invoice queue actions from creating multiple submissions. Source-invoice row locks serialize cancellation and first send. Provider UUID association is unique by environment and organization. Network timeouts are bounded; interrupted Sending records become Unknown after ten minutes.

The background job is intentionally the transaction boundary for remote effects; no commit is performed inside the Sales Invoice hooks. If response persistence fails after a successful external write, the committed Sending marker survives and recovery reconciles it.

## Accounting model

Final ERP `net_amount` is the input, including item and supported document discounts and inclusive-tax back-calculation. It is divided by quantity into a six-decimal unit price, and mapping rejects any line whose two-decimal amount cannot be reproduced. The mapper uses configured tax categories and validates their rates against the ERP tax row/item override. It checks net, tax and gross totals before sending; it checks returned net, tax, gross and payable totals afterward.

This release intentionally rejects accounting shapes whose semantics are not implemented. It does not use zero-rated/exempt/out-of-scope interchangeably. All return quantities are normalized once to positive provider credit-note quantities, with a per-connection contract-verification switch.

## Permissions

System Manager configures credentials. Addons E Invoice Operator can invoke actions only when normal ERP permissions also allow reading/submitting the source Sales Invoice. Company User Permissions constrain logs. Protected audit documents reject ordinary create/update/delete operations; an internal request-local flag is set only in server code, never trusted from a submitted Document flags object.

API responses never contain credentials. Payloads and provider responses are financial records and are visible only through the relevant DocType permissions. PDF/XML files are private and attached to the protected submission. The public webhook uses its separate signing secret and verifies organization/profile. Provider resource URLs from notifications are ignored.

## Compatibility

No Sales Invoice controller overrides, monkey patches or core source edits are used. Frappe hooks, DocTypes, whitelisted methods, workers, Redis cache, private File storage and the Desk form API are used across the v15/v16 target. SQL row locks currently target MariaDB. Runtime verification on v16 is an explicit release gate; the package version range alone is not proof of v16 testing.
