# SQL Optimization Evidence — Kaggle PostgreSQL Challenge

**Status: verified local engineering evidence; not a Kaggle submission or official judge score.**

Public competition: https://www.kaggle.com/competitions/python-postgre-sql-data-pipeline-optimization-challenge

Upstream: https://github.com/igorsiecz/kaggle_postgre_challenge

Source modification: `SQL files/06_table2.sql` only. Baseline upstream commit: `5dfde9d967425982229b92d6ffe98efcd74612e9`. Local tested topic commit: `22c704c3e745c1f73eaa616bc91af2b91aed8e11`. GitHub source update commit: `4facd1ab54095afdd8efab1f09718cf493bd793c`. The GitHub content was compared byte-for-byte with the local tested working-tree file.

## Bottleneck and solution

The original table2 expansion constructed fourteen sets of JSONB path extraction expressions in a `CROSS JOIN LATERAL (VALUES ...)` relation. The optimized query iterates over fourteen fixed typed ordinal values and computes the JSONB field names from each ordinal. It retains original output columns, typed conversions, `WHERE` predicates, relational joins, six-table dependency order, and the DB Manager's source, validation and version-management code.

## Measured direct PostgreSQL timings

The sponsor's original deterministic `generate_database.py` populated PostgreSQL 18.6, with fixed seed `4918304907611952177`, inside an isolated Docker lab without published ports.

| Source records | Original table2 | Modified table2 | Local speed-up | Exact output |
|---:|---:|---:|---:|---|
| 100,000 | 5,251.523 ms | 3,536.626 ms | 32.655% | 232,386 identical rows |
| 250,000 | 13,787.181 ms | 8,625.084 ms | 37.441% | 580,772 identical rows |

100k timings are medians from two balanced run orders; 250k figures are one run each. Correctness was checked using bidirectional `EXCEPT ALL` over all target values, including duplicates, with **zero missing rows and zero extra rows** at each size. Tests were performed inside explicit transactions, and all candidate modifications were rolled back. No production container or external network service was changed.

The original test suite passed **6/6 tests**, without changing test cases or the benchmark generator.

Additionally, a 250k-row shadow-schema integration test invoked the application's real `_prepare_cross_table_expansion` and `_build_managed_dml_sql` methods, ran all six prepared insert statements inside one database transaction, verified all six row counters, collected six server-timing measurements, and rolled back the complete test. Target counts: `table3=4`, `table4=26`, `table1=250000`, `table5=250000`, `table6=250000`, `table2=580772`. This shadow test took about **13.57 seconds** end to end, but did **not** traverse the application GUI/SSH or version registration.

A deliberate SQL exception after an in-transaction operation yielded an error and preserved all **580,772** reference target rows; this confirms transaction rollback in that isolated case. It does **not** validate durable checkpoint-and-resume.

## Reproduction and limits

Run the existing repository tests with the dependencies in `requirements.txt`. Generate the official sample with the unmodified `generate_database.py`, select `raw_schema=group001`, apply all six recipes in the mandated order, and compare the original and modified table2 query on the same environment. The project has been validated on 100k and 250k rows but **not** on 300-million-row workloads.

**Not yet verified:** The judge's primary metric, `MEASURED PROCESSING TOTAL`, includes SSH, application preflight, database metadata, version registration and dump/version recovery. Our numbers measure only one SQL query and do not predict the final competition score. Full end-to-end checks and authenticated Kaggle registration still need to pass. The competition has a $100 first-place prize; no income is earned by publishing this branch.
