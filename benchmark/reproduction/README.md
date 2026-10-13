# DataMechBench reference-core reproduction packet

This packet verifies or reruns the frozen 210-row, three-track held-out study,
the 11-method finite-domain incentive audit, six reusable evidence tables and
six SVG diagnostics, the standalone replication-wave and
economic-observable-scope CSVs, the 4,626-run controlled trading-geometry stress study, and the
1,215-run aggregate-compatible economic-type study, the 528-run direct-market
listed-price support study, the 17-card/119-dimension
non-composite mechanism-risk audit. It also binds the post-freeze 408-row Triple Eagle
extension, its 105-row baseline-completion run, and the exact finite-support
randomization audit, plus the 68-row BFM-VM extension and its pinned
paper/source discrepancy audit. It is deliberately
fail-closed: a successful local command proves artifact integrity, but **does
not** prove independent reproduction or deployment readiness.

## Supported CPU environment

- Python 3.12.7;
- the exact packages in `requirements-cpu.lock`;
- Linux x86-64 is the reference platform;
- no GPU is required.

The entrypoint rejects Python below 3.10 before launching any stage; 3.12.7 is
the pinned reference environment rather than a claim that arbitrary Python
versions are equivalent.

From the repository root:

```bash
python3.12 -m venv .venv-kdd
.venv-kdd/bin/python -m pip install -r benchmark/reproduction/requirements-cpu.lock
.venv-kdd/bin/python -m pip install --no-index --no-build-isolation --no-deps . ./benchmark
PYTHONPATH=benchmark/src .venv-kdd/bin/python \
  benchmark/scripts/check_kdd_environment.py \
  --output environment-preflight.json
PYTHONPATH=benchmark/src .venv-kdd/bin/python \
  benchmark/scripts/reproduce_kdd_core.py --verify-only \
  --report reproduction-report.json
```

The preflight uses only the Python standard library and distribution metadata;
it does not import NumPy, SciPy, or scikit-learn. It fails before a long run on
an unsupported Python, malformed lock, missing source tree, missing package, or
version mismatch. A supported runtime other than the pinned Python 3.12.7 or a
non-reference platform is reported explicitly as a warning. The JSON also
states that the runtime is a native Python source library and that no container
or VM image is required.

Expected scientific identity:

- release: `datamechbench-reference-v0.3-code`;
- rows: 210 completed, zero skipped/failed;
- track counts: valuation 72, procurement 66, trading 72;
- scientific digest: `2476e1c41f4b057dcf8f37abce45623db64f8e04e3f42e7a3bb839d4b3adb1a7`;
- artifact and source-tree counts are recorded directly in
  `kdd2027_core_manifest.json`; manuscript sources and venue records are not
  part of this code release.

The scientific digest excludes only the top-level and metric-level runtime
measurements.  It still binds every status, error, method, case, seed,
scientific metric, and metadata value.

`--verify-only` is an archive-integrity check and requires every declared byte
hash to match.  `--run` uses the stricter scientific-reproduction contract for
new outputs: input/protocol/code bytes must still match, while byte differences
in explicitly identified runtime-bearing generated files are reported as
`non_scientific_differences` and accepted only when the scientific digest,
row/status/track counts, and deterministic confirmatory statistics still match.
The report-artifact manifest may also rebind the rerun raw-results byte hash
because runtime fields change; the six CSV tables and six SVG figures remain
byte-bound individually and must still match exactly.

## Native Python-library release

The benchmark is distributed as two installable Python source projects
(`datavalor` and `datamechbench`), not as a container image. The deterministic
archive is only a byte-bound transport for those sources and their evidence;
it is not a separate runtime format. Build the candidate, extract it into a
fresh directory, install the pinned lock and then install `.` and
`./benchmark` with `--no-deps`, as shown above. CI performs the same standalone
Python rerun and therefore checks that no local worktree state is required.
The project code and release-level documentation use the repository's
Apache-2.0 `LICENSE`; `catalog/kdd_public_release.yaml` binds both that identifier
and the exact license-file SHA-256. Third-party datasets and vendored validation
sources retain the separate licences recorded in their source cards and
manifests.

## External implementation cross-checks

The core release contains four independently authored source-path comparisons
covering five headline method IDs. The native-CPU exact-Shapley comparison
executes the unchanged ground-truth enumerator and its three algorithmic
dependencies from the S-SVARM authors' repository at commit
`c4e30395b14b8bf9a8687d839d5b406f825bb23d`:

