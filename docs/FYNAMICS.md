# Fynamics setup — Addons - E invoicing 0.3.0

Implemented from the [Fynamics documentation](https://sandbox-uae.fynamicstax.com/docs#description/introduction) and its [published OpenAPI file](https://sandbox-uae.fynamicstax.com/assets/swagger/ae-einve2e.yaml), retrieved 17 October 2026. API calls use `/api/partner` under the provider origin. The documentation's environment selector supplies the real origins; the YAML's localhost server entry is not used.

## Configure and test

1. Open **Addons - E invoicing → Company Settings** on `addons_ai.local` and create the company record. Select **Fynamics**. Existing connections with submission/webhook history cannot be switched to another provider.
2. Keep **Sandbox** and base URL `https://sandbox-uae.fynamicstax.com`. Enter the Fynamics **Client ID** and **Client Secret**. Ardentax organization/profile fields do not apply.
3. Set the Company's VAT TRN. Choose an Address linked to this Company with street, city, UAE country and the e-invoice emirate code. Enter supplier Peppol endpoint/scheme, legal registration ID/scheme, issuing authority and contact email. The Company name is sent as its legal registration name.
4. Add ERP UOM → provider unit mappings and tax-template mappings. This Fynamics release supports domestic AED B2B tax invoices with standard 5% VAT. The buyer needs its legal name, VAT TRN, TIN, endpoint/scheme, email and structured UAE billing address.
5. Save, then use **Test Authentication**. OAuth uses Basic authentication and a form-encoded `client_credentials` grant. Secrets are encrypted Password fields; access tokens are cached and never returned to the browser.
6. Restart existing Bench workers/web processes so they load the upgraded modules. Enable the connection only when ready. Keep automatic submission off for the first sandbox tests.
7. Enable e-invoicing on a test invoice; save and select **Validate / Preview**. Review supplier, buyer, line/tax amounts and payable total. Submit in ERPNext, then **Queue Submission**.
8. Initial acceptance stores the returned UUID and displays **Processing**, not Approved. Use **Refresh / Reconcile**, or leave the scheduler running. Approval requires the final SUCCESS status and both C3/C5 MLS acceptance codes for the supported domestic profile.
9. Configure the app's Webhook URL and signing secret in the Fynamics portal's Sales Webhook settings for this VAT/TRN. Use a public HTTPS URL; localhost cannot receive internet callbacks. Fynamics uses `X-Webhook-Signature: sha256=<hex>` over the raw body. Duplicate payloads are ignored, changed updates for the same UUID are retained, and workers poll the authenticated status endpoint so stale callbacks cannot regress status.
10. Use **Fetch PDF and Compliance Files**. Downloads are restricted to documented paths on the configured provider origin, without redirects, and saved privately. Compliance downloads may be a ZIP or XML; the app does not mislabel a ZIP as XML or unpack it.
11. For credit notes, confirm the 381 type, positive quantities, discrepancy code and original invoice-number/date reference with Fynamics in sandbox, then enable **Credit Note Contract Verified**. Generate the ERP return against an approved original invoice.
12. After sandbox acceptance, deploy/configure production separately using `https://uae.fynamicstax.com`; confirm **Sandbox Acceptance Completed** before enabling it. Do not repoint a historical sandbox connection at production.

## Supported scope and deliberate limits

- Standard domestic UAE B2B AED invoices, 5% VAT, tax-inclusive ERP rates mapped to net rates, and supported net discounts; positive-amount credit notes after explicit sandbox verification.
- Export/e-commerce, foreign currency, zero/exempt/out-of-scope VAT, B2C, self-billed purchases, incoming purchase accounting, advances and complex charges are not mapped in this Fynamics release. They are rejected before transmission.
- The public status response contains UUID and delivery status, **no invoice number, supplier TRN, currency or totals**. The UUID is bound only from the direct create response. ERP amounts are frozen and validated locally; remote amount reconciliation is not claimed. Verify downloaded documents during acceptance.
- No documented sales lookup by invoice number or update/resubmission endpoint is available. A timeout, malformed response or duplicate conflict becomes **Unknown** and is never reposted. Manual UUID linking is blocked because a status-only response cannot prove invoice identity. Resolve the original outcome with Fynamics support. Definite errors without a UUID may be corrected and manually retried.
- Unmatched callbacks remain in Webhook Events for review/retry; they are not attached to a company invoice based on unverified payload data.
- One provider per company connection. The app does not route the same invoice to both providers.

## Public contract discrepancies and acceptance gates

The formal `InvoiceRequest` schema describes lowercase `invoice`, object-valued PaymentMeans/DocumentTaxSubtotal, and tax fields directly under Item. Its concrete POST example instead uses `Invoice`, arrays, and Item.ClassifiedTaxCategory. This implementation follows the concrete enriched-sales POST example. The reference examples also contain inconsistent sample totals; the app computes and validates its own totals. Provider sandbox confirmation is required before live use, particularly header casing, arrays, credit-note references and tax rounding.

No Fynamics credentials were supplied and no provider invoices have been transmitted. All automated provider traffic is mocked. Frappe/ERPNext v16 remains a declared target without a local v16 runtime test.

Reviewed schema SHA-256: `aa181e72baae4c8fb80fbc09fd7457e2961150146b134b0d81426f955b1c081e`.
