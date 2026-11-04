# Third-party notices and licensing boundary

## Original project material

Copyright (c) 2026 Eugene156. Original project code and documentation are licensed
under the [MIT License](LICENSE). This grant does not relicense third-party code,
data, model weights, container images or trademarks. Preserve any applicable
upstream copyright and license notices when redistributing third-party material.

The approved source-only publication does not bundle third-party runtimes, Python
wheels, model weights, container images or the full retail archive. Dependency
references and n8n node identifiers are not copies of those runtime components.

## Dataset attribution

Chen, D. (2012). *Online Retail II* [Dataset]. UCI Machine Learning Repository.
DOI: [10.24432/C5CG6D](https://doi.org/10.24432/C5CG6D).
[Publisher and dataset](https://archive.ics.uci.edu/dataset/502/online+retail+ii).
License: [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).
Dataset rights remain separate from the project's MIT license. No endorsement by
the creator, UCI or the original retailer is implied.

### Transformations used in this project

- Preserve the original workbook and physical worksheet/source-row identities.
  Map its headers into a canonical SQL schema and parse dates and numeric fields.
- Classify sale, cancellation, adjustment and invalid rows using explicit rules.
  Missing CustomerID does not remove an otherwise valid sale. Identical-valued
  physical rows are not automatically removed.
- For overlapping annual worksheets, use the newer sheet analytically from
  1 December 2010 after checking overlap multiset equality. The underlying rows
  remain preserved; this is analytical selection rather than destructive deduplication.
- Select bounded historical periods and compute deterministic aggregate KPIs and
  reports with SQL NUMERIC arithmetic. Published evidence contains selected
  results, rather than an unmodified copy of the dataset. Money may be formatted
  for display without changing the stored calculation/report binding.

See the [data contract](docs/DATA_CONTRACT.md),
[KPI dictionary](docs/KPI_DICTIONARY.md) and
[original-file profile](docs/G0_DATA_PROFILE.md). These transformations and
project-authored policy explanations are not claims made by the dataset creator.
If further data extracts or adaptations are released, retain the attribution and
license link and identify their modifications.

The separately documented fallback is Chen, D. (2015). *Online Retail* [Dataset].
UCI Machine Learning Repository. DOI:
[10.24432/C5BW33](https://doi.org/10.24432/C5BW33).
[Publisher](https://archive.ics.uci.edu/dataset/352/online-retail),
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
This fallback is not the source of the verified Online Retail II demonstrations.

## Software and models

| Component | Separate license / boundary |
| --- | --- |
| n8n Community components and task-runner launcher | Sustainable Use License; enterprise-only portions are excluded from that grant. The assembled stack is not wholly MIT. |
| PostgreSQL and pgvector | PostgreSQL License |
| Python | Python Software Foundation license; operating-system packages have their own terms |
| FastAPI and Ollama runtime | MIT |
| Starlette and Uvicorn | BSD-3-Clause |
| psycopg and psycopg-binary | LGPLv3; importing the library does not relicense it under MIT |
| qwen3:4b-instruct and all-minilm:22m model packages | Apache-2.0; model weights are not distributed here |

Upstream references: [n8n license](https://github.com/n8n-io/n8n/blob/master/LICENSE.md),
[task-runner launcher](https://github.com/n8n-io/task-runner-launcher/blob/main/LICENSE.md),
[PostgreSQL](https://github.com/postgres/postgres/blob/master/COPYRIGHT),
[pgvector](https://github.com/pgvector/pgvector/blob/master/LICENSE),
[Python](https://docs.python.org/3/license.html),
[FastAPI](https://github.com/fastapi/fastapi/blob/master/LICENSE),
[Ollama](https://github.com/ollama/ollama/blob/main/LICENSE),
[Starlette](https://github.com/encode/starlette/blob/master/LICENSE.md),
[Uvicorn](https://github.com/Kludex/uvicorn/blob/main/LICENSE.md),
[psycopg](https://github.com/psycopg/psycopg/blob/master/LICENSE.txt),
[Qwen package](https://ollama.com/library/qwen3:4b-instruct),
[embedding package](https://ollama.com/library/all-minilm:22m).

The previously inspected API wheel metadata also identified MIT terms for
annotated-types, AnyIO, h11, Pydantic, pydantic-core and typing-inspection;
BSD-3-Clause for Click and idna; and PSF-2.0 for typing-extensions. All 14 inspected
API wheels contained license files. Exact installed terms and upstream notices
remain applicable; this summary is not a complete transitive bill of materials.
CI dependencies are referenced in the [CI requirements](config/ci-requirements.txt)
and are installed separately, not vendored in the repository.

The current use is a personal local portfolio. Free local use does not establish
permission to resell a hosted n8n service. Redistributing runtime bundles, modified
libraries or model weights requires a separate exact-version license review,
including any required license copies, notices and source/relinking obligations.

## Provenance boundary

Workflow exports describe the project's orchestration and reference upstream n8n
nodes; they do not include the n8n implementation. The focused review found no
explicit externally copied-code attribution markers in those exports. This does
not certify every line's authorship. Any externally copied snippet with uncertain
redistribution rights must be flagged and withheld until its origin and permission
are confirmed; MIT must not be assumed to cover it.
