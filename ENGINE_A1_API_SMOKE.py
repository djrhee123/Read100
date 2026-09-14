#!/usr/bin/env python3
import importlib.util,json,os,sys,tempfile,threading,urllib.request,urllib.parse
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
os.environ['READ100_OWNER_PIN']='135790'
os.environ['READ100_OBSERVER_PIN']='246801'
os.environ['READ100_REMOTE_PILOT']='1'
spec=importlib.util.spec_from_file_location('candidate_read_server',ROOT/'server.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
with tempfile.TemporaryDirectory() as td:
    m.DB=Path(td)/'read.db';m.init_db()
    httpd=m.ThreadingHTTPServer(('127.0.0.1',0),m.Handler);port=httpd.server_address[1]
    th=threading.Thread(target=httpd.serve_forever,daemon=True);th.start()
    code=next(c for c,a in m.AGE_LOCK.items() if a==7)
    def req(path,data=None):
        body=None if data is None else json.dumps(data).encode()
        r=urllib.request.Request(f'http://127.0.0.1:{port}{path}',data=body,headers={'Content-Type':'application/json'} if body else {})
        with urllib.request.urlopen(r,timeout=5) as x:
            raw=x.read();return x.status,(json.loads(raw) if raw else {})
    assert req('/api/login',{'code':code})[1]['ok']
    assert req('/api/start',{'code':code,'story_id':1,'age':7})[1]['ok']
    events=[
      {'skill':'under','correct':True,'attempt':1,'event_type':'answer','mission_id':'m1','client_event_id':'a1'},
      {'skill':'word','correct':True,'attempt':1,'event_type':'answer','mission_id':'m2','client_event_id':'a2'},
      {'skill':'seq','correct':False,'attempt':1,'event_type':'answer','mission_id':'m3','client_event_id':'a3'},
      {'skill':'trans','correct':True,'attempt':1,'event_type':'answer','mission_id':'m4','client_event_id':'a4'},
      {'skill':'seq','event_type':'hint_used','hint_level':1,'mission_id':'m3','client_event_id':'h1'},
      {'skill':'seq','event_type':'hint_used','hint_level':2,'mission_id':'m3','client_event_id':'h2'},
      {'skill':'seq','correct':True,'attempt':2,'event_type':'answer','mission_id':'m3','client_event_id':'a5'},
    ]
    for e in events:
        payload={'code':code,'story_id':1,'age':7,'day':1,'device_w':820,'device_h':1180,**e}
        st,res=req('/api/event',payload);assert st==200 and res['ok']
    assert req('/api/complete',{'code':code,'story_id':1,'age':7,'duration_sec':600})[1]['ok']
    st,parent=req('/api/parent/summary?'+urllib.parse.urlencode({'code':code}));assert st==200
    assert parent['summary']['mastery_state']=='supported_mastery',parent['summary']
    assert parent['growth']['blocks'][0]['mastery_state']=='supported_mastery'
    st,human=req('/api/validation/human',{'code':code,'story_id':1,'observer_id':'OBS-A1','human_state':'supported_mastery','observer_pin':'246801','note':'smoke'})
    assert st==200 and human['agreement'] is True and human['false_positive'] is False
    st,val=req('/api/validation/summary?'+urllib.parse.urlencode({'pin':'135790','code':code}));assert st==200 and val['count']==1 and val['agreement_rate']==100.0
    out={'status':'PASS','login':'PASS','event_write':'PASS','mastery_state':parent['summary']['mastery_state'],'growth_block':'PASS','human_validation':'PASS','agreement_rate':val['agreement_rate'],'static_mutation':0}
    print(json.dumps(out,ensure_ascii=False,indent=2));httpd.shutdown();th.join(timeout=2)
