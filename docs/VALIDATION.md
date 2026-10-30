# Validation record

Last verified: 17 October 2026.

## Passed

- Installed app and seven DocTypes on the isolated `addons-ai-test.localhost` site.
- Frappe **15.116.1**, ERPNext **15.118.1**, Python **3.11**, MariaDB.
- **38 pure unit tests**: payload mapping, raw-body HMAC, token caching/refresh, origin restrictions, rate limits, timeout/HTTP ambiguity, discounts, rounding checks, tax mismatch, foreign currency, credit-note signs, export requirements and status interpretation.
- **30 ERPNext integration tests**, with every provider request mocked: invoice submit hooks, duplicate queue protection, durable send marker, approved state, uncertain-outcome reconciliation, no-match handling, correction/PUT eligibility, cancellation protection, forbidden generic record mutation, connection identity protection, signed webhook deduplication and cross-organization rejection, ignored untrusted resource URL, inbox persistence, operator roles, real ERP return generation, private PDF/XML attachment storage, explicit UUID linking disabled-connection behavior, dashboard role protection and bulk queue validation.
- Installation setup run repeatedly without duplicate custom fields/workspace.
- Parsed **37 Python modules**, checked **6 JavaScript files** with `node --check`, and validated field ordering in **7 DocType JSON schemas**.
- Built a Python wheel using the declared flit build backend.

All tests passed on the final recorded run. Early tests used an invoice user without accounting roles and an intentionally incomplete PDF fixture; both fixtures were corrected and the expanded suite rerun successfully.

## Not verified / release gates

- **ERPNext/Frappe v16 runtime**: declared target, not installed in this workspace. Run install/migrate plus the integration suite on a disposable v16 site before rollout. Packaging compatibility is not a substitute for runtime testing.
- **Live ArdentaxIT**: no credentials were supplied and no provider invoices were created. Authentication, payload acceptance, code lists, status transitions and signed callback delivery need a real sandbox acceptance exercise.
- **Worker crash durability**: integration tests assert the commit boundary and recovery logic but intercept commits for transactional test isolation; a staging worker-kill exercise should confirm recovery with real commits/Redis workers.
- **Concurrency/load**: uniqueness and locking behavior are implemented, but a multi-worker stress test at your invoice volume has not been run.
- **Browser UI**: form JavaScript syntax and installed workspace/custom-field metadata were verified; the local route was opened and reached the login screen. Existing saved credentials did not authenticate, so an authenticated browser walkthrough was not completed. Server-side dashboard and schema checks passed.
- **Local deployment**: installed on `addons_ai.local` (ERPNext 15.118.1) with zero settings/submissions, following a database and file backup. Seven existing invoices retained their original status, totals, balances and modification timestamps. API delivery remains disabled.
- **Background workers**: restart the existing Bench services before activating API delivery so all long-running Python processes load the newly installed package.

## Acceptance matrix for the deployment team

1. Install/migrate/build on the actual v15 and v16 staging versions you support.
2. Authenticate against the provider sandbox; confirm organization/profile identity in retrieved documents.
3. Submit standard, mixed-rate, inclusive-tax, supported discount, foreign-currency and export samples.
4. Confirm all four reconciled totals, provider type codes, generated XML and printable PDF.
5. Issue full and partial credit notes against approved originals; confirm positive quantities and invoice-number reference semantics.
6. Deliver a real signed callback, duplicate it, reject a corrupted signature and verify scheduled recovery of a missed callback.
7. Simulate a request timeout after provider creation and verify no second POST occurs.
8. Interrupt a worker after the Sending commit; verify recovery marks Unknown and finds the existing document.
9. Confirm Company User Permissions and accounting roles with actual finance users.
10. Confirm incoming purchase resource routing if the review inbox is used; reconcile completeness in the provider portal.
11. Obtain finance/provider approval of the supported scope before enabling the production connection.

## Fynamics 0.3.0 upgrade

38 unit tests and 30 integration tests passed, covering both providers. New checks include OAuth form authentication/cache/refresh, timeout and duplicate-conflict handling, mapped totals/discounts/credit references, C3/C5 approval, UUID mismatch, callback signatures/deduplication/changed updates, read-only callback polling and failed-poll retries, private artifacts and supplier-TRN changes. Provider traffic was mocked throughout.
