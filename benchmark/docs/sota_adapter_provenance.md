# SOTA Shapley adapter provenance

Frozen on 2026-09-29. Benchmark adapters are optional integrations; none of
these packages becomes a mandatory DataValor dependency.

| Family | Frozen source | License | Native call unit | Adapter status |
|---|---|---|---|---|
| pyDVL VRDS/Owen/Group Testing | `pyDVL==0.10.0`, tag commit `c85d2afc8f210d1e9e55c9ee20d0d5181b1c1e26` | LGPL-3.0 | utility/model fit requested by pyDVL | Model-backed adapter remains optional because pyDVL does not support the base Python 3.13 environment |
| SVARM, Stratified SVARM, Stratified SVARM+ | authors' repository commit `c4e30395b14b8bf9a8687d839d5b406f825bb23d` | MIT | one coalition-value access; the authors treat the empty coalition as known/free | Maintained `shapiq` is preferred for SVARM; the authors' experiment repository can be supplied explicitly for the two paper-exact stratified variants |
| shapiq estimators | `shapiq==1.7.0`, tag commit `827d695946ca0a36c92f41426cb8253a906f0699` | MIT | each row passed to the vectorized game callback | Direct adapters for SVARM, stratified sampling, Owen, KernelSHAP, Unbiased KernelSHAP, and LeverageSHAP |
| ASSS-A / ASSS-B | PACMMOD 4(3), DOI `10.1145/3802016`, published 2026-05-18 | CC-BY-4.0 article | marginal samples with an adaptive number of strata | No maintained source artifact was located and the publisher exposes no retrievable algorithm supplement; structured unavailable rather than an unverifiable approximation |

## Accounting and deviations

- `budget` is the maximum number of coalition rows delivered to an external
  game callback. The adapter reports the observed row count rather than assuming
  full-budget consumption; border/exact tricks often consume less.
- Inputs are immutable `CoalitionGameTable` objects. External packages receive
  a vectorized lookup callable, so model training and cache construction remain
  outside the estimator adapter and are charged separately by the common ledger.
- The AAAI-2024 code assumes `v(empty)=0`; the adapter subtracts the table's
  empty-coalition value. Shapley values are invariant to this constant shift.
- Official-repository code is loaded only from an explicit path and is never
  copied into DataValor. Its global NumPy/Python RNG state is saved and restored.
- ASSS stays unavailable until paper pseudocode or author code can be audited
  line by line. An unrelated adaptive Neyman sampler is not labelled ASSS.
