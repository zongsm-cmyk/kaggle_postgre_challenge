"""Complete PostgresAdminService.execute_cross_table_expansion call test in disposable Kaggle DB.
Actual SQL manifest, destination locking, all 6 managed inserts, COMMIT, telemetry.
Preflight metadata/version/function/SSH methods are STUBBED; NOT full judged workflow.
The SQL wrapper goes through genuine PostgreSQL binary in isolated network-none container.
A second run injects a real SQL error before COMMIT and verifies complete rollback.
No production database access, no destructive commands, no external network.
"""
import json,os,pathlib,re,subprocess,sys,time,types
R=pathlib.Path(r'C:\Users\askgs\Downloads\KAGGLE_POSTGRES_PRIZE_RECON_20261101')
sys.path.insert(0,str(R))
from services.postgres_service import PostgresAdminService
CONTAINER='kaggle-pg-20261101-isolated'
DATABASE='kaggle_e2e_lab'
SOURCE_SCHEMA='kaggle_full_source'
SOURCE_TABLE=SOURCE_SCHEMA+'.raw_data'
DESTS=['table3','table4','table1','table5','table6','table2']
FILES=['01_table3.sql','02_table4.sql','03_table1.sql','04_table5.sql','05_table6.sql','06_table2.sql']
VERSIONS=('kaggle_full_method_success','kaggle_full_method_failure')
def psql(sql,expected_error=False,timeout=180):
 c=['docker','exec','-i',CONTAINER,'psql','-X','-q','-w','-v','ON_ERROR_STOP=1','-U',
    'kagglebench','-d',DATABASE,'-t','-A']
 p=subprocess.run(c,input=sql,text=True,capture_output=True,timeout=timeout)
 if expected_error:
  assert p.returncode!=0 and 'division by zero' in p.stderr, (p.returncode,p.stderr[-500:])
 elif p.returncode!=0:raise RuntimeError(p.stderr[-1200:])
 return p.stdout.strip()
def scalar(sql):return psql(sql).splitlines()[-1].strip()
def assert_preflight():
 assert scalar('SELECT count(*) FROM public.raw_data;')=='250000'
 assert scalar("SELECT to_regnamespace('"+SOURCE_SCHEMA+"') IS NULL;")=='t'
 assert all(scalar("SELECT to_regnamespace('"+x+"') IS NULL;")=='t' for x in VERSIONS)
 assert scalar("SELECT to_regclass('public.pgdm_table_row_counts') IS NULL;")=='t'
def initialize_sandbox():
 assert_preflight()
 setup=["BEGIN;","CREATE SCHEMA "+SOURCE_SCHEMA+";","CREATE TABLE "+SOURCE_TABLE+" (LIKE public.raw_data INCLUDING ALL);",
        "INSERT INTO "+SOURCE_TABLE+" SELECT * FROM public.raw_data ORDER BY raw_hash LIMIT 1000;",
        "CREATE TABLE public.pgdm_table_row_counts (schema_name text NOT NULL, table_name text NOT NULL,"
        "row_count bigint NOT NULL, updated_at timestamptz NOT NULL,"
        "PRIMARY KEY(schema_name,table_name));"]
 for schema in VERSIONS:
  setup.append("CREATE SCHEMA "+schema+";")
  for t in DESTS:
   setup.extend(["CREATE TABLE "+schema+"."+t+" (LIKE public."+t+" INCLUDING ALL);",
    "INSERT INTO public.pgdm_table_row_counts VALUES ('"+schema+"','"+t+"',0,clock_timestamp());"])
 setup.append("COMMIT;")
 psql('\n'.join(setup))
 assert scalar('SELECT count(*) FROM '+SOURCE_TABLE+';')=='1000'
 for schema in VERSIONS:
  assert all(scalar('SELECT count(*) FROM '+schema+'.'+t+';')=='0' for t in DESTS)
 print('SCRATCH_READY_1000',flush=True)
