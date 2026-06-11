---
name: po_compliance_audit
description: Audit completed high-value purchase orders for vendor scope coverage and valid VP approval.
---

# po_compliance_audit

Use this skill for purchase PO compliance audit tasks.

The skill reads `purchase_orders_raw.csv`, `vendors.csv`, `people_roles.csv`,
`approval_evidence.csv`, and the referenced attachment text files. It audits
only completed/closed/paid/accepted high-value POs, checks that all service
items are within the vendor service scope, verifies that a valid VP approved
the whole PO no later than `po_date`, and returns non-compliant PO ids sorted
ascending.

Call `skill_run` with:

```json
{
  "name": "po_compliance_audit",
  "arguments": {
    "source_dir": "<declared PO audit directory>"
  }
}
```

Return the `answer` field verbatim.
