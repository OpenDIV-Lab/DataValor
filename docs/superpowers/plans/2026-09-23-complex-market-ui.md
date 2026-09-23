# Complex Market UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing DataValor UI with normalized multi-format inputs, model-specific pricing configuration, multi-product markets, repository-backed analysis, and module-local execution traces.

**Architecture:** Pure Python services own input normalization and pricing/market execution. FastAPI preserves the current envelope and operation route while adding schema and preview endpoints. A new browser module overrides the existing product editor and market renderer, keeping navigation and workflow serialization stable.

**Tech Stack:** Python dataclasses and csv/json standard library, DataValor registries and market algorithms, FastAPI/Pydantic, vanilla JavaScript and CSS.

**Spec:** `docs/superpowers/specs/2026-09-22-complex-market-ui-design.md`

## Global Constraints

- Keep `datavalor.ui-workflow/v1alpha1`, existing node types and API envelope compatible.
- Add no left-navigation entries and no frontend framework or mandatory dependency.
- Every exposed method must call a repository implementation or a clearly marked offline executor.
- Preserve old single-product `product_id` requests.

## Review Focus

- CSV quoted delimiters and inconsistent row widths must produce deterministic records or localized errors.
- Multi-product orders must reject unknown products before mechanism execution.
- Currency conflicts and negative monetary/quantity values must be rejected explicitly.
- Old products without `metadata.input_config` and old workflows without trace fields must still load.
- Empty products, orders and optional analysis inputs must render useful states without JavaScript exceptions.

---

### Task 1: Multi-format input normalization

**Files:**
- Create: `UI/services/input_parsing.py`
- Modify: `UI/server/app.py`
- Test: `tests/test_ui_complex_workbench.py`

**Interfaces:**
- Produces: `parse_input(input_type, content, options) -> InputPreview` and `POST /api/inputs/preview`.
- Consumes: standard JSON/CSV text and key-value payloads.

- [ ] Write failing tests for JSON, JSONL, CSV, TSV, key-value, schema override and malformed rows.
- [ ] Run `pytest -q tests/test_ui_complex_workbench.py -k input` and verify missing module failure.
- [ ] Implement parser, schema inference, normalized records and field errors.
- [ ] Add preview request model and endpoint with the existing envelope.
- [ ] Run focused tests and `ruff check UI/services/input_parsing.py UI/server/app.py tests/test_ui_complex_workbench.py`.

### Task 2: Pricing schemas and attributable quote traces

**Files:**
- Create: `UI/services/pricing_workbench.py`
- Modify: `UI/services/operations.py`
- Modify: `UI/server/app.py`
- Test: `tests/test_ui_complex_workbench.py`

**Interfaces:**
- Produces: `pricing_schema()`, `run_pricing(product, parameters, context)` and schema endpoint data.
- Consumes: existing `QuoteRequest`, `PRICING_MODELS`, model parameters and product rights.

- [ ] Write failing tests asserting all exposed models have concrete fields and quotes include `quote`, `trace`, and normalized parameters.
- [ ] Verify RED with focused pytest.
- [ ] Implement explicit field schemas for all registered workbench pricing models.
- [ ] Move pricing execution from `operations.py` to the service and retain compatibility fields for old callers.
- [ ] Run focused tests, existing UI API tests and Ruff.

### Task 3: Multi-product market execution and repository analysis

**Files:**
- Create: `UI/services/market_workbench.py`
- Modify: `UI/services/operations.py`
- Modify: `UI/server/app.py`
- Test: `tests/test_ui_complex_workbench.py`

**Interfaces:**
- Produces: `market_schema()` and `run_market(products, parameters, context)` with execution trace and diagnostics.
- Consumes: normalized products, bids, asks, mechanism selection, BundleDemandMatcher and market analysis functions.

- [ ] Write failing tests for multi-product AND/XOR bundles, multi-unit auction, market health, unknown products, currencies and negative quantities.
- [ ] Verify RED with focused pytest.
- [ ] Implement order validation, listings, advanced mechanism dispatch, bundle/multi-attribute matching, segmentation, health, anomalies and audit.
- [ ] Extend operation payload with compatible `product_ids` and persist one artifact/run through the existing route.
- [ ] Run focused tests, all API tests and Ruff.

### Task 4: Module-local complex input and market UI

**Files:**
- Create: `UI/workbench-complex.js`
- Create: `UI/workbench-complex.css`
- Modify: `UI/index.html`
- Test: `tests/test_ui_complex_workbench.py`

**Interfaces:**
- Produces: product input tabs, market tabs, dynamic method forms, batch order import, trace and diagnostic views.
- Consumes: `/api/inputs/preview`, `/api/workbench/schemas`, product APIs and operation APIs.

- [ ] Write failing static contract tests for unchanged navigation, input modes, module-local tabs, dynamic schemas and trace rendering.
- [ ] Verify RED with focused pytest.
- [ ] Implement product editor input modes, preview and saved `metadata.input_config`.
- [ ] Implement market scenario/product/order/pricing/mechanism/execution/result tabs and model-specific forms.
- [ ] Add workflow Price/Market node detail tabs without changing exported schema version.
- [ ] Run Node syntax checks, focused tests, Ruff and full Pytest.

### Task 5: End-to-end verification

**Files:**
- Modify: `UI/README.md`
- Test: full repository suite.

**Interfaces:**
- Consumes: all prior services and UI assets.
- Produces: documented root/UI launch and complex workbench use.

- [ ] Document supported input types, scenario flow and online/offline behavior.
- [ ] Run `pytest -q`, `ruff check .`, and Node syntax checks.
- [ ] Start via `python -m UI.run` and direct `uvicorn UI.server.app:app` and verify health/static routes.
