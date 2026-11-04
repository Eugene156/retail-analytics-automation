# Evidence

Templates are empty collection formats, not test results. Store raw local reports in `evidence/private/` and publish only reviewed, sanitised evidence. Record dates, environment, versions, source/model hashes, actual commands, observed results and limitations.

Use `templates/acceptance-run.json` for a test record and `templates/measurement.csv` for the three-way timing protocol. Do not populate observations, timings, reviewer signatures or screenshots with invented values.

Maintain an index linking release -> requirement -> acceptance criterion -> observed evidence. Keep no pass/fail metric badge until the corresponding test has run.
