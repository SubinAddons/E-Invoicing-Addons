# Addons - E invoicing for ERPNext

A standalone Frappe app connecting ERPNext Sales Invoices and Credit Notes to ArdentaxIT and Fynamics UAE e-invoicing APIs. The app targets **ERPNext/Frappe 15 and 16**, uses the **20260507** provider contract, and installs disabled by default.

**Release 0.3.0 is a sandbox-first implementation, not a provider-certified connector.** Runtime integration tests have been performed on ERPNext 15.118.1 / Frappe 15.116.1. A v16 installation and live ArdentaxIT sandbox acceptance remain required before claiming production readiness on v16. No credentials are included and no real invoices were transmitted during development.

## Included

- Company-specific connections with encrypted Password fields and pinned environment/API version.
- Customer TIN, legal name, email and Peppol endpoint fields; structured address region codes.
- Explicit UOM and item tax-template mappings.
- Sales Invoice preview, pre-submit validation, manual or automatic asynchronous submission.
- ERPNext return Sales Invoice → sales credit note, linked to an approved original submission.
- Immutable request snapshots, payload hashes, provider UUIDs, amount reconciliation and audit records.
- Token caching and refresh, account-level rate limiting, bounded retries for throttling.
- Durable Sending state before external writes; uncertain writes never automatically repeat.
- Signed webhook verification, deduplication, durable processing, secret-rotation overlap and retry tools.
- Overall, C3 participant and C5 tax-reporting statuses stored separately from ERP accounting status.
- Private PDF and XML downloads.
- Five-minute scheduler recovery for pending work and missing callbacks.
- Review inbox for unmatched sales/purchase webhook resources; it does not post Purchase Invoices to the ledger.
- A Desk workspace, status dashboard, company settings, invoice actions and bulk queueing (up to 50 invoices).

## Provider scope

The app is branded **Addons - E invoicing** and can be installed for multiple companies. This release supports **ArdentaxIT** and **Fynamics**, selected per company. Fynamics has a separate OAuth client, payload mapper, status lifecycle and signed webhook handler. See [Fynamics setup and limits](docs/FYNAMICS.md). One company selects one provider; provider/account identity is frozen after history exists. Changing a URL does not make any other API compatible. The supplied UAE ERPGulf marketplace app was reviewed as a workflow reference; its code and provider implementations are not bundled.

## ArdentaxIT accounting scope

The initial release deliberately validates a bounded set of transaction shapes:

| Supported | Limits |
| --- | --- |
| Business customers | UAE business or foreign business; individuals/B2C need a separately confirmed classification mapping |
| Normal sales and sales returns | No POS invoices, write-offs or debit notes |
| Standard, export and e-commerce profiles | Other profile flags are rejected |
| AED and foreign currency | Foreign currency needs an explicit AED-per-invoice-currency rate |
| Standard, zero, exempt and out-of-scope tax categories | `S`, `Z`, `E`, `O`; `E` requires provider reason code and matching text |
| One `On Net Total` VAT row | Item Tax Templates can override its rate; compound taxes and commercial charge rows are rejected |
| Tax-inclusive prices | Maps ERP's calculated tax-exclusive line amounts |
| Item discounts and additional Net Total discount | Maps final net amounts once; does not duplicate discounts in allowances |
| Currency rounding | Provider totals must match the frozen ERP amounts to two decimal places |

Not implemented: self-billed purchase creation, automatic supplier-invoice accounting, proforma invoices, document-register uploads, sending attachments, advances/prepayments, freight/compound charge mappings, special FTZ/deemed/agent/summary/continuous-supply profiles. These are not silently converted to ordinary invoices.

Purchase APIs issue **self-billed** documents. Do not treat ordinary ERPNext Purchase Invoice submission as authorization to issue a self-billed document.

## Install on ERPNext v15 or v16

Use a matching Frappe/ERPNext major version and a host that permits custom apps. Use the Python, Node and database versions supported by that Bench (v16 has newer runtime requirements). MariaDB is the tested database.

From the Bench directory, with this app's repository available locally:

```sh
bench get-app addons_einvoicing https://github.com/SubinAddons/E-Invoicing-Addons.git
bench --site staging.example.com install-app addons_einvoicing
bench build --app addons_einvoicing
bench --site staging.example.com migrate
bench --site staging.example.com enable-scheduler
bench restart
```