```bash
PYTHONPATH=benchmark/src:src python \
  benchmark/scripts/run_external_shapley_validation.py --build
PYTHONPATH=benchmark/src:src python \
  benchmark/scripts/run_external_shapley_validation.py --verify
```

Five normalized finite games agree within `1e-12`. A sixth nonzero-empty game
is retained as an expected semantic boundary: the upstream enumerator assumes
`v(empty)=0` and differs by the analytically expected `v(empty)/n`. The record
is an independent reimplementation of exact Shapley, not official Data Shapley
code.

The optional ML comparison executes the
unchanged KNN-Shapley source from the official OpenDataVal repository at commit
`5c2856b95237a07ee4565638060e043f1e410822`. Its source, MIT license, three
fixtures, runner, output vectors, and tolerance are byte-bound. Install the
small optional lock (PyTorch is intentionally not part of the CPU core), then
rebuild and verify the record:

```bash
python -m pip install -r benchmark/reproduction/requirements-external-knn.lock
PYTHONPATH=benchmark/src:src python \
  benchmark/scripts/run_external_knn_validation.py --build
PYTHONPATH=benchmark/src:src python \
  benchmark/scripts/run_external_knn_validation.py --verify
```

The three point-value comparisons have maximum absolute error
`2.781550090258378e-08` against tolerance `1e-7`. This is real external-code
agreement after the declared training-only standardization alignment.

The CPU-core pipeline also rebuilds the author-maintained McAfee comparison at
commit `d1a55eaacb337ecebeaf5f57a67bcd6a9d4411eb` without optional packages:

```bash
PYTHONPATH=benchmark/src:src python \
  benchmark/scripts/run_external_mcafee_validation.py --build
PYTHONPATH=benchmark/src:src python \
  benchmark/scripts/run_external_mcafee_validation.py --verify
```

Five fixtures span candidate-price, reduction, exhausted-side, zero-GFT, and
no-trade branches. Six economic observables agree exactly with the local core
and hand-derived fixture oracles; three additional fallback-only fixtures
cross-check the standalone Trade Reduction core. Every executed upstream dependency is
hash-bound, and the record explicitly discloses one terminal-newline-only
vendoring normalization. Together with exact Shapley, these checks validate
four headline cores in two tracks at this point in the sequence.

The same pinned author repository contributes a fourth external code path: its
generalized SBB external-competition mechanism specialized to a two-category
`[1,1]` recipe. This path remains standard-library/CPU-only:

```bash
PYTHONPATH=benchmark/src:src python \
  benchmark/scripts/run_external_sbba_validation.py --build
PYTHONPATH=benchmark/src:src python \
  benchmark/scripts/run_external_sbba_validation.py --verify
```

Five general-position fixtures agree exactly on nine structural and expected
economic observables. One zero-external-competition tie is retained separately:
the generalized code uses a strict-positive test whereas the 2016 SBBA equality
case retains full trade. Together the four external paths validate five
headline cores in two tracks; they do not validate the other 12 families and
do not count as independent clean-room reproduction of the benchmark.

## Post-freeze Triple Eagle extension

The procurement extension is exploratory and does not alter any frozen
confirmatory contrast. Its runner rebuilds two paper-exact Triple Eagle
variants over 34 cases, completes the 12 previously absent Jalaly--Tardos/ML
method-case cells, removes environment-dependent runtime fields from the
scientific rows, and derives method-level comparisons:

```bash
PYTHONPATH=benchmark/src:src python \
  benchmark/scripts/run_triple_eagle_extension.py --build
PYTHONPATH=benchmark/src:src python \
  benchmark/scripts/run_triple_eagle_extension.py --verify
```

Building twice must reproduce the two raw-result hashes and analysis-manifest
hash exactly. The theorem audit enumerates and exactly weights the randomized
mechanism's two finite branches; the ten-seed panel remains a separate
sensitivity artifact. The procurement code search found no eligible official
author implementation, so this extension is `paper_exact` local evidence and
does not increase the external-code validation count.

## Deterministic public-release candidate

After the core manifest verifies, build and check the DOI-ready local candidate:

```bash
PYTHONPATH=benchmark/src .venv-kdd/bin/python \
  benchmark/scripts/build_kdd_release_candidate.py --build
PYTHONPATH=benchmark/src .venv-kdd/bin/python \
  benchmark/scripts/build_kdd_release_candidate.py --verify
```

