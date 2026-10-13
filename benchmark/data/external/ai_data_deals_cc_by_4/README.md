# AI Training Data Deals evidence snapshot

This directory contains a minimized derivative of
[`midah/ai-data-deals`](https://huggingface.co/datasets/midah/ai-data-deals),
pinned at revision `f8ce413790627e25138104d5f23d169430bb8aa6`.

- Upstream file: `data/train-00000-of-00001.parquet`
- Upstream SHA-256: `4a5f21b2fe0d5afa1916899a5f19ed21fdb710841d0a5c649093cdcdff0abef7`
- Upstream rows: 78
- Upstream licence: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- Attribution: *AI Training Data Deals*, Hugging Face user `midah`

`snapshot.json` retains deal fields, financial-term wording, source URLs,
counterparties and canonical hashes of the complete upstream rows. It omits the
long `source_text` passages to avoid redistributing unnecessary press excerpts.
The row hash is SHA-256 over compact, key-sorted UTF-8 JSON of the complete
upstream row before minimization.

The snapshot is admitted only for deal-level pricing-mechanism, disclosure and
reported-payment-support evidence. It must not be used as seller reservation
costs, buyer values, mechanism outcomes or an i.i.d. transaction sample. Run:

```bash
PYTHONPATH=benchmark/src python benchmark/scripts/audit_ai_data_deals.py
```

The audit recomputes every price-evidence class from retained wording, rejects
duplicate or unclassified rows, and reports counterparty concentration and
source anomalies without silently cleaning them.
