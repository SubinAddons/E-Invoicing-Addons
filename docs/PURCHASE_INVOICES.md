# Addons — Purchase E-Invoicing

This workflow sends ERPNext Purchase Invoices to Ardentax. Ardentax's purchase-creation API creates buyer-issued, self-billed invoices (type 389). Use it only for an agreed self-billing transaction; it is not an upload of an ordinary supplier-issued invoice (type 380).

## Configure
1. Open Addons E Invoice Settings for the purchasing company. Select ArdentaxIT and Sandbox for testing. The business profile must belong to the buyer company.
2. Save and Test Authentication. Configure every item UOM and the applicable tax mappings, as for sales.
3. Leave Queue on Purchase Invoice Submit off for manual queuing, or enable it for automatic queuing of opted-in purchases.
4. Create the Supplier and complete its e-invoicing legal name, email, telephone, TIN, VAT number where applicable, Peppol endpoint and scheme, and registration details. Add its billing Address with country, city, street and emirate code. Use the supplier's actual identifiers.

## Create and send
1. Create a Purchase Invoice, select the company, supplier and supplier billing address.
2. Enter posting/due dates, currency, items, quantities, prices and taxes. Confirm the calculated ERP totals.
3. Enable E-Invoicing and Confirm Self Billing. The type is 389 and the supported transaction profile is standard (00000000).
4. Select the actual payment means code. Code 30 requires Supplier Payment Account Identifier. If setting an actual supply date, select the company shipping address with complete address details.
5. Save, then E-Invoice > Validate / Preview. Correct any mapping errors.
6. Submit the Purchase Invoice. If automatic queuing is off, use E-Invoice > Queue Submission.
7. Open View Submissions or the Addons dashboard to inspect progress. The shared submission record links back to the Purchase Invoice.

## Check completion
Approved submissions populate the read-only UUID and show a green dot on the form and purchase list. Other form statuses show red. Approved Ardentax invoices offer Download Approved PDF. The dashboard includes both sales and purchases. Provider processing is asynchronous; refresh the submission using the available status action, or allow configured background status checks/webhooks to update it.

For Error, Rejected, Unknown or Mismatch, inspect the submission details before retrying. Do not create a replacement just to bypass an uncertain response: first confirm whether Ardentax already received the original.

## Current scope
ArdentaxIT, UAE suppliers, standard self-billed purchases. Purchase returns, other transaction profiles and Fynamics purchase submission are not enabled. Payment methods needing mandate/card details are not mapped. Test the complete flow in Sandbox before production use.

For deployment, update the app, run the site's normal migration and clear cache/restart workers as required by the hosting platform. Both submission and settings schemas and Supplier/Purchase Invoice custom fields must be installed.

## Field review against Ardentax version 20260507
Source: https://docs.ae.ardentaxit.tax/docs/2026-05-07/flow/businesses/purchase-documents/purchase-invoices/create

### Supplier master
| Field | Rule / API mapping |
|---|---|
| Supplier Name | Existing master field → name |
| E-Invoice Legal Name | Required → party_name |
| E-Invoice Email | Required; validated email → email |
| E-Invoice Telephone | Required for supported UAE suppliers → telephone |
| UAE TIN | Required, 10 digits starting with 1 → tin |
| Peppol Endpoint ID / Scheme | Required → endpoint_id / endpoint_scheme_id |
| Tax ID | Existing VAT field; optional. If supplied, 15 digits starting with 1 and ending with 03 → party_tax_scheme |
| Registration ID / Type | Required for endpoint scheme 0235; otherwise supply both together when used → company_id / scheme_agency_id |
| Registration Issuing Authority | Required for TL registration → authority_name |
| Passport Issuing Country | Required for PAS registration; country ISO code → passport_issuing_country_code |
| Supplier Party Identification / Scheme | Optional; scheme requires identifier → party_identification_id / party_identification_scheme_id |
| Supplier Address | Select on invoice. Street, city, country and emirate code required; address line 2 and postal code optional |

Enable E-Invoicing on the Supplier to enforce the master fields on save. The invoice payload validates them again even if the master checkbox is off. UAE supplier TIN and telephone are required regardless of endpoint scheme. Registration ID and type are mandatory for endpoint scheme 0235 (IBR-150-AE). VAT remains optional.

### Purchase Invoice
| Field | Rule / API mapping |
|---|---|
| Invoice name | Existing ERP number → document_number; unique reconciliation identifier |
| Posting Date / Time | Existing fields → issue_date / issue_time (GST conversion) |
| Due Date | Existing field → due_date |
| Currency | Existing field → document_currency_code |
| E-Invoice Type | Read-only 389 |
| Confirm Self Billing | Explicit application confirmation |
| Transaction Profile | Standard 00000000 supported |
| Payment Means Code | Required for standard invoices; only implemented methods offered |
| Supplier Payment Account Identifier / Name | Identifier required for code 30; name optional → payee_financial_account |
| Actual Supply Date | Optional → delivery.actual_delivery_date; complete company shipping address required when used |
| AED per Invoice Currency Unit | Required and positive when currency is not AED → tax_exchange_rate; tax_currency_code set to AED |
| E-Invoice Buyer Reference / Note | Optional → buyer_reference / note |
| Items | Existing item name, description, quantity and net price; mapped UOM and tax category required |
| UUID | Read-only provider result after approval; never entered manually |

The buyer party is taken from the configured Ardentax business profile, not sent as a supplier or manually duplicated in the payload. Totals and system identifiers are response fields. Credit-note discrepancy is hidden on Purchase Invoice because purchase returns are not implemented.

This review covers the supported standard UAE self-billing workflow. FTZ, summary billing, disclosed-agent billing, exports, card/direct-debit details, document attachments, and document-level charges/allowances require additional scenario-specific mapping and are not claimed as supported by this release.
