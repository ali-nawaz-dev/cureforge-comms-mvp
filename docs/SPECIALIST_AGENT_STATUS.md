# Specialist Agent Status

All specialist agents are drafting-only in the MVP. Outputs enter the shared HITL approval queue and include the required AI-drafted warning header.

Real portal send paths are hard-disabled with `NotImplementedError`, regardless of approval-token state.

| Agent | Topic | Required reviewer role | Real portal status |
| --- | --- | --- | --- |
| Grant Agent | `specialist_request.grant` | `grants_administrator` | Grants.gov disabled |
| Preprint Agent | `specialist_request.preprint` | `principal_investigator` | arXiv SWORD disabled |
| Journal Agent | `specialist_request.journal` | `principal_investigator` | Editorial Manager disabled |
| Patent Agent | `specialist_request.patent` | `patent_counsel` | USPTO Patent Center disabled |
| DUA Agent | `specialist_request.dua` | `regulatory_advisor` or `institutional_legal` | DUA portal disabled |
| FDA Agent | `specialist_request.fda` | `regulatory_advisor` | FDA ESG disabled |

Portal conformance re-verification is deferred to a later phase with patent counsel and regulatory advisor review.

