#!/usr/bin/env python3
import os, json, sqlite3, csv, io, time, mimetypes, threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
from pathlib import Path
from collections import defaultdict, deque

# Evidence Learning Engine v1.0 — Read100 v1.5 Reference Adapter
from evidence_learning_engine.adapters.read100_v15 import classify_from_stats as shared_classify_from_stats
from evidence_learning_engine.adapters.read100_v15 import growth_block_from_stats as shared_growth_block_from_stats

ROOT=Path(__file__).resolve().parent
CFG=json.loads((ROOT/'config.json').read_text(encoding='utf-8'))
DB=ROOT/'read100_pilot.db'
HOST=os.environ.get('READ100_HOST','127.0.0.1')
PORT=int(os.environ.get('READ100_PORT','8919'))
OWNER_PIN=os.environ.get('READ100_OWNER_PIN','').strip() or str(CFG.get('owner_pin','')).strip()
OBSERVER_PIN=os.environ.get('READ100_OBSERVER_PIN','').strip()
REMOTE=os.environ.get('READ100_REMOTE_PILOT','0')=='1'
VALID=set(CFG['participant_codes'])
AGE_LOCK={str(k).upper():int(v) for k,v in CFG.get('participant_age_map',{}).items()}
PILOT_STORIES=set(int(x) for x in CFG.get('pilot_story_ids',CFG.get('recommended_pilot_story_ids',[1])))
if REMOTE and (not OWNER_PIN or not OBSERVER_PIN): raise RuntimeError('READ100_OWNER_PIN and READ100_OBSERVER_PIN are required in remote pilot mode')
RATE=defaultdict(deque); LOCK=threading.Lock()
SKILL_GROUPS={
 '내용 이해':['under','important','ending'], '어휘':['word'], '순서·원인':['seq','cause','ce'],
 '마음·근거':['emo','evi'], '추론·중심 생각':['lesson','rc','re','rl'], '설명·새 상황 적용':['trans','speech','writing']}
MASTER_LABELS={'independent_mastery':'혼자 안정적으로 이해해요','supported_mastery':'도움을 받으면 이해해요','fragile_understanding':'맞혔지만 새 상황에서는 아직 불안정해요','needs_relearning':'다시 경험하면 좋아요','insufficient_evidence':'기록을 더 모으는 중이에요'}

def db():
    c=sqlite3.connect(DB,timeout=10); c.row_factory=sqlite3.Row; return c

def ensure_col(c,table,col,decl):
    cols={r[1] for r in c.execute(f'PRAGMA table_info({table})')}
    if col not in cols: c.execute(f'ALTER TABLE {table} ADD COLUMN {col} {decl}')