Do not install Frappe or ERPNext from PyPI. Bench manages those apps. Keep the **short** and **default** queue workers running: submissions use short; webhook processing uses the default queue.

Installing this app does not enable or submit existing invoices. Existing apps and core ERP controllers are not overridden.

## ArdentaxIT setup checklist

1. **ArdentaxIT:** obtain sandbox access, enable API Integration, complete/confirm business onboarding and obtain the organization UUID and business profile ID. The Client ID (`org_...`) is not necessarily the organization UUID (`org_id`).
2. Open **Addons - E invoicing → Connections** as System Manager. Create one connection per ERP Company.
3. Keep environment **Sandbox**, base URL `https://api-sandbox.ae.ardentaxit.tax`, version `20260507`. Enter Client ID, Client Secret, organization UUID and business profile ID.
4. Add UOM mappings, e.g. your `Nos` to the provider-approved `EA`. Confirm codes against the provider code lists.
5. Add tax mappings. A row with a blank Item Tax Template is the default for invoice lines with no template. Add one row per other template you use. For standard VAT use category `S`, rate `5`. Exempt `E` needs both exemption code and exact description. Do not infer categories from rates alone.
6. Save and use **Test Authentication**. This performs a token request only and does not submit an invoice. Token responses accept `token` or `access_token`, with `expires_at`.
7. Configure customer fields: legal name, e-invoice email, TIN (UAE businesses), Peppol endpoint and endpoint scheme. Existing `Customer.tax_id` supplies the UAE VAT TRN, if applicable. TIN and VAT TRN are separate.
8. On billing/shipping Address records, fill **E-Invoice Region / Emirate Code**. UAE codes: `DXB`, `AUH`, `SHJ`, `UAQ`, `FUJ`, `AJM`, `RAK`. Ensure Country has its ISO alpha-2 code.
9. Assign **Addons E Invoice Operator** alongside normal ERPNext accounting roles that permit reading and submitting Sales Invoices (for example Accounts User/Accounts Manager). The app role does not grant ERP permissions or credential access. Apply Company User Permissions normally.
10. Enable the connection. Initially leave **Queue on Sales Invoice Submit** off to test manual submission.
11. On a draft invoice, enable **Enable E-Invoicing**. Choose invoice type and transaction profile, payment means code, actual supply date and foreign-currency rate when applicable.
12. Save, then select **E-Invoice → Validate / Preview**. Review the JSON and expected totals.
13. Submit the invoice in ERPNext. Select **E-Invoice → Queue Submission**. Alternatively turn on auto-submit on the connection after the manual flow is verified.
14. Review the resulting Addons E Invoice Submission. **Created** is not Peppol approval. Inspect `overall_status`, C3 participant status and C5 FTA status. Use **Refresh / Reconcile** or wait for callbacks/scheduler recovery.
15. Use **Fetch PDF and XML** to save private artifacts. Downloads are explicit; they are not sent to the customer automatically.

### Credit notes

Use ERPNext's standard return/credit-note workflow against an original invoice with an **Approved** Addons E Invoice Submission on the same connection. Select a discrepancy code. Type `380` maps to credit-note type `381`; `480` maps to `81`.

First confirm positive credit quantities/amounts and `billing_reference[].id` as the original document number with ArdentaxIT in sandbox, then enable **Credit Note Contract Verified** on the connection. The implementation preserves original issue date from the submitted payload. Accounting amounts must not change during a correction/resubmission.

### Foreign currency and time

Enter **AED per Invoice Currency Unit**, e.g. `3.6725` for a USD invoice where that is the approved rate. The integration does not assume the Company's base currency is AED. ERP posting date/time is converted from the site's configured timezone to `Asia/Dubai`, including date rollover. Confirm this matches your accounting issuance policy. Actual supply date is sent as a date; the app does not send `tax_point_date`.

## Webhooks

1. Make the ERPNext site accessible over HTTPS using your normal reverse proxy.
2. Save the connection and copy its **Webhook URL**, which points to:
   `/api/method/addons_einvoicing.api.webhook?connection=<URL-encoded-connection-name>`
3. Configure that exact URL in ArdentaxIT and subscribe to sale invoice/credit note create/update events. Purchase events can populate the review inbox if your provider subscription routes them there.
4. Put the provider's **webhook signing secret** into the connection. It is separate from the API Client Secret.
5. Test a real provider event. The endpoint computes Base64 HMAC-SHA256 over the exact raw body, verifies organization/profile, persists the event, queues work after commit and returns HTTP 200 through Frappe's normal JSON response.
6. During secret rotation, place the retiring secret in **Previous Webhook Secret** for a short overlap. Remove it after rotation completes.

