# fixtures/

These three JSON files are verbatim output of the **public**
`https://shopify.dev/assistant/search` endpoint, captured live with no
authentication required:

| File | Query used |
|------|-----------|
| `search_orders_bulk.json` | `bulkOperationRunQuery orders bulk operation` |
| `search_customer_orders.json` | `Customer numberOfOrders new returning customers query` |
| `search_order_fields.json` | `Order createdAt currentTotalPriceSet fields` |

## PII notice

Any names, email addresses, or phone numbers that appear in these files (e.g.
"John Smith", "johnsmith@example.com", "+16134504532") are **Shopify's own
public documentation placeholder values**.  The email domain `example.com` is
an RFC-2606 reserved example domain — it does not belong to any real person.
These are not real customer records and contain no PII.