The builder packages exactly the hash-bound scientific inputs/source tree plus
an explicit documentation allowlist. It normalizes ordering, timestamps,
ownership and modes. The verifier does not extract the archive and rejects
traversal, absolute/backslash paths, duplicate entries, links/devices, altered
bytes, or metadata drift. It also checks that the sidecar, archived
`RELEASE-METADATA.json`, archived reproduction manifest, and current repository
manifest all carry the same reproduction-manifest SHA-256. A previously valid
candidate therefore becomes stale and fails readiness as soon as any core
binding changes. CI builds it twice and compares the raw archive and sidecar
bytes. The archive is not bound back into the core manifest because that would
create a hash cycle; instead, the candidate binds the core manifest.

After this non-extracting safety check passes, CI unpacks the verified candidate
into a fresh temporary directory and executes the complete `--run` pipeline from
inside that directory. This standalone rerun is an internal package-closure
test: it catches runtime dependencies that exist in the development checkout but
were omitted from the candidate. It still does not count as an independent
clean-room reproduction because the same project workflow and maintainers run
it. In particular, `catalog/qualification.yaml` is both hash-bound by the core
manifest and present in the candidate because the post-freeze Triple Eagle
reporter loads it while rebuilding constraint-qualified tables.

## Full rerun

First ensure that every source file named in
`kdd2027_core_manifest.json` exists and passes `--verify-only`.  Source URLs,
licences, transformations, and limitations are frozen in
`../configs/kdd_heldout_confirmatory.yaml` and
`../docs/heldout_source_cards.md`.  Then run:

```bash
PYTHONPATH=benchmark/src .venv-kdd/bin/python \
  benchmark/scripts/reproduce_kdd_core.py --run \
  --report reproduction-report.json
```

`--run` invokes, in order, the frozen v1 held-out driver, the evaluator-held v2
replication driver and cross-wave report, the finite-domain incentive audit,
the controlled trading-geometry builder, the DaDaDa processed-profile
verifier, the direct listed-price transfer builder, the independent
exact-Shapley, official McAfee, and
generalized-SBB/SBBA cross-checks, the Triple Eagle extension builder, the
deterministic report-artifact builder, the decision-impact builder, and the
mechanism-risk-card builder, then
verifies the complete release. The optional OpenDataVal/PyTorch cross-check is
not rerun by the CPU core. The calibration stage verifies the released anonymous
profiles and source receipt without downloading the raw CSV. It will overwrite
those output/evidence files, so
external operators should run it in a disposable clone, virtual environment, or VM. The 681,554,784-byte
ChileCompra archive is needed only to rebuild the three processed cost files;
the core mechanism rerun consumes the hash-bound processed files and source
receipt.  OpenML ARFFs and nine Elexon payloads are direct runner inputs.
The 38,142,044-byte DaDaDa CSV is needed only to rebuild the anonymous profile;
it is deliberately excluded from the core archive. The transfer rerun consumes
the hash-bound profile and the existing OpenML owner games.

The held-out config also freezes its emitted metric IDs and diagnostic keys.
This result-surface contract prevents metrics introduced by later exploratory
extensions from silently changing the 210-row confirmatory scientific digest.
The new normalized oracle-gain and value-oracle-query metrics therefore remain
available to the Triple Eagle extension without being retroactively injected
into the preregistered held-out rows.

## Independent operator record

Two non-implementers are required. DataMechBench is reproduced as a native
Python source library; no Docker/OCI image, container, or VM image is part of
the benchmark contract. Each operator should:

1. unpack the published source archive (or use its hash-matched source clone)
   only after recording its resolvable HTTPS URL and measuring its SHA-256,
   then create a fresh Python virtual environment;
2. retain the exact command, setup time, exit code, manifest SHA-256, scientific
   digest, and unexpected differences;
3. save the successful native-Python environment preflight, then run the
   reproduction entrypoint with `--operator-record` so the complete preflight,
   public archive identity, command, exit status, manifest hash, digest, and
   tracks are written automatically;
4. use each `--attest-*` flag only when its statement is true; in particular,
   attest independence only if they did not implement the evaluated mechanisms
   or this reproduction code; and
5. submit the generated record for review before it is hash-bound by the
   post-release evidence overlay described below.

Example for an independent operator (replace the operator ID and measured setup
time). The exact lock file, including the Python build backend, is installed
first. The two local Python packages are then installed without pip creating a
second, unpinned build environment:

