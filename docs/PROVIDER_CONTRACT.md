# Provider contract and outstanding acceptance

Reviewed ArdentaxIT Business API documentation for contract `20260507` on 16 October 2026. Documentation is evidence of the intended API, not a live acceptance test.

## Implemented routes

- `GET /auth/token?client_id=...` with Base64 HMAC-SHA256(Client Secret, Client ID).
- `POST /api/sales-invoices/{business_profile_id}`.
- `GET /api/sales-invoices/{id}` and `GET /api/sales-invoices?document_number=...`.
- `PUT /api/sales-invoices/{uuid}/{business_profile_id}` only for fresh `VALIDATION_FAILED` state.
- Corresponding `sales-credit-notes` resource routes for credit notes.
- `/api/{sales-resource}/{id}/download-pdf` and `/api/{sales-resource}/{id}/xml`.
- Verified purchase webhook resources use the corresponding purchase retrieval routes for review only.

`X-API-Version: 20260507` is sent throughout. `payment_means` is an array. Customer endpoint fields are explicit. Supplier party is derived by the provider from the profile URL, so the mapper does not send it. System/calculated fields are not echoed back in create/resubmit payloads.

Status interpretation uses `meta_info.peppol_status.overall_status` on document retrieval: APPROVED, REJECTED, VALIDATION_FAILED, PENDING. C3 participant and C5 FTA diagnostics are retained separately. No success is inferred from HTTP 201 or a UUID alone.

## Provider confirmations still needed

- Authentication response casing/shape and token lifetime against a real account.
- Production origin, organization UUID, business profile and account/subscription permissions.
- Positive credit-note quantity/amount convention and original document number in `billing_reference[].id`.
- Credit-note type 381/81 selection. The create schema requires the type although the overview describes automatic assignment.
- Payment means conditional requirements: the change log and implementation notes differ; this app requires it for supported ordinary sales.
- Tax code/reason lists, all-zero/exempt type 480 semantics, price precision and amount rounding.
- Customer endpoint substitutions and classifications for actual business scenarios.
- Whether inbound purchase events expose the expected purchase retrieval route for the subscribed account; no historical inbound backfill is implemented.
- Provider idempotency and duplicate-lookup guarantees; this app makes no idempotency-key assumption.
- PDF/XML download and attachment behavior. Uploading attachments is outside this release.
- Final status transitions, webhook retry schedule and onboarding completeness.

## Primary references

- [Business integration overview](https://docs.ae.ardentaxit.tax/docs/2026-05-07/flow/businesses)
- [Authentication](https://docs.ae.ardentaxit.tax/docs/2026-05-07/flow/businesses/auth/api-keys)
- [Business profiles](https://docs.ae.ardentaxit.tax/docs/2026-05-07/flow/businesses/party-management/business-profiles/what-is)
- [Sales invoice create](https://docs.ae.ardentaxit.tax/docs/2026-05-07/flow/businesses/sale-documents/sale-invoices/create)
- [Sales invoice retrieve and processing states](https://docs.ae.ardentaxit.tax/docs/2026-05-07/flow/businesses/sale-documents/sale-invoices/retrieve)
- [Resubmit](https://docs.ae.ardentaxit.tax/docs/2026-05-07/flow/businesses/sale-documents/sale-invoices/resubmit)
- [Credit note create](https://docs.ae.ardentaxit.tax/docs/2026-05-07/flow/businesses/sale-documents/sale-credit-notes/create)
- [Webhook signing](https://docs.ae.ardentaxit.tax/docs/2026-05-07/flow/businesses/integration/webhooks/signature-verification)
- [Implementation notes](https://docs.ae.ardentaxit.tax/docs/2026-05-07/flow/businesses/supporting-resources/implementation-notes)
- [Version changes](https://docs.ae.ardentaxit.tax/docs/2026-05-07/flow/businesses/api-versioning/change-log)
- [Frappe v16 migration guide](https://github.com/frappe/frappe/wiki/Migrating-to-version-16)
