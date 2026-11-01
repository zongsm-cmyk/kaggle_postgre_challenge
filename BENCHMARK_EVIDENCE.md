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


## Shadow-schema failure injection (application-managed DML)

A follow-up isolated test ran the existing application’s actual SQL preflight parser and managed DML wrappers on the original 250,000 sponsor-generated records. The six destination inserts ran within a single PostgreSQL transaction, with real per-table row-counter updates, and the entire transaction was rolled back.

On an additional run, an explicit SQL division-by-zero error was injected after the third managed destination insert. The client observed the database error, disconnected, and verified that **no shadow schema or counter table remained**, that all 250,000 source rows were unchanged, and that the 580,772 original \`table2\` reference rows were untouched.

| Mode | Result | Wall time |
| --- | --- | ---: |
| Six managed inserts + counts + ROLLBACK | PASS, 6/6 targets | 14.003 s |
| Inject database error after third managed insert | PASS, complete transactional rollback | 4.806 s |

The opt-in source test is included at \`benchmarks/managed_shadow_transaction.py\`. It explicitly refuses unknown containers or databases; it is intended only for the temporary lab used in development, never production. This validates application SQL atomicity and observable DB consistency for one error-injection scenario. It **does not implement or prove durable checkpoint/resume after an SSH interruption**, an important remaining part of the challenge’s recovery criterion.


## One-million-row balanced scale experiment

A separate PostgreSQL 18.6 Docker lab (container \`kaggle-pg-1m-private\`, **network mode none**, no published ports) ran the unmodified sponsor generator with its original fixed seed on **1,000,000** source rows. The original first five SQL recipes were then executed in dependency order, producing 4, 27, 1,000,000, 1,000,000, and 1,000,000 rows in their respective destination tables.

The original and optimized sixth queries were run on separate **identically defined temporary tables** (\`LIKE public.table2 INCLUDING ALL\`). Both run orders were measured to control for cache-warming and order effects. Each produced **2,321,522** destination rows. Full bidirectional multiset checks using \`EXCEPT ALL\` found **zero missing and zero extra rows**.

| Execution order | Original SQL | Optimized SQL |
|---|---:|---:|
| Original, then optimized | 38,022.141 ms | 20,974.273 ms |
| Optimized, then original | 36,237.867 ms | 20,594.747 ms |
| **Two-order median** | **37,130.004 ms** | **20,784.510 ms** |

**Measured SQL-only speedup: 44.022%** on this one-million-row workload. All temporary comparison objects were rolled back. The database remains in its initial state with \`public.table2\` empty and the original first five destination tables populated.

The complete, machine-readable cross-over receipt is published as \`benchmarks/million_row_balanced_two_orders.json\`. This **does not** establish a full application/SSH \`MEASURED PROCESSING TOTAL\` improvement; performance and storage behavior on tables with different durability settings or at hundreds of millions of source rows have not been tested.



## Loopback SSH transport integration (bounded)

An additional, isolated integration test used the application’s **real \`PostgresAdminService.connect\` and \`run_remote_command\` methods** against a temporary Paramiko SSH test server bound strictly to **127.0.0.1**. The test used a random, process-local password and ephemeral TCP port, accepted only one exact, allowlisted PostgreSQL CLI command, then forwarded the SQL bytes to a **real PostgreSQL binary inside the dedicated Linux Docker container**.

Verified: SSH password authentication, streamed SQL stdin, correct transfer of the query result (250,000 source rows), propagation of a deliberately raised PostgreSQL division-by-zero error to the application, and unchanged reference table2 rows (580,772). Two allowlisted commands completed; both tests passed.

The test source and original result receipt are at \`benchmarks/ssh_loopback_protocol.py\` and \`benchmarks/ssh_loopback_protocol_receipt.json\`. **This server is an in-process Windows SSH test harness, not an actual Linux \`sshd\` deployment.** It does not reproduce remote SSH latency, actual Linux host security, GUI operations, backup/version registration, interrupted-network resumption, or the judged \`MEASURED PROCESSING TOTAL\`.
