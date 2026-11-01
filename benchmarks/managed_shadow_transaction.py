#!/usr/bin/env python3
"""Opt-in, rollback-only integration test of PGDM expansion SQL wrappers.

Usage from repository root:
  python benchmarks/managed_shadow_transaction.py --container kaggle-pg-20261101-isolated \
    --database kaggle_e2e_lab --expected-source-rows 250000
  python benchmarks/managed_shadow_transaction.py --container kaggle-pg-20261101-isolated \
    --database kaggle_e2e_lab --expected-source-rows 250000 --inject-failure

Requires the sponsor's existing test dataset in a disposable PostgreSQL database.
Never operate on a production database. No network ports are opened by this script.
This checks original PGDM parser + DML row counters, NOT official end-to-end UI/SSH.
"""
from __future__ import annotations
import argparse
import json
import pathlib
import re
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from services.postgres_service import PostgresAdminService

FILES = (
    ("01_table3.sql", "table3"),
    ("02_table4.sql", "table4"),
    ("03_table1.sql", "table1"),
    ("04_table5.sql", "table5"),
    ("05_table6.sql", "table6"),
    ("06_table2.sql", "table2"),
)
SCHEMA = "kaggle_optin_shadow_250k"


def psql(container: str, database: str, sql: str, timeout=240, expect_failure=False):
    cmd = ["docker", "exec", "-i", container, "psql", "-X", "-q", "-w",
           "-v", "ON_ERROR_STOP=1", "-U", "kagglebench",
           "-d", database, "-A", "-t"]
    run = subprocess.run(cmd, input=sql, text=True, capture_output=True, timeout=timeout)
    if expect_failure:
        if run.returncode == 0 or "division by zero" not in run.stderr:
            raise AssertionError("Expected database exception not observed: " + run.stderr[-600:])
    elif run.returncode:
        raise RuntimeError(run.stderr[-1700:])
    return run.stdout


def build_prepared():
    items = []
    for filename, name in FILES:
        sql = (REPO / "SQL files" / filename).read_text(encoding="utf-8")
        sql = re.sub(r"\bpublic\.(table[1-6])\b",
                     lambda match: SCHEMA + "." + match[1], sql)
        items.append({"table_name": SCHEMA+"."+name,
                      "version_title": "Opt-in local acceptance",
                      "sql": sql})
    result = PostgresAdminService._prepare_cross_table_expansion(
        "public.raw_data", ["group001"], items)
    assert len(result["destinations"]) == 6
    return result


