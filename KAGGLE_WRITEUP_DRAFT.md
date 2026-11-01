# Kaggle Writeup — Query Slayer: Ordinal-Folded JSONB Expansion

**Competition:** Python & PostgreSQL Data Pipeline Optimization Challenge  
**Track:** Query Slayer ($100 first-place prize)  
**Author account:** mhamedaskoure  
**Public repository:** https://github.com/zongsm-cmyk/kaggle_postgre_challenge  
**Exact solution commit:** `ef2352abae0afdfb3e1042f3b1e67eb9ab86f727`  
**Status:** READY FOR REVIEW. **NOT SUBMITTED ON KAGGLE.**

## Challenge and bottleneck

The original DB Manager expands heterogeneous `raw_data.raw` JSONB values into six relational tables over an SSH-controlled PostgreSQL backend. The sixth SQL recipe (`SQL files/06_table2.sql`) contains fourteen position-specific `VALUES` tuples, each repeating expressions to extract type, quantity, weight and gap fields. The original program must preserve origin validation, target dependencies, version registration, backup/dump semantics and exact output correctness.

## What was changed

The proposed solution changes **one SQL file only**: `SQL files/06_table2.sql`. It replaces repeated, fully expanded per-position JSONB expressions with fourteen typed numeric ordinals; the query derives the appropriate source JSONB keys from the ordinal. All pre-existing joins, output columns, casts and filters remain. No benchmark generator, seed, source dataset, version/backup handling or main application code was altered. It uses the original permitted SQL function set and introduces no materialized staging dataset.

## Locally measured performance

PostgreSQL 18.6, disposable offline Docker lab, official unmodified generator with fixed seed. **These are direct SQL timings, not the official `MEASURED PROCESSING TOTAL`.**

| Official generator source rows | Original sixth SQL | Optimized sixth SQL | Improvement | Verified identical destination rows |
|---:|---:|---:|---:|---:|
| 100,000 | 5.252 s | 3.537 s | **32.66%** | 232,386 |
| 250,000 | 13.787 s | 8.625 s | **37.44%** | 580,772 |
| 1,000,000 | 37.130 s | 20.785 s | **44.02%** | 2,321,522 |

For 100k and 1M, original and optimized SQL were each timed in both run orders, with medians reported to mitigate query-cache/order effects. For 250k, only one timing per candidate was recorded. Both directions of `EXCEPT ALL` over every output value showed **zero missing and zero extra rows** at each tested size. Query-level comparisons used explicit transactions, followed by ROLLBACK.

The machine-readable one-million-row cross-over receipt is at `benchmarks/million_row_balanced_two_orders.json` in this repository, and the full methods and limitations are in `BENCHMARK_EVIDENCE.md`.

## Functional correctness and integrity

The original unmodified Python unit test suite passes **6/6**. A separate integration test used the original `PostgresAdminService._prepare_cross_table_expansion` and `_build_managed_dml_sql` to execute all six prepared, dependency-ordered SQL recipes in a single transaction on 250,000 source records. All six managed row counters matched the PostgreSQL result counts. The transaction was rolled back with baseline tables unchanged.

An injected database exception after the third managed step raised an expected error, and the test verified that all shadow schema and counter changes were rolled back. A separate loopback Paramiko SSH harness exercised the application’s real `connect` and `run_remote_command` methods: query stdin streaming and propagation of an actual PostgreSQL error both passed. The test scripts and receipts are in `benchmarks/`.

## Recovery strategy and resource use

For database errors in the scenarios tested, the existing single-transaction expansion model preserves atomicity: PostgreSQL discards all uncommitted changes. We intentionally did not replace the original version and dump/recovery system with an untested alternative.

The tested solution adds **no new persistent intermediate tables or external preprocessing services**. The largest offline PostgreSQL container displayed approximately 2.5 GiB of memory use during active query execution, but this is not a judge-collected peak RAM metric and should not be compared directly with other submissions.

## Limitations and reproducibility

1. The full Windows UI → real remote Linux SSH daemon → metadata/version registration → dump creation pipeline has **not** been benchmarked end to end; only the unchanged SQL and bounded transport/integration components have been tested.
2. Durable checkpoint/resume after OS restart or network interruption is **not implemented** by this single-file optimization. Error rollback was tested, but resuming partial work after a committed checkpoint was not.
3. These experiments stop at **1 million** deterministic rows; the target of up to 300 million rows is untested.
4. The ranking and awarded cash depend entirely on the organizer’s reproduced results and rules, not the local timing numbers.
5. The exact code commit cited above is immutable; later commits adding documentation or test evidence do not alter the submitted SQL contents at that commit.

**Reproduce:** clone the public repository at the exact commit, install the original requirements, run its original unit tests, generate the official dataset with the unmodified `generate_database.py` and fixed seed, execute all six original SQL recipes in dependency order (substituting the committed `06_table2.sql`), and compare full target multisets against the original query. Use `benchmarks/managed_shadow_transaction.py` only in the explicitly named disposable local lab.

---

**Submission note:** This document is a prepared Kaggle Writeup draft. It has **not** been entered or officially submitted, and must not be represented as a scored competition entry until Kaggle confirms registration and the Writeup submission receipt.