`resource_url` is never followed; retrieval paths are built from the configured origin and verified resource UUID. Duplicate event IDs are acknowledged without duplicate processing. Invalid signatures are rejected. Configure reverse-proxy request/rate limits for the public callback endpoint. Notifications are hints to fetch the latest state, not a complete ordered event ledger.

The inbox stores verified documents for review only. It does not infer an ERP supplier, match PO/receipt rows or create accounting entries. There is no inbound historical backfill in this release; reconcile inbound completeness with the provider portal.

## Failure handling

| Status | What to do |
| --- | --- |
| Queued | Wait for the short worker; the scheduler re-enqueues stranded pending records |
| Sending | API attempt started and was committed locally before the request |
| Retry | Rate-limited; scheduled backoff is pending, capped at eight retries |
| Unknown | Timeout, ambiguous response or interrupted worker. Never click/create a replacement invoice to retry |
| Created / Processing | Provider resource exists; await processing and reconciliation |
| Approved | Provider overall status is APPROVED and returned amounts match |
| Validation Failed | Fix source master/metadata, then **Rebuild and Retry**; full-payload PUT rechecks provider eligibility |
| Rejected | Review provider reasons and resolve through the provider's supported business workflow |
| Mismatch | Provider amounts differ. UUID is retained; investigate instead of resubmitting |
| Error | Definite API rejection or exhausted throttling retries. Review Audit Trail and correct before **Rebuild and Retry** |
| Stopped | ERP invoice was cancelled before any remote attempt |

For Unknown, **Refresh / Reconcile** searches by document number and verifies organization, business profile, currency and totals. It never creates when no match is found. **Link Existing Provider UUID** performs a verified GET when support/dashboard supplies the exact UUID. If the provider confirms no document exists but lookup still cannot resolve it, escalation to the integration maintainer is required; no unsafe force-create button is provided.

After any external attempt, ERP invoice cancellation is blocked so accounting cannot silently diverge from external issuance. Resolve the external state and use the approved credit-note workflow. Do not edit the database to bypass this protection.

Failed webhook processing retries up to eight attempts, then remains visible as Error. An operator can select **Retry Processing** after resolving the cause.

To pause new sending and polling, disable the connection. Signed webhook events can still be durably received and wait for re-enablement. Existing accounting documents are unchanged. The app does not automatically email invoices or block all other ERP printing/email paths; your operational workflow must govern customer delivery while e-invoicing is pending.

## Environment and data protection

Use a **separate staging site** for sandbox, and a fresh connection on the production site. Connection identity/environment cannot change once submission history exists. This prevents old jobs or callbacks being processed with another environment or company identity.

Before enabling production:

- Obtain the exact production API origin and production credentials from ArdentaxIT. Only HTTPS origins under `.ae.ardentaxit.tax` are accepted; redirects are not followed.
- Finish onboarding and provider sandbox acceptance for each transaction shape you use.
- Test installation and acceptance on your actual ERPNext major version and custom app combination.
- Complete the Sandbox Acceptance checkbox and intentionally enable production/auto-submit.
- Confirm financial rounding, credit-note references, code lists, status behavior and access permissions.

Credentials use Frappe's encrypted Password storage; back up the site's encryption key through your normal backup process. Access tokens are cached in Redis, so Redis must remain private to the site infrastructure. Do not log credentials or HMAC headers. Preserve the audit records and private XML/PDF artifacts according to your organization's retention policy; no automatic deletion is implemented.

## Tests and packaging

Pure mapping/client tests need Python and requests, not a site:

```sh
PYTHONPATH=. python -m unittest discover -s tests -v
```

Integration tests need an isolated installed ERPNext site. They create test accounting fixtures and mock all provider HTTP:

```sh
bench --site disposable-test.local run-tests --app addons_einvoicing
```

Never run integration tests on a production site. The tests use transaction savepoints and intercept worker commits for rollback; production workers still perform real durable commits. A real ArdentaxIT sandbox exercise is separately required.

See [validation](docs/VALIDATION.md), [architecture](docs/ARCHITECTURE.md), and [provider references](docs/PROVIDER_CONTRACT.md).
