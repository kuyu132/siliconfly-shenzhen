# Data license

`connectome.json`, `neurons.bin`, `synapses.bin` (and the legacy
`brain_points.json` / `circuit.json`) are derived from the publicly released
FlyWire connectome data products (FAFB v783) and processed by `../etl.py`.

Sources:

- **Neuron annotations, coordinates, cell types and neurotransmitters** —
  `classification.csv.gz`, `coordinates.csv.gz`,
  `consolidated_cell_types.csv.gz`, `neurons.csv.gz`, downloaded from
  [FlyWire Codex](https://codex.flywire.ai)
  (`https://storage.googleapis.com/flywire-data/codex/data/fafb/783`).
- **Connectivity** — `2025_Connectivity_783.parquet` from
  [eonsystemspbc/fly-brain](https://github.com/eonsystemspbc/fly-brain), an
  aggregation of FlyWire's `proofread_connections_783` release
  ([Zenodo 10676866](https://doi.org/10.5281/zenodo.10676866)) into
  15,091,983 (pre, post) synapse-count pairs with no threshold. It carries
  the same FlyWire CC BY-NC 4.0 terms as the Codex dumps.

FlyWire data is licensed under
[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)
(Attribution-NonCommercial 4.0 International). These derived files are
likewise released under CC BY-NC 4.0: they may be shared and adapted with
attribution, for non-commercial use.

Please cite:

- Dorkenwald, S. et al. *Neuronal wiring diagram of an adult brain.*
  Nature 634, 124–138 (2024). https://doi.org/10.1038/s41586-024-07558-y
- Schlegel, P. et al. *Whole-brain annotation and multi-connectome cell typing
  of Drosophila.* Nature 634, 139–152 (2024).
  https://doi.org/10.1038/s41586-024-07686-5

FlyWire is a project of Princeton University and collaborators; see
https://flywire.ai for full terms and community guidelines.