def init_db():
    with db() as c:
        c.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS participants(code TEXT PRIMARY KEY,age INTEGER,device_group TEXT,created_at REAL NOT NULL,last_seen REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,code TEXT NOT NULL,ts REAL NOT NULL,story_id INTEGER,age INTEGER,event_type TEXT NOT NULL,skill TEXT,correct INTEGER,attempt INTEGER,value TEXT,device_w INTEGER,device_h INTEGER);
        CREATE INDEX IF NOT EXISTS idx_events_code ON events(code);
        CREATE INDEX IF NOT EXISTS idx_events_story ON events(story_id);
        CREATE TABLE IF NOT EXISTS progress(code TEXT NOT NULL,story_id INTEGER NOT NULL,age INTEGER NOT NULL,started_at REAL,completed_at REAL,duration_sec REAL,PRIMARY KEY(code,story_id));
        CREATE TABLE IF NOT EXISTS survey(code TEXT NOT NULL,story_id INTEGER NOT NULL,fun INTEGER,hard INTEGER,parent_help INTEGER,created_at REAL NOT NULL,PRIMARY KEY(code,story_id));
        CREATE TABLE IF NOT EXISTS human_observations(id INTEGER PRIMARY KEY AUTOINCREMENT,code TEXT NOT NULL,story_id INTEGER NOT NULL,observer_id TEXT NOT NULL,human_state TEXT NOT NULL,note TEXT,created_at REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_human_obs ON human_observations(code,story_id);
        """)
        ensure_col(c,'events','day','INTEGER'); ensure_col(c,'events','mission_id','TEXT'); ensure_col(c,'events','hint_level','INTEGER'); ensure_col(c,'events','client_event_id','TEXT'); c.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_events_client_id ON events(code,client_event_id) WHERE client_event_id IS NOT NULL')
        now=time.time()
        for code in VALID:
            locked=AGE_LOCK.get(code)
            dg=('tablet' if locked and locked<=7 else 'smartphone') if locked else None
            c.execute('INSERT OR IGNORE INTO participants(code,age,device_group,created_at,last_seen) VALUES(?,?,?,?,?)',(code,locked,dg,now,now))
            if locked: c.execute('UPDATE participants SET age=?,device_group=? WHERE code=?',(locked,dg,code))

def json_body(h):
    n=int(h.headers.get('Content-Length','0') or 0)
    if n>65536: raise ValueError('too large')
    return json.loads((h.rfile.read(n) if n else b'{}').decode('utf-8'))
def client_ip(h): return h.client_address[0]
def allow_login(ip):
    now=time.time()
    with LOCK:
        q=RATE[ip]
        while q and now-q[0]>60:q.popleft()
        if len(q)>=12:return False
        q.append(now);return True
def ratio(a,b): return a/b if b else None

def core_stats(c,code,story_min=None,story_max=None):
    ew=['code=?']; ea=[code]; pw=['code=?']; pa=[code]
    if story_min is not None: ew.append('story_id>=?'); ea.append(story_min); pw.append('story_id>=?'); pa.append(story_min)
    if story_max is not None: ew.append('story_id<=?'); ea.append(story_max); pw.append('story_id<=?'); pa.append(story_max)
    ewhere=' AND '.join(ew); pwhere=' AND '.join(pw)
    ans=c.execute(f"SELECT SUM(CASE WHEN correct=1 THEN 1 ELSE 0 END),COUNT(*) FROM events WHERE {ewhere} AND event_type='answer' AND attempt=1",ea).fetchone()
    hints=c.execute(f"SELECT COUNT(*) FROM events WHERE {ewhere} AND event_type='hint_used'",ea).fetchone()[0]
    relearn=c.execute(f"SELECT COUNT(*) FROM events WHERE {ewhere} AND event_type='relearn_view'",ea).fetchone()[0]
    rec=c.execute(f"SELECT COUNT(*) FROM events WHERE {ewhere} AND event_type='answer' AND correct=1 AND attempt>1",ea).fetchone()[0]
    tr=c.execute(f"SELECT SUM(CASE WHEN correct=1 THEN 1 ELSE 0 END),COUNT(*) FROM events WHERE {ewhere} AND event_type='answer' AND skill='trans'",ea).fetchone()
    completed=c.execute(f"SELECT COUNT(*) FROM progress WHERE {pwhere} AND completed_at IS NOT NULL",pa).fetchone()[0]
    return {'first_right':ans[0] or 0,'first_total':ans[1] or 0,'hints':hints or 0,'relearn':relearn or 0,'recovered':rec or 0,'transfer_right':tr[0] or 0,'transfer_total':tr[1] or 0,'completed':completed or 0}

def classify_mastery(st):
    return shared_classify_from_stats(st)
def story_evidence(c,code,sid):
    st=core_stats(c,code,sid,sid); state=classify_mastery(st); return {**st,'story_id':sid,'mastery_state':state,'mastery_label':MASTER_LABELS[state]}
def learning_snapshot(c,code):
    p=c.execute('SELECT code,age,device_group,last_seen FROM participants WHERE code=?',(code,)).fetchone()
    if not p:return None
    st=core_stats(c,code); state=classify_mastery(st); times=[]
    for r in c.execute("SELECT value FROM events WHERE code=? AND event_type='response_time'",(code,)):
        try:times.append(max(0,int(float(r[0]))))
        except:pass
    readaloud=c.execute("SELECT COUNT(*) FROM events WHERE code=? AND event_type='read_aloud'",(code,)).fetchone()[0]
    exp=c.execute("SELECT COUNT(*) FROM events WHERE code=? AND event_type='expression'",(code,)).fetchone()[0]
    return {**dict(p),**st,'read_aloud':readaloud,'expression':exp,'avg_response_ms':round(sum(times)/len(times)) if times else None,'mastery_state':state,'mastery_label':MASTER_LABELS[state]}
def skill_summary(c,code):
    out=[]
    for label,skills in SKILL_GROUPS.items():
        marks=','.join('?' for _ in skills); args=[code,*skills]
        row=c.execute(f"SELECT SUM(CASE WHEN correct=1 THEN 1 ELSE 0 END),COUNT(*) FROM events WHERE code=? AND event_type='answer' AND attempt=1 AND skill IN ({marks})",args).fetchone()
        recover=c.execute(f"SELECT COUNT(*) FROM events WHERE code=? AND event_type='answer' AND correct=1 AND attempt>1 AND skill IN ({marks})",args).fetchone()[0]
        hints=c.execute(f"SELECT COUNT(*) FROM events WHERE code=? AND event_type='hint_used' AND skill IN ({marks})",args).fetchone()[0]
        right,total=row[0] or 0,row[1] or 0
        state='아직 기록 없음' if total==0 else '혼자 안정적' if right/total>=.75 and hints<=max(1,round(total*.2)) else '도움 후 회복' if recover>0 else '더 관찰'
        out.append({'label':label,'right':right,'total':total,'recovered':recover,'hints':hints,'state':state})
    return out
def growth_report(c,code):
    blocks=[]
    for a,b,day in [(1,5,20),(6,10,40),(11,15,60),(16,20,80),(21,25,100)]:
        st=core_stats(c,code,a,b); shared=shared_growth_block_from_stats(st); state=shared['mastery_state']
        blocks.append({'checkpoint_day':day,'story_range':[a,b],**st,'mastery_state':state,'mastery_label':MASTER_LABELS[state],
        'first_rate':shared['first_rate'],'transfer_rate':shared['transfer_rate'],'hint_dependency':shared['hint_dependency']})
    avail=[x for x in blocks if x['first_total']]
    delta={'first_rate':None,'transfer_rate':None,'hint_dependency':None}
    if len(avail)>=2:
        base,cur=avail[0],avail[-1]
        for k in delta:
            delta[k]=None if base[k] is None or cur[k] is None else cur[k]-base[k]
    if not avail:narrative='아직 성장 비교에 필요한 기록이 없습니다.'
    elif len(avail)==1:narrative=f"Day {avail[-1]['checkpoint_day']} 구간의 기준 기록을 모으는 중입니다. 다음 Proof 구간부터 변화가 비교됩니다."
    else:
        parts=[]
        if delta['transfer_rate'] is not None:parts.append(f"새 상황 적용 {delta['transfer_rate']:+d}%p")
        if delta['first_rate'] is not None:parts.append(f"첫 시도 {delta['first_rate']:+d}%p")
        if delta['hint_dependency'] is not None:parts.append(f"힌트 의존 {delta['hint_dependency']:+d}%p")
        narrative='기준 구간 대비 '+', '.join(parts)+' 변화가 관찰되었습니다.'
    return {'blocks':blocks,'delta_from_baseline':delta,'narrative':narrative,'latest':avail[-1] if avail else None}
def human_validation(c,code=None):
    wh='WHERE code=?' if code else ''; args=[code] if code else []
    rows=[dict(r) for r in c.execute(f'SELECT id,code,story_id,observer_id,human_state,note,created_at FROM human_observations {wh} ORDER BY id DESC',args)]
    compared=[]
    for r in rows:
        sys=story_evidence(c,r['code'],r['story_id']); agreement=r['human_state']==sys['mastery_state']; fp=sys['mastery_state']=='independent_mastery' and r['human_state'] in ('fragile_understanding','needs_relearning')
        compared.append({**r,'system_state':sys['mastery_state'],'system_label':sys['mastery_label'],'agreement':agreement,'false_positive':fp})
    n=len(compared); agree=sum(x['agreement'] for x in compared); fp=sum(x['false_positive'] for x in compared)
    return {'rows':compared,'count':n,'agreement_rate':round(agree/n*100,1) if n else None,'false_positive_rate':round(fp/n*100,1) if n else None,'gate_false_positive_le_5':fp/n<=.05 if n else None}

def locked_age(code): return AGE_LOCK.get(str(code).upper())
def pilot_story_ok(sid): return int(sid or 0) in PILOT_STORIES
def secrets_compare(a,b):
    import hmac
    return bool(a and b and hmac.compare_digest(a,b))
def observer_ok(data): return (not REMOTE) or secrets_compare(str(data.get('observer_pin','')),OBSERVER_PIN)

class Handler(BaseHTTPRequestHandler):
    server_version='Read100Pilot/1.5'
    def log_message(self,fmt,*args):
        safe_args=list(args)
        if safe_args and isinstance(safe_args[0],str): safe_args[0]=safe_args[0].split('?',1)[0]
        print('[%s] %s'%(self.log_date_time_string(),fmt%tuple(safe_args)))
    def security_headers(self):self.send_header('X-Content-Type-Options','nosniff');self.send_header('X-Frame-Options','DENY');self.send_header('Referrer-Policy','no-referrer');self.send_header('Permissions-Policy','camera=(), geolocation=()')
    def send_json(self,obj,status=200):
        b=json.dumps(obj,ensure_ascii=False).encode();self.send_response(status);self.security_headers();self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
    def send_file(self,path):
        if not path.exists() or not path.is_file():self.send_error(404);return
        data=path.read_bytes();ctype=mimetypes.guess_type(str(path))[0] or 'application/octet-stream';self.send_response(200);self.security_headers();self.send_header('Content-Type',ctype+('; charset=utf-8' if ctype.startswith('text/') or ctype=='application/json' else ''));self.send_header('Cache-Control','no-cache' if ctype.startswith('text/html') else 'public, max-age=3600');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def owner_ok(self,qs):return (CFG.get('local_full_test') and client_ip(self) in ('127.0.0.1','::1')) or (qs.get('pin') or [''])[0]==OWNER_PIN
    def do_GET(self):
        u=urlparse(self.path);p=unquote(u.path);qs=parse_qs(u.query)
        pages={'/':'app.html','/owner.html':'owner.html','/parent.html':'parent.html','/fulltest.html':'fulltest.html','/validation.html':'validation.html','/evidence.html':'evidence.html'}
        if p in pages:return self.send_file(ROOT/'static'/pages[p])
        if p=='/api/health':return self.send_json({'ok':True,'service':'read100','pilot':'A'})
        if p=='/api/version':return self.send_json({'ok':True,'product':'Read100','version':'1.5','build':'AWS-PILOT-A','evidence_loop':'Observe → Recover → Transfer → Prove Growth','pilot':'A','pilot_story_ids':sorted(PILOT_STORIES)})
        if p.startswith('/static/'):
            rel=Path(p[8:]);target=(ROOT/'static'/rel).resolve();root=(ROOT/'static').resolve()
            if root not in target.parents and target!=root:return self.send_error(403)
            return self.send_file(target)
        if p=='/api/profile':
            code=(qs.get('code') or [''])[0]
            if code not in VALID:return self.send_json({'ok':False},403)
            with db() as c:
                r=c.execute('SELECT code,age,device_group,last_seen FROM participants WHERE code=?',(code,)).fetchone();completed=[x[0] for x in c.execute('SELECT story_id FROM progress WHERE code=? AND completed_at IS NOT NULL ORDER BY story_id',(code,))]
            return self.send_json({'ok':True,'profile':dict(r),'completed':completed,'pilot_ids':CFG['recommended_pilot_story_ids']})
        if p=='/api/parent/summary':
            code=(qs.get('code') or [''])[0].strip().upper()
            if code not in VALID:return self.send_json({'ok':False},403)
            with db() as c:
                snap=learning_snapshot(c,code);skills=skill_summary(c,code);growth=growth_report(c,code);recent=[dict(r) for r in c.execute('SELECT pr.story_id,pr.age,pr.started_at,pr.completed_at,pr.duration_sec,sv.fun,sv.hard,sv.parent_help FROM progress pr LEFT JOIN survey sv ON sv.code=pr.code AND sv.story_id=pr.story_id WHERE pr.code=? ORDER BY COALESCE(pr.completed_at,pr.started_at) DESC LIMIT 10',(code,))]
            return self.send_json({'ok':True,'summary':snap,'skills':skills,'growth':growth,'recent':recent})
        if p=='/api/owner/observations':
            if not self.owner_ok(qs):return self.send_json({'ok':False},403)
            code=(qs.get('code') or [''])[0].strip().upper()
            if code not in VALID:return self.send_json({'ok':False},400)
            with db() as c:
                snap=learning_snapshot(c,code);skills=skill_summary(c,code);growth=growth_report(c,code);events=[dict(r) for r in c.execute('SELECT ts,story_id,age,day,mission_id,event_type,skill,correct,attempt,hint_level,value,device_w,device_h FROM events WHERE code=? ORDER BY id DESC LIMIT 300',(code,))]
            return self.send_json({'ok':True,'summary':snap,'skills':skills,'growth':growth,'events':events,'stories':[]})
        if p=='/api/owner/summary':
            if not self.owner_ok(qs):return self.send_json({'ok':False},403)
            with db() as c:
                rows=[]
                for r in map(dict,c.execute('SELECT code,age,device_group,last_seen FROM participants ORDER BY code')):
                    st=learning_snapshot(c,r['code']);ev=c.execute('SELECT COUNT(*) FROM events WHERE code=?',(r['code'],)).fetchone()[0];started=c.execute('SELECT COUNT(*) FROM progress WHERE code=?',(r['code'],)).fetchone()[0];rows.append({**r,**({k:v for k,v in st.items() if k not in r} if st else {}),'event_count':ev,'started_count':started,'retry':0,'fun_avg':None,'help_avg':None})
            return self.send_json({'ok':True,'rows':rows,'pilot_ids':CFG['recommended_pilot_story_ids']})
        if p=='/api/owner/surveys':
            if not self.owner_ok(qs):return self.send_json({'ok':False},403)
            with db() as c:rows=[dict(r) for r in c.execute('SELECT s.code,s.story_id,p.age,p.device_group,s.fun,s.hard,s.parent_help,s.created_at FROM survey s LEFT JOIN participants p ON p.code=s.code ORDER BY s.created_at DESC')]
            return self.send_json({'ok':True,'rows':rows})
        if p=='/api/owner/surveys.csv':
            if not self.owner_ok(qs):return self.send_json({'ok':False},403)
            out=io.StringIO();w=csv.writer(out);w.writerow(['code','age','device_group','story_id','fun','hard','parent_help','created_at'])
            with db() as c:
                for r in c.execute('SELECT s.code,p.age,p.device_group,s.story_id,s.fun,s.hard,s.parent_help,s.created_at FROM survey s LEFT JOIN participants p ON p.code=s.code ORDER BY s.created_at DESC'):w.writerow(list(r))
            b=out.getvalue().encode('utf-8-sig');self.send_response(200);self.security_headers();self.send_header('Content-Type','text/csv; charset=utf-8');self.send_header('Content-Disposition','attachment; filename="read100_v15_surveys.csv"');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b);return
        if p=='/api/validation/summary':
            if not self.owner_ok(qs):return self.send_json({'ok':False},403)
            code=(qs.get('code') or [''])[0].strip().upper() or None
            with db() as c:v=human_validation(c,code)
            return self.send_json({'ok':True,**v})
        if p=='/api/owner/export.csv':
            if not self.owner_ok(qs):return self.send_json({'ok':False},403)
            out=io.StringIO();w=csv.writer(out);w.writerow(['code','age','story_id','day','mission_id','event_type','skill','correct','attempt','hint_level','value','device_w','device_h','ts'])
            with db() as c:
                for r in c.execute('SELECT code,age,story_id,day,mission_id,event_type,skill,correct,attempt,hint_level,value,device_w,device_h,ts FROM events ORDER BY id'):w.writerow(list(r))
            b=out.getvalue().encode('utf-8-sig');self.send_response(200);self.security_headers();self.send_header('Content-Type','text/csv; charset=utf-8');self.send_header('Content-Disposition','attachment; filename="read100_v15_evidence.csv"');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b);return
        self.send_error(404)
    def do_POST(self):
        p=urlparse(self.path).path
        try:data=json_body(self)
        except:return self.send_json({'ok':False,'error':'bad_request'},400)
        if p=='/api/login':
            if not allow_login(client_ip(self)):return self.send_json({'ok':False},429)
            code=str(data.get('code','')).strip().upper()
            if code not in VALID:return self.send_json({'ok':False},403)
            with db() as c:c.execute('UPDATE participants SET last_seen=? WHERE code=?',(time.time(),code))
            return self.send_json({'ok':True,'code':code})
        code=str(data.get('code','')).strip().upper()
        if code not in VALID:return self.send_json({'ok':False},403)
        if p=='/api/profile':
            requested=int(data.get('age',0) or 0); age=locked_age(code) or requested
            if age not in (5,6,7,8,9):return self.send_json({'ok':False},400)
            if locked_age(code) and requested not in (0,age):return self.send_json({'ok':False,'error':'age_locked','age':age},409)
            dg='tablet' if age<=7 else 'smartphone'
            with db() as c:c.execute('UPDATE participants SET age=?,device_group=?,last_seen=? WHERE code=?',(age,dg,time.time(),code))
            return self.send_json({'ok':True,'age':age,'device_group':dg,'age_locked':bool(locked_age(code))})
        if p=='/api/event':
            sid=int(data.get('story_id',0) or 0)
            if not pilot_story_ok(sid):return self.send_json({'ok':False,'error':'story_not_in_pilot'},403)
            age=locked_age(code) or int(data.get('age',0) or 0);day=int(data.get('day',0) or 0) or None;event=str(data.get('event_type',''))[:40];skill=str(data.get('skill',''))[:40];mission=str(data.get('mission_id',''))[:80] or None
            correct=data.get('correct');correct=None if correct is None else int(bool(correct));attempt=data.get('attempt');attempt=None if attempt is None else max(0,min(int(attempt),99));hint=data.get('hint_level');hint=None if hint is None else max(0,min(int(hint),9));value=str(data.get('value',''))[:300];dw=int(data.get('device_w',0) or 0);dh=int(data.get('device_h',0) or 0);ceid=str(data.get('client_event_id','')).strip()[:120] or None
            with db() as c:
                try:c.execute('INSERT INTO events(code,ts,story_id,age,day,mission_id,event_type,skill,correct,attempt,hint_level,value,device_w,device_h,client_event_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(code,time.time(),sid,age,day,mission,event,skill,correct,attempt,hint,value,dw,dh,ceid));duplicate=False
                except sqlite3.IntegrityError:
                    if ceid: duplicate=True
                    else: raise
                c.execute('UPDATE participants SET last_seen=? WHERE code=?',(time.time(),code))
            return self.send_json({'ok':True,'duplicate':duplicate})
        if p=='/api/start':
            sid=int(data.get('story_id',0))
            if not pilot_story_ok(sid):return self.send_json({'ok':False,'error':'story_not_in_pilot'},403)
            age=locked_age(code) or int(data.get('age',0))
            with db() as c:c.execute('INSERT INTO progress(code,story_id,age,started_at) VALUES(?,?,?,?) ON CONFLICT(code,story_id) DO UPDATE SET age=excluded.age,started_at=COALESCE(progress.started_at,excluded.started_at)',(code,sid,age,time.time()))
            return self.send_json({'ok':True})
        if p=='/api/complete':
            sid=int(data.get('story_id',0))
            if not pilot_story_ok(sid):return self.send_json({'ok':False,'error':'story_not_in_pilot'},403)
            age=locked_age(code) or int(data.get('age',0));dur=float(data.get('duration_sec',0) or 0)
            with db() as c:c.execute('INSERT INTO progress(code,story_id,age,started_at,completed_at,duration_sec) VALUES(?,?,?,?,?,?) ON CONFLICT(code,story_id) DO UPDATE SET age=excluded.age,completed_at=excluded.completed_at,duration_sec=excluded.duration_sec',(code,sid,age,time.time()-max(dur,0),time.time(),max(dur,0)))
            return self.send_json({'ok':True})
        if p=='/api/survey':
            sid=int(data.get('story_id',0))
            if not pilot_story_ok(sid):return self.send_json({'ok':False,'error':'story_not_in_pilot'},403)
            fun=int(data.get('fun',0));hard=int(data.get('hard',0));helpv=int(data.get('parent_help',-1))
            if fun not in (1,2,3) or hard not in (1,2,3) or helpv not in (-1,0,1):return self.send_json({'ok':False},400)
            with db() as c:c.execute('INSERT INTO survey(code,story_id,fun,hard,parent_help,created_at) VALUES(?,?,?,?,?,?) ON CONFLICT(code,story_id) DO UPDATE SET fun=excluded.fun,hard=excluded.hard,parent_help=excluded.parent_help,created_at=excluded.created_at',(code,sid,fun,hard,None if helpv==-1 else helpv,time.time()))
            return self.send_json({'ok':True})
        if p=='/api/parent/help':
            sid=int(data.get('story_id',0));helpv=int(data.get('parent_help',-1))
            if not pilot_story_ok(sid) or helpv not in (0,1):return self.send_json({'ok':False},400)
            with db() as c:c.execute('INSERT INTO survey(code,story_id,parent_help,created_at) VALUES(?,?,?,?) ON CONFLICT(code,story_id) DO UPDATE SET parent_help=excluded.parent_help,created_at=excluded.created_at',(code,sid,helpv,time.time()))
            return self.send_json({'ok':True})
        if p=='/api/validation/human':
            sid=int(data.get('story_id',0))
            if not pilot_story_ok(sid):return self.send_json({'ok':False,'error':'story_not_in_pilot'},403)
            if not observer_ok(data):return self.send_json({'ok':False,'error':'observer_auth'},403)
            observer=str(data.get('observer_id','')).strip()[:40];state=str(data.get('human_state','')).strip();note=str(data.get('note',''))[:500]
            if not observer or not 1<=sid<=25 or state not in MASTER_LABELS or state=='insufficient_evidence':return self.send_json({'ok':False},400)
            with db() as c:c.execute('INSERT INTO human_observations(code,story_id,observer_id,human_state,note,created_at) VALUES(?,?,?,?,?,?)',(code,sid,observer,state,note,time.time()));sys=story_evidence(c,code,sid)
            return self.send_json({'ok':True,'system':sys,'agreement':state==sys['mastery_state'],'false_positive':sys['mastery_state']=='independent_mastery' and state in ('fragile_understanding','needs_relearning')})
        self.send_error(404)

if __name__=='__main__':
    init_db();print(f'Read100 v1.5 Evidence Loop: http://{HOST}:{PORT}');print(f'Full Test: http://{HOST}:{PORT}/fulltest.html');ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