def make_service(inject_failure):
 svc=PostgresAdminService()
 svc.sql_username='kagglebench'
 # The following preflight methods are stubbed *only* for isolated integration.
 def fake_table_exists(self,db,name,**kw):
  return scalar("SELECT to_regclass('"+name+"') IS NOT NULL;")=='t'
 def fake_get_columns(self,db,name,**kw):
  return [{'name':'raw_schema','type':'text'},{'name':'raw_hash','type':'text'}]
 def fake_get_versions(self,db,table,groups,**kw):
  return [{'raw_schema':'group001','version_code':'test_reference_not_registered'}]
 def fake_validate_functions(self,db,prepared,**kw):return None
 def fake_ensure_metadata(self,db,**kw):return None
 def fake_count(self,db,table,**kw):return int(scalar('SELECT count(*) FROM '+table+';'))
 def fake_dependencies(self,*args,**kw):return None
 def run_real_sql(self,command,stdin_text=None,**kw):
  assert '-d kaggle_e2e_lab' in command and 'psql -h localhost -U kagglebench' in command
  assert 'BEGIN ISOLATION LEVEL REPEATABLE READ;' in stdin_text
  assert 'pgdm_expansion_timings' in stdin_text
  sql=stdin_text
  if inject_failure:
   needle="INSERT INTO pg_temp.pgdm_expansion_timings VALUES (9000"
   assert sql.count(needle)==1
   sql=sql.replace(needle,"SELECT 1/0;\n"+needle)
   psql(sql,expected_error=True)
   raise RuntimeError('ERROR: division by zero')
  return psql(sql,timeout=180)
 for n,fn in [('table_exists',fake_table_exists),
              ('get_table_column_definitions',fake_get_columns),
              ('get_raw_schema_version_references',fake_get_versions),
              ('_validate_cross_table_expansion_functions',fake_validate_functions),
              ('ensure_data_database_metadata',fake_ensure_metadata),
              ('get_table_row_count',fake_count),
              ('_validate_managed_sql_dependencies',fake_dependencies),
              ('run_remote_command',run_real_sql)]:
  setattr(svc,n,types.MethodType(fn,svc))
 return svc
def make_destinations(schema):
 dest=[]
 for file,t in zip(FILES,DESTS):
  sql=(R/'SQL files'/file).read_text(encoding='utf8')
  sql=re.sub(r'\bpublic\.(table[1-6])\b',lambda m:schema+'.'+m.group(1),sql)
  assert sql.startswith('INSERT INTO '+schema+'.'+t),file
  dest.append({'table_name':schema+'.'+t,'version_title':'Sandbox only','sql':sql})
 return dest
def execute_case(schema,failure):
 svc=make_service(failure)
 callback=[]
 begin=time.perf_counter()
 try:
  result=svc.execute_cross_table_expansion(
    DATABASE,SOURCE_TABLE,['group001'],make_destinations(schema),
    post_commit_callback=lambda:callback.append('committed'))
  assert not failure,'injected failure should have raised'
  assert callback==['committed']
  report=result['timing_report']
  assert report['source_rows']==1000,report.get('source_rows')
  assert len(report['destination_rows'])==6
  assert report['total_rows_inserted']==sum(x['rows'] for x in report['destination_rows'])
  assert result['dependency_manifest']['expected_row_count']==1000
  assert len([x for x in report['items'] if x.get('origin')=='postgresql_backend_wall'])>=6 or len(report['items'])>=6
 except RuntimeError as exc:
  if not failure:raise
  assert 'division by zero' in str(exc),str(exc)
  assert callback==[]
  report=None
 counts={}
 for t in DESTS:
  rows=int(scalar('SELECT count(*) FROM '+schema+'.'+t+';'))
  met=int(scalar("SELECT row_count FROM public.pgdm_table_row_counts WHERE schema_name='"+schema+
    "' AND table_name='"+t+"';"))
  assert rows==met,(schema,t,rows,met)
  if failure:assert rows==0,(schema,t,rows)
  else:assert rows>0,(schema,t,rows)
  counts[t]=rows
 return {'case':'injected_before_commit' if failure else 'full_managed_success',
   'assertion':'PASS','rows':counts,'source_rows':1000,
   'callback_committed':bool(callback),'duration_sec':round(time.perf_counter()-begin,3),
   'real_application_entrypoint':True,'postgres_commit_path':not failure,
   'preflight_stubbed':True,'transport_stubbed':True,
   'timing_report_items':len(report['items']) if report else None,
   'manifest_distinct_hashes':report and result['dependency_manifest'].get('expected_distinct_raw_hash_count')}
def main():
 initialize_sandbox()
 good=execute_case(VERSIONS[0],False)
 print('FULL_ENTRYPOINT_PASS',json.dumps(good),flush=True)
 bad=execute_case(VERSIONS[1],True)
 print('FULL_ENTRYPOINT_INJECTED_FAILURE_PASS',json.dumps(bad),flush=True)
 assert scalar('SELECT count(*) FROM public.table2;')=='580772'
 assert scalar('SELECT count(*) FROM public.raw_data;')=='250000'
 results={'scoped_lab':'kaggle_e2e_lab on isolated network-none container','success':good,'failure':bad,
  'production_tables_unchanged':True,'boundaries':['SSH transport stubbed','selected preflight checks stubbed',
  'no real registered versions or dumps','actual full method SQL batch + manifest + COMMIT/ROLLBACK in PostgreSQL'],
  'not_official_competition_score':True}
 out=R/'full_entrypoint_transaction_cases_1000.json'
 out.write_text(json.dumps(results,indent=2),encoding='utf8')
 print('FULL_ENTRYPOINT_RESULT',json.dumps(results),flush=True)
if __name__=='__main__':main()