def run_experiment(container, database, expected_source_rows, inject_failure):
    # Fail closed if this is not the explicitly named disposable Kaggle lab.
    if container != "kaggle-pg-20261101-isolated" or database != "kaggle_e2e_lab":
        raise ValueError("Refusing to run outside the preverified disposable Kaggle lab")
    check = psql(container, database,
        "SELECT count(*) FROM public.raw_data WHERE raw_schema='group001';").strip()
    if int(check) != expected_source_rows:
        raise ValueError("Dataset size mismatch: " + check)
    if psql(container, database,
            "SELECT to_regnamespace('"+SCHEMA+"') IS NULL;").strip() != "t":
        raise ValueError("Shadow namespace exists; refusing to modify it")
    if psql(container, database,
            "SELECT to_regclass('public.pgdm_table_row_counts') IS NULL;").strip() != "t":
        raise ValueError("Counter table exists in lab; refusing collision")
    original_table2 = psql(container,database,"SELECT count(*) FROM public.table2;").strip()
    prepared = build_prepared()
    sql = ["\\set ON_ERROR_STOP on",
           "BEGIN;",
           "CREATE SCHEMA "+SCHEMA+";",
           """CREATE TABLE public.pgdm_table_row_counts(
           schema_name text NOT NULL,table_name text NOT NULL,
           row_count bigint NOT NULL,updated_at timestamptz NOT NULL,
           PRIMARY KEY(schema_name,table_name));"""]
    for _, name in FILES:
        sql.append("CREATE TABLE "+SCHEMA+"."+name+
                   " (LIKE public."+name+" INCLUDING ALL);")
        sql.append("INSERT INTO public.pgdm_table_row_counts VALUES ('"+
                   SCHEMA+"','"+name+"',0,clock_timestamp());")
    sql.append("""CREATE TEMP TABLE pgdm_expansion_timings(
        sequence_number integer PRIMARY KEY,stage_key text NOT NULL,
        item_name text NOT NULL,started_at timestamptz NOT NULL,
        finished_at timestamptz,rows_affected bigint,
        destination_name text,statement_index integer
        ) ON COMMIT PRESERVE ROWS;""")
    for i, item in enumerate(prepared["destinations"], 10):
        assert len(item["statements"]) == 1
        name = item["pure_table_name"]
        sql.append(PostgresAdminService._build_managed_dml_sql(
            item["statements"][0],SCHEMA,name,"add",
            timing_sequence=i,timing_stage="execute",
            timing_name="INSERT "+name,timing_destination=SCHEMA+"."+name,
            timing_statement_index=1))
        if inject_failure and i == 12:
            sql.extend(["SELECT 1/0;", "COMMIT;"])
            break
    if not inject_failure:
        sql.append("SELECT 'STEP_COUNT='||count(*) FROM pg_temp.pgdm_expansion_timings;")
        for _, name in FILES:
            sql.append("SELECT 'ROWS_"+name+"='||count(*) FROM "+SCHEMA+"."+name+";")
            sql.append("SELECT 'COUNTER_"+name+
                       "='||row_count FROM public.pgdm_table_row_counts "+
                       "WHERE schema_name='"+SCHEMA+"' AND table_name='"+name+"';")
        sql.extend(["ROLLBACK;","\\echo ROLLBACK_COMPLETE"])
    started = time.perf_counter()
    out = psql(container, database,"\n".join(sql),expect_failure=inject_failure)
    duration=round(time.perf_counter()-started,3)
    counts={}
    if not inject_failure:
        data={k:int(v) for k,v in re.findall(
            r"(STEP_COUNT|ROWS_table\d|COUNTER_table\d)=(\d+)",out)}
        assert data.pop("STEP_COUNT") == 6,data
        for _,name in FILES:
            rows=data.pop("ROWS_"+name)
            counter=data.pop("COUNTER_"+name)
            assert rows==counter and rows>0,(name,rows,counter)
            counts[name]=rows
        assert not data and "ROLLBACK_COMPLETE" in out
    # Both success and expected error must leave no schema or metadata.
    assert psql(container,database,"SELECT to_regnamespace('"+SCHEMA+"') IS NULL;").strip()=="t"
    assert psql(container,database,
                "SELECT to_regclass('public.pgdm_table_row_counts') IS NULL;").strip()=="t"
    assert psql(container,database,"SELECT count(*) FROM public.table2;").strip()==original_table2
    assert psql(container,database,
                "SELECT count(*) FROM public.raw_data WHERE raw_schema='group001';").strip()==str(expected_source_rows)
    return {"outcome":"PASS","mode":"injected_failure" if inject_failure else "managed_six_step",
            "source_rows":expected_source_rows,
            "target_table_counts":counts,
            "elapsed_wall_s":duration,"transaction_rolled_back":True,
            "data_unchanged":True,
            "scope":"PGDM real parser/wrappers in disposable lab; no SSH, UI, or versioning"}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--container",default="kaggle-pg-20261101-isolated")
    parser.add_argument("--database",default="kaggle_e2e_lab")
    parser.add_argument("--expected-source-rows",type=int,default=250000)
    parser.add_argument("--inject-failure",action="store_true")
    args=parser.parse_args()
    result=run_experiment(args.container,args.database,
                          args.expected_source_rows,args.inject_failure)
    print(json.dumps(result),flush=True)


if __name__=="__main__":
    main()
