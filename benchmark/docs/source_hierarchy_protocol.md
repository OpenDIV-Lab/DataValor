# Source hierarchy protocol

DataMechBench treats cases, dates, datasets, source families, and institutions
as different evidence units.  The mapping is frozen in
`catalog/source_hierarchy.yaml`; the audit refuses missing, duplicate, or
track-inconsistent mappings.

`cross_source_supported` requires at least three distinct source families and
three distinct institutions.  Multiple dates from ChileCompra or Elexon count
as temporal transfer only.  The five valuation datasets span distinct dataset
families, but their upstream institutional independence is not established by
OpenML hosting metadata, so the release conservatively reports
`multi_dataset_single_institution`.

This audit controls claim scope rather than mechanism scores.  It does not turn
temporal or dataset counts into a population sample size and does not itself
perform statistical significance testing.