```bash
python -m venv .venv-datamechbench
. .venv-datamechbench/bin/activate
python -m pip install -r benchmark/reproduction/requirements-cpu.lock
python -m pip install --no-index --no-build-isolation --no-deps . ./benchmark
PYTHONPATH=benchmark/src:src python \
  benchmark/scripts/check_kdd_environment.py \
  --output environment-preflight.json
# Set these from the public release record and the archive bytes you downloaded.
SOURCE_ARCHIVE_URL='https://<public archival host>/<versioned source archive>'
SOURCE_ARCHIVE_SHA256='<sha256sum of the downloaded source archive>'
PYTHONPATH=benchmark/src:src python \
  benchmark/scripts/reproduce_kdd_core.py --run \
  --report reproduction-report.json \
  --operator-record operator-a.json \
  --operator-id operator-a \
  --isolation fresh_venv \
  --setup-minutes 12.5 \
  --source-archive-url "$SOURCE_ARCHIVE_URL" \
  --source-archive-sha256 "$SOURCE_ARCHIVE_SHA256" \
  --environment-preflight environment-preflight.json \
  --attest-independent-of-implementation \
  --attest-no-source-modifications \
  --attest-no-unexpected-differences
```

`--operator-record` is rejected with `--verify-only`; it always requires the
full reproduction pipeline. Its three source/environment arguments are
mandatory: the URL must be HTTPS, the archive hash must match the verified
public-release sidecar, and the embedded preflight must report the exact lock
with every package matched under `native_python_source_library`. A container or
VM image report is rejected even if it claims success. Operator-local absolute
repository and lock paths are normalized to `.` and the repository-relative
lock path before publication, while their scientific lock hash is retained.
The recorded replay command likewise uses `python`, repository-relative paths,
and filenames instead of publishing virtual-environment or home-directory
paths. A successful machine run with any omitted
attestation produces `status=draft`, while a failed pipeline produces
`status=failed`. If a difference is observed, replace the final no-difference
flag with one or more `--unexpected-difference 'description'` arguments. Such a
record remains non-passing until the difference is resolved and a new clean run
is made. An internal maintainer rehearsal must omit the independence flag and
therefore cannot satisfy the gate.

The template has schema 1.1, `status=template`, negative timing/exit
placeholders, an unexecuted preflight, no real public archive identity, and a
false independence declaration, so it cannot satisfy the machine gate as-is.
Operator IDs may be stable pseudonyms; no personal data is required in the
public artifact.

## Post-release evidence overlay

Publication identifiers and independent runs necessarily exist only after the
native-Python archive is frozen. They therefore live in a separate evidence
overlay and are **not** packed into, or hash-bound as inputs of, that immutable
archive. This avoids a circular workflow in which recording the archive hash
would itself change the archive.

After publishing the candidate, and without rebuilding it:

1. copy `post_release_evidence.template.yaml` to
   `benchmark/evidence/post_release/kdd_release_evidence.yaml`;
2. copy `catalog/kdd_public_release.yaml` to the overlay directory; fill only
   real resolvable repository/archive URLs and DOI, the actual archive creators,
   and its ISO publication date; verify that the archive deposit exposes the
   same title, release/version, software resource type, Apache-2.0 license,
   description, and keywords; then retain the final record's measured SHA-256
   in the overlay;
3. import each genuine non-implementer record unchanged and retain each
   measured file SHA-256;
4. record the SHA-256 of the exact published
   `kdd2027_core_manifest.json`; and
5. run `datamechbench kdd-readiness --post-release-evidence
   benchmark/evidence/post_release/kdd_release_evidence.yaml`.

The live overlay is intentionally absent from the release candidate. A missing
overlay keeps the public-release and clean-room gates `not_evidenced`; an
existing malformed, escaping, duplicated, symlinked, or hash-mismatched
overlay fails closed. Do **not** rebuild the archive after importing these
records: the overlay attests to the already published immutable package.

## What remains external

This repository can supply an internal verification report and deterministic
release candidate, but it cannot manufacture publication or independence. Real
public URLs, a DOI, truthful creator/date citation metadata, and two genuine
operator records remain release actions supplied through that overlay. Missing
external citation identity remains `not_evidenced`; placeholder identities or
deposit metadata that conflict with the frozen release fail closed. Until then
the release audit retains `public_release_artifact=not_evidenced` and
`clean_room_reproduction=not_evidenced`. Manuscript and venue readiness are
maintained outside this code repository. The finite audit is
also empirical evidence only: zero gain on the declared grid is neither a DSIC
nor a BIC proof, and a counterexample is evidence about the audited
implementation/domain/estimand rather than an automatic refutation of a source
theorem.
