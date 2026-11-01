"""Opt-in SSH transport integration test for sponsor PostgresAdminService.
A Paramiko SSH server listens ONLY on 127.0.0.1 with an ephemeral password,
forwards ONLY a single allowlisted psql command to the disposable
network-none PostgreSQL container. It is NOT a Linux SSH daemon test.
Does not alter the benchmarked source, Git, production assets, or secrets.
"""
import json,os,pathlib,secrets,socket,subprocess,sys,threading,time
import paramiko

REPO=pathlib.Path(r'C:\Users\askgs\Downloads\KAGGLE_POSTGRES_PRIZE_RECON_20261101')
sys.path.insert(0,str(REPO))
from services.postgres_service import PostgresAdminService

CONTAINER='kaggle-pg-20261101-isolated'
DB='kaggle_e2e_lab'
USER='kagglebench'
COMMAND=f'psql -h localhost -U {USER} -d {DB} -X -qAt -v ON_ERROR_STOP=1 -f -'

class LoopbackSSH(paramiko.ServerInterface):
 def __init__(self,password):
  self.password=[REDACTED];self.lock=threading.Lock();self.executions=[]
 def check_auth_password(self,username,password):
  return paramiko.AUTH_SUCCESSFUL if username=='kagglelab' and password==self.password else paramiko.AUTH_FAILED
 def get_allowed_auths(self,username):return 'password'
 def check_channel_request(self,kind,chanid):
  return paramiko.OPEN_SUCCEEDED if kind=='session' else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
 def check_channel_exec_request(self,channel,command):
  cmd=command.decode('utf8') if isinstance(command,bytes) else command
  if not cmd.endswith('; '+COMMAND) or not cmd.startswith('export PGPASSWORD='):
   with self.lock:self.executions.append({'allowed':False,'command':cmd[:80]})
   return False
  def worker():
   try:
    chunks=[]
    while True:
     piece=channel.recv(65536)
     if not piece:break
     chunks.append(piece)
     if sum(map(len,chunks))>250000:raise ValueError('INPUT_TOO_LARGE')
    data=b''.join(chunks)
    if not (b'SELECT' in data) or not data.strip().endswith(b';'):
     raise ValueError('ONLY_TEST_SELECT_ALLOWED')
    # A real PostgreSQL binary in a real Linux container processes the stdin.
    args=['docker','exec','-i',CONTAINER,'psql','-X','-q','-w','-v','ON_ERROR_STOP=1',
          '-U',USER,'-d',DB,'-A','-t']
    result=subprocess.run(args,input=data,timeout=30,capture_output=True)
    if result.stdout:channel.sendall(result.stdout)
    if result.stderr:channel.sendall_stderr(result.stderr)
    channel.send_exit_status(result.returncode)
    with self.lock:self.executions.append({'allowed':True,'bytes':len(data),'exit':result.returncode})
   except Exception as e:
    channel.sendall_stderr((str(e)+'\n').encode())
    channel.send_exit_status(1)
   finally:channel.shutdown_write();channel.close()
  threading.Thread(target=worker,daemon=True).start()
  return True

def safe_query(sql):
 p=subprocess.run(['docker','exec','-i',CONTAINER,'psql','-X','-q','-w','-U',USER,'-d',DB,'-A','-t','-c',sql],
                  capture_output=True,text=True,timeout=10,check=True)
 return p.stdout.strip()

def main():
 assert safe_query('SELECT count(*) FROM public.raw_data;')=='250000'
 assert safe_query('SELECT count(*) FROM public.table2;')=='580772'
 password=secrets.token_hex(16)
 host_key=paramiko.RSAKey.generate(2048)
 server=LoopbackSSH(password)
 listener=socket.socket()
 listener.bind(('127.0.0.1',0));listener.listen(1);port=listener.getsockname()[1]
 ready=threading.Event()
 states=[]
 def serve():
  try:
   ready.set();sock,_=listener.accept()
   trans=paramiko.Transport(sock);trans.add_server_key(host_key)
   trans.start_server(server=server)
   while trans.is_active():time.sleep(.05)
   trans.close()
  except Exception as e:states.append(type(e).__name__+':'+str(e)[:200])
  finally:listener.close()
 th=threading.Thread(target=serve,daemon=True);th.start();ready.wait(2)
 service=PostgresAdminService()
 receipt={'scope':'real application Paramiko SSH transport via temporary loopback server -> genuine Linux PostgreSQL binary',
          'not_real_Linux_SSH_daemon':True,'database':DB,'container':CONTAINER,'bound_address':'127.0.0.1',
          'ephemeral_port_used':True,'errors':[]}
 try:
  service.connect('127.0.0.1',port,'kagglelab',password,5432,USER,'')
  result=service.run_remote_command(COMMAND,stdin_text="SELECT 'SSH_PAYLOAD_OK='||count(*) FROM public.raw_data;\n",timeout_seconds=20)
  assert 'SSH_PAYLOAD_OK=250000' in result,result
  receipt['ssh_command_streaming']='PASS'
  try:
   service.run_remote_command(COMMAND,stdin_text='SELECT 1/0;\n',timeout_seconds=20)
   raise AssertionError('EXPECTED_DB_ERROR_NOT_PROPAGATED')
  except RuntimeError as e:
   assert 'division by zero' in str(e),repr(e)
   receipt['ssh_remote_error_propagation']='PASS'
  assert safe_query('SELECT count(*) FROM public.table2;')=='580772'
  receipt['database_unchanged']=True
  assert len(server.executions)==2 and all(x.get('allowed') for x in server.executions),server.executions
  receipt['allowed_execution_counts']=len(server.executions)
  receipt['result']='PASS'
 finally:
  service.close()
  listener.close()
  th.join(timeout=2)
 p=pathlib.Path(r'C:\Users\askgs\Downloads\KAGGLE_POSTGRES_PRIZE_RECON_20261101\ssh_loopback_protocol_receipt.json')
 p.write_text(json.dumps(receipt,indent=2),encoding='utf8')
 print('SSH_LOOPBACK_INTEGRATION',json.dumps(receipt),flush=True)
if __name__=='__main__':main()
