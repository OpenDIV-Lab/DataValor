# Volume valuation reference-fidelity audit

> Audit date: 2026-10-02  
> Scope: the VSV/RVSV characteristic-function and exact-Shapley core with
> benchmark preprocessing disabled. The registered benchmark methods remain
> documented `paper_variant` implementations.

## Primary sources

- Xinyi Xu, Zhaoxuan Wu, Chuan Sheng Foo, and Bryan Kian Hsiang Low,
  “Validation Free and Replication Robust Volume-based Data Valuation,”
  NeurIPS 2021,
  <https://proceedings.neurips.cc/paper/2021/hash/59a3adea76fadcb6dd9e54c96fc155d1-Abstract.html>.
- Authors' public implementation,
  <https://github.com/ZhaoxuanWu/VolumeBased-DataValuation>, especially
  `dataval/volume.py`: `compute_volumes`, `compute_X_tilde_and_counts`, and
  `compute_robust_volumes`. GitHub's repository metadata reported no detected
  license and the repository exposed no `LICENSE` path when rechecked on
  2026-10-04. It is therefore inspected as a public fidelity source but is not
  vendored or counted as licensed external-code output parity.

The paper and official repository are the fidelity authorities. A replication
robustness result produced by DataMechBench is not used as circular evidence
that the implementation is correct.

## Volume Shapley Value mapping

For a data matrix `X`, the tested characteristic is

```text
Vol(X) = sqrt(det(X^T X) + 1e-8).
```

`volume_shapley` constructs the matrix of each owner coalition and performs
exact subset enumeration of Equation 3. The three-owner golden fixture uses
owner matrices

```text
A = [[1,0],[0,1]]
B = [[1,1],[2,0]]
C = [[0,2],[2,2]].
```

The independently frozen coalition values are:

| Coalition | Volume |
|---|---:|
| A | 1.0000000050 |
| B | 2.0000000025 |
| C | 4.00000000125 |
| AB | 3.316624791863 |
| AC | 5.385164808063 |
| BC | 7.483314774216 |
| ABC | 8.660254038422 |

Equation 3 therefore yields `(A,B,C) = (1.175944689098,
2.725019670924, 4.759289678399)`. The values and Shapley efficiency identity
are pinned by
`test_volume_shapley_matches_equation_three_on_three_owner_fixture` in
`benchmark/tests/test_replication_expansion.py`.

## Robust Volume Shapley Value mapping

For each coalition, `robust_volume_shapley` follows the official helper:

1. translate by the coordinate-wise minimum and assign each point to
   `floor((x-min(X))/omega)`;
2. replace every occupied cube by its mean point;
3. set `N` to the number of occupied cubes and `alpha=1/(10N)`;
4. multiply compressed volume by
   `product_c (1-alpha^(n_c+1))/(1-alpha)`;
5. use the resulting robust volume as the exact-Shapley characteristic.

The golden fixture fixes `omega=1`. Its grand coalition compresses to

```text
[[0.15,0.15], [0.15,1.15], [1.20,0.10],
 [1.20,1.20], [2.15,0.15]]
```

with cube counts `(2,2,1,1,2)`, `N=5`, `alpha=0.02`, base volume
`4.116925431678355`, density multiplier `1.1053802312384255`, and robust
volume `4.5507679856599745`. The independently frozen Shapley vector is
`(0.496614934772, 2.887112278799, 1.167040772089)`.

`test_robust_volume_shapley_matches_official_cube_density_formula` checks the
Shapley vector, grand characteristic, compression count, alpha, base volume,
density multiplier, and efficiency identity. Runtime diagnostics expose the
four intermediate scalar quantities so a release can be audited without
reconstructing cube membership from scores alone.

## Source-to-code table

| Source component | DataMechBench implementation | Evidence |
|---|---|---|
| `sqrt(det(X^T X)+1e-8)` | `_volume` | two-owner hand derivation and three-owner golden vector |
| cube assignment and mean representative | `_robust_volume_details` | fixed five-representative golden fixture |
| `alpha=1/(10N)` and multiplicative density | `_robust_volume_details` | alpha/base/density diagnostics pinned numerically |
| Equation 3 exact Shapley | `_volume_shapley` | three-owner VSV and RVSV score vectors plus efficiency |

## Why parity is verified but provenance remains `paper_variant`

The golden tests establish parity for the characteristic-function and exact
Shapley core. They do not erase benchmark adaptations:

- DataMechBench treats an owner bundle as one Shapley player;
- benchmark runs use declared sklearn standardization/PCA rather than the
  paper's task-specific feature-extraction pipeline;
- the official helper rounds displayed robust volumes to three decimals,
  while the benchmark retains full precision to avoid aggregation ties.

Consequently `volume_shapley` and `robust_volume_shapley` remain
`paper_variant`. Their KDD `verified` status means that the adapted core is
source-tested and its deviations are explicit; it does not mean end-to-end
official-output identity or theorem transfer to the benchmark preprocessing.
