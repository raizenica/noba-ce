#!/usr/bin/env python3
"""Nobara Command Center – Backend v1.0.0 (modular)"""

import http.server
import socketserver
import json
import subprocess
import os
import time
import re
import logging
import glob
import threading
import urllib.request
import urllib.error
import signal
import sys
import ipaddress
import uuid
import hashlib
import secrets
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs

# ── Version from file ─────────────────────────────────────────────────────────
VERSION_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'VERSION')
try:
    with open(VERSION_FILE) as f:
        VERSION = f.read().strip()
except:
    VERSION = '1.0.0'

# ── Config ────────────────────────────────────────────────────────────────────
PORT       = int(os.environ.get('PORT',   8080))
HOST       = os.environ.get('HOST',       '0.0.0.0')
SCRIPT_DIR = os.environ.get('NOBA_SCRIPT_DIR', os.path.expanduser('~/.local/libexec/noba'))
LOG_DIR    = os.path.expanduser('~/.local/share/noba')
PID_FILE   = os.environ.get('PID_FILE',  '/tmp/noba-web-server.pid')
ACTION_LOG = '/tmp/noba-action.log'
AUTH_CONFIG = os.path.expanduser('~/.config/noba-web/auth.conf')
NOBA_YAML   = os.environ.get('NOBA_CONFIG', os.path.expanduser('~/.config/noba/config.yaml'))
USE_HTTPS   = os.environ.get('NOBA_HTTPS', '0') == '1'
CERT_FILE   = os.environ.get('NOBA_CERT', os.path.expanduser('~/.config/noba-web/server.crt'))
KEY_FILE    = os.environ.get('NOBA_KEY',  os.path.expanduser('~/.config/noba-web/server.key'))
NOTIF_FILE  = os.path.join(LOG_DIR, 'notifications.json')
SPEED_FILE  = os.path.join(LOG_DIR, 'speedtest-history.json')

_server_start_time = time.time()

try:    os.makedirs(LOG_DIR, exist_ok=True)
except Exception: pass

log_file = os.path.join(LOG_DIR, 'noba-web-server.log')
try:    logging.basicConfig(filename=log_file, level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
except Exception: logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('noba')

ANSI_RE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
def strip_ansi(s): return ANSI_RE.sub('', s)

SCRIPT_MAP = {
    'backup':        'backup-to-nas.sh',
    'verify':        'backup-verifier.sh',
    'organize':      'organize-downloads.sh',
    'diskcheck':     'disk-sentinel.sh',
    'check_updates': 'noba-update.sh',
}
ALLOWED_ACTIONS = {'start', 'stop', 'restart'}
ADMIN_ONLY_POST = {'/api/run', '/api/service-control'}

# ── Authentication (multi-user) ───────────────────────────────────────────────
_tokens_lock = threading.Lock()
_tokens: dict = {}   # token → {expiry, username, role}

def verify_password(stored: str, password: str) -> bool:
    if not stored:
        return False
    if stored.startswith('pbkdf2:'):
        parts = stored.split(':', 2)
        if len(parts) != 3:
            return False
        _, salt, expected = parts
        dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 200_000)
        return secrets.compare_digest(expected, dk.hex())
    if ':' not in stored:
        return False
    salt, expected = stored.split(':', 1)
    actual = hashlib.sha256((salt + password).encode()).hexdigest()
    return secrets.compare_digest(expected, actual)

def load_users() -> dict:
    if not os.path.exists(AUTH_CONFIG):
        return {}
    users = {}
    try:
        with open(AUTH_CONFIG) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if ':' not in line:
                    continue
                username, rest = line.split(':', 1)
                rparts = rest.rsplit(':', 1)
                if rparts[-1] in ('admin', 'viewer'):
                    pw_hash = rparts[0]
                    role    = rparts[-1]
                else:
                    pw_hash = rest
                    role    = 'admin'
                users[username.strip()] = {'hash': pw_hash, 'role': role}
    except Exception as e:
        logger.warning(f'Could not read auth config: {e}')
    return users

def generate_token(username: str, role: str) -> str:
    token = str(uuid.uuid4())
    with _tokens_lock:
        _tokens[token] = {
            'expiry':   datetime.now() + timedelta(hours=24),
            'username': username,
            'role':     role,
        }
    return token

def get_token_info(token: str) -> dict | None:
    with _tokens_lock:
        info = _tokens.get(token)
        if info and info['expiry'] > datetime.now():
            return info
        if token in _tokens:
            del _tokens[token]
    return None

def revoke_token(token: str) -> None:
    with _tokens_lock:
        _tokens.pop(token, None)

def authenticate_request(headers, query=None) -> dict | None:
    auth = headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        info = get_token_info(auth[7:])
        if info:
            return info
    if query and 'token' in query:
        info = get_token_info(query['token'][0])
        if info:
            return info
    return None

def _token_cleanup_loop():
    while not _shutdown_flag.is_set():
        _shutdown_flag.wait(300)
        now = datetime.now()
        with _tokens_lock:
            expired = [t for t, v in list(_tokens.items()) if v['expiry'] <= now]
            for t in expired:
                del _tokens[t]
        if expired:
            logger.info(f'Token cleanup: {len(expired)} expired')

# ── Login rate limiter ─────────────────────────────────────────────────────────
class LoginRateLimiter:
    def __init__(self, max_attempts=5, window_s=60, lockout_s=30):
        self._lock     = threading.Lock()
        self._attempts: dict = {}
        self._lockouts: dict = {}
        self.max_attempts = max_attempts
        self.window_s     = window_s
        self.lockout_s    = lockout_s
    def is_locked(self, ip: str) -> bool:
        with self._lock:
            exp = self._lockouts.get(ip)
            if exp and datetime.now() < exp: return True
            self._lockouts.pop(ip, None)
            return False
    def record_failure(self, ip: str) -> bool:
        now = datetime.now(); cutoff = now - timedelta(seconds=self.window_s)
        with self._lock:
            attempts = [t for t in self._attempts.get(ip, []) if t > cutoff]
            attempts.append(now); self._attempts[ip] = attempts
            if len(attempts) >= self.max_attempts:
                self._lockouts[ip] = now + timedelta(seconds=self.lockout_s)
                self._attempts.pop(ip, None)
                logger.warning(f'Login lockout: {ip}')
                return True
        return False
    def reset(self, ip: str) -> None:
        with self._lock:
            self._attempts.pop(ip, None); self._lockouts.pop(ip, None)

_rate_limiter = LoginRateLimiter()

# ── NotificationStore ─────────────────────────────────────────────────────────
class NotificationStore:
    def __init__(self, persist_file: str, maxlen: int = 100):
        self._lock     = threading.Lock()
        self._items    = deque(maxlen=maxlen)
        self._next_id  = 1
        self._persist  = persist_file
        self._load()

    def _load(self):
        if not os.path.exists(self._persist):
            return
        try:
            with open(self._persist) as f:
                items = json.load(f)
            for item in items[-self._items.maxlen:]:
                self._items.append(item)
                self._next_id = max(self._next_id, item.get('id', 0) + 1)
        except Exception as e:
            logger.warning(f'NotificationStore load error: {e}')

    def _save(self):
        try:
            with open(self._persist, 'w') as f:
                json.dump(list(self._items), f)
        except Exception:
            pass

    def add_alerts(self, alerts: list):
        if not alerts:
            return
        now = datetime.now()
        with self._lock:
            recent_msgs = {
                item['msg'] for item in self._items
                if (now - datetime.fromisoformat(item['ts'])).total_seconds() < 300
            }
            added = False
            for alert in alerts:
                if alert['msg'] not in recent_msgs:
                    self._items.append({
                        'id':    self._next_id,
                        'ts':    now.strftime('%H:%M:%S'),
                        'level': alert['level'],
                        'msg':   alert['msg'],
                    })
                    recent_msgs.add(alert['msg'])
                    self._next_id += 1
                    added = True
            if added:
                self._save()

    def get_all(self, limit: int = 100) -> list:
        with self._lock:
            return list(self._items)[-limit:]

# ── SpeedtestHistory ──────────────────────────────────────────────────────────
class SpeedtestHistory:
    def __init__(self, persist_file: str, maxlen: int = 20):
        self._lock    = threading.Lock()
        self._items   = deque(maxlen=maxlen)
        self._persist = persist_file
        self._load()

    def _load(self):
        if not os.path.exists(self._persist):
            return
        try:
            with open(self._persist) as f:
                for item in json.load(f)[-self._items.maxlen:]:
                    self._items.append(item)
        except Exception as e:
            logger.warning(f'SpeedtestHistory load error: {e}')

    def _save(self):
        try:
            with open(self._persist, 'w') as f:
                json.dump(list(self._items), f)
        except Exception:
            pass

    def add(self, download: float, upload: float, ping: float):
        with self._lock:
            self._items.append({
                'ts':       datetime.now().strftime('%m/%d %H:%M'),
                'download': round(download, 1),
                'upload':   round(upload, 1),
                'ping':     round(ping, 1),
            })
            self._save()

    def get_all(self) -> list:
        with self._lock:
            return list(self._items)

    @staticmethod
    def parse_output(text: str):
        ping = download = upload = None
        for line in text.splitlines():
            m = re.search(r'([\d.]+)', line)
            if not m: continue
            val = float(m.group(1))
            if   'Ping'     in line: ping     = val
            elif 'Download' in line: download = val
            elif 'Upload'   in line: upload   = val
        return download, upload, ping

# ── YAML settings ─────────────────────────────────────────────────────────────
def read_yaml_settings():
    default = {
        'piholeUrl': '', 'piholeToken': '',
        'monitoredServices': 'backup-to-nas.service, organize-downloads.service, sshd, podman, syncthing.service',
        'radarIps': '192.168.100.1, 1.1.1.1, 8.8.8.8',
        'bookmarksStr': ''
    }
    if not os.path.exists(NOBA_YAML):
        return default
    try:
        r = subprocess.run(['yq', 'eval', '-o=json', '.web', NOBA_YAML], capture_output=True, text=True, timeout=2)
        if r.returncode == 0 and r.stdout.strip():
            web = json.loads(r.stdout)
            for k in default:
                if k in web: default[k] = web[k]
    except Exception as e:
        logger.warning(f'read_yaml_settings: {e}')
    return default

def write_yaml_settings(settings: dict) -> bool:
    try:
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
            tmp.write('web:\n')
            for k, v in settings.items():
                if isinstance(v, str) and any(c in v for c in '\n:#'):
                    v = json.dumps(v)
                tmp.write(f'  {k}: {v}\n')
            tmp_path = tmp.name
        if os.path.exists(NOBA_YAML):
            r = subprocess.run(['yq', 'eval-all', 'select(fileIndex==0) * select(fileIndex==1)', NOBA_YAML, tmp_path],
                               capture_output=True, text=True, timeout=2)
            if r.returncode == 0:
                with open(NOBA_YAML, 'w') as f: f.write(r.stdout)
            else:
                raise RuntimeError(f'yq merge failed: {r.stderr}')
        else:
            os.makedirs(os.path.dirname(NOBA_YAML), exist_ok=True)
            with open(tmp_path) as src, open(NOBA_YAML, 'w') as dst: dst.write(src.read())
        os.unlink(tmp_path)
        return True
    except Exception as e:
        logger.exception(f'write_yaml_settings: {e}')
        return False

# ── Validation ────────────────────────────────────────────────────────────────
def validate_service_name(n): return bool(re.match(r'^[a-zA-Z0-9_.@-]+$', n))
def validate_ip(ip):
    try: ipaddress.ip_address(ip); return True
    except ValueError: return False

# ── TTL cache ─────────────────────────────────────────────────────────────────
class TTLCache:
    def __init__(self): self._s={}; self._l=threading.Lock()
    def get(self,k,ttl=30):
        with self._l:
            e=self._s.get(k)
            if e and (time.time()-e['t'])<ttl: return e['v']
        return None
    def set(self,k,v):
        with self._l: self._s[k]={'v':v,'t':time.time()}

_cache = TTLCache()

# ── Global state ──────────────────────────────────────────────────────────────
_state_lock  = threading.Lock()
_cpu_history = deque(maxlen=20)
_cpu_prev    = None
_net_prev    = None
_net_prev_t  = None
_shutdown_flag = threading.Event()

# ── Signal handler ────────────────────────────────────────────────────────────
def sigterm_handler(signum, frame):
    logger.info('SIGTERM received, shutting down…')
    _shutdown_flag.set()
    threading.Thread(target=lambda: server.shutdown(), daemon=True).start()
signal.signal(signal.SIGTERM, sigterm_handler)

# ── Helpers ───────────────────────────────────────────────────────────────────
def run(cmd, timeout=3, cache_key=None, cache_ttl=30, ignore_rc=False):
    if cache_key:
        hit = _cache.get(cache_key, cache_ttl)
        if hit is not None: return hit
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = r.stdout.strip() if (r.returncode == 0 or ignore_rc) else ''
        if cache_key and out: _cache.set(cache_key, out)
        return out
    except Exception as e:
        logger.debug(f'run {cmd}: {e}'); return ''

def human_bps(bps):
    for u in ('B/s','KB/s','MB/s','GB/s'):
        if bps<1024: return f'{bps:.1f} {u}'
        bps/=1024
    return f'{bps:.1f} TB/s'

# ── Stats collectors ──────────────────────────────────────────────────────────
def get_cpu_percent():
    global _cpu_prev
    with _state_lock:
        try:
            with open('/proc/stat') as f: fields=list(map(int,f.readline().split()[1:]))
            idle=fields[3]+fields[4]; total=sum(fields)
            if _cpu_prev is None: _cpu_prev=(total,idle); return 0.0
            dt=total-_cpu_prev[0]; di=idle-_cpu_prev[1]; _cpu_prev=(total,idle)
            pct=round(100.0*(1.0-di/dt) if dt>0 else 0.0,1)
            _cpu_history.append(pct); return pct
        except: return 0.0

def get_net_io():
    global _net_prev, _net_prev_t
    with _state_lock:
        try:
            with open('/proc/net/dev') as f: lines=f.readlines()
            rx=tx=0
            for line in lines[2:]:
                p=line.split()
                if len(p)>9 and not p[0].startswith('lo'): rx+=int(p[1]); tx+=int(p[9])
            now=time.time()
            if _net_prev is None: _net_prev=(rx,tx); _net_prev_t=now; return 0.0,0.0
            dt=now-_net_prev_t
            if dt<0.05: return 0.0,0.0
            rx_bps=max(0.0,(rx-_net_prev[0])/dt); tx_bps=max(0.0,(tx-_net_prev[1])/dt)
            _net_prev=(rx,tx); _net_prev_t=now; return rx_bps,tx_bps
        except: return 0.0,0.0

def ping_host(ip):
    ip=ip.strip()
    if not validate_ip(ip): return ip,False,0
    try:
        t0=time.time()
        r=subprocess.run(['ping','-c','1','-W','1',ip],capture_output=True,timeout=2.5)
        return ip,r.returncode==0,round((time.time()-t0)*1000)
    except: return ip,False,0

def get_service_status(svc):
    svc=svc.strip()
    if not validate_service_name(svc): return 'invalid',False
    for scope,is_user in ((['--user'],True),([],False)):
        cmd=['systemctl']+scope+['show','-p','ActiveState,LoadState',svc]
        out=run(cmd,timeout=2)
        d=dict(l.split('=',1) for l in out.splitlines() if '=' in l)
        if d.get('LoadState') not in (None,'','not-found'):
            state=d.get('ActiveState','unknown')
            if state=='inactive' and svc.endswith('.service'):
                tn=svc.replace('.service','.timer')
                t=run(['systemctl']+scope+['show','-p','ActiveState',tn],timeout=1)
                if 'ActiveState=active' in t: return 'timer-active',is_user
            return state,is_user
    return 'not-found',False

def get_battery():
    bats=glob.glob('/sys/class/power_supply/BAT*')
    if not bats: return{'percent':100,'status':'Desktop','desktop':True,'timeRemaining':''}
    try:
        pct=int(open(f'{bats[0]}/capacity').read().strip())
        stat=open(f'{bats[0]}/status').read().strip()
        time_rem=''
        try:
            cur=int(open(f'{bats[0]}/current_now').read().strip())
            if cur>0:
                if stat=='Discharging': charge=int(open(f'{bats[0]}/charge_now').read().strip()); hrs=charge/cur
                else:
                    cfull=int(open(f'{bats[0]}/charge_full').read().strip())
                    charge=int(open(f'{bats[0]}/charge_now').read().strip())
                    hrs=(cfull-charge)/cur
                time_rem=f'{int(hrs)}h {int((hrs%1)*60)}m'
                if stat!='Discharging': time_rem+=' to full'
        except: pass
        return{'percent':pct,'status':stat,'desktop':False,'timeRemaining':time_rem}
    except: return{'percent':0,'status':'Error','desktop':False,'timeRemaining':''}

def get_containers():
    for cmd in (['podman','ps','-a','--format','json'],['docker','ps','-a','--format','{{json .}}']):
        out=run(cmd,timeout=4,cache_key=' '.join(cmd),cache_ttl=10)
        if not out: continue
        try:
            items=json.loads(out) if out.lstrip().startswith('[') else [json.loads(l) for l in out.splitlines() if l.strip()]
            res=[]
            for c in items[:16]:
                name=c.get('Names',c.get('Name','?'))
                if isinstance(name,list): name=name[0] if name else '?'
                image=c.get('Image',c.get('Repository','?')).split('/')[-1][:32]
                state=(c.get('State',c.get('Status','?')) or '?').lower().split()[0]
                res.append({'name':name,'image':image,'state':state,'status':c.get('Status',state)})
            return res
        except: continue
    return []

def get_pihole(url, token):
    if not url: return None
    base=url if url.startswith('http') else 'http://'+url
    base=base.rstrip('/').replace('/admin','')
    def _get(ep,h=None):
        hdrs={'User-Agent':f'noba-web/{VERSION}','Accept':'application/json'}
        if h: hdrs.update(h)
        req=urllib.request.Request(base+ep,headers=hdrs)
        with urllib.request.urlopen(req,timeout=3) as r: return json.loads(r.read().decode())
    try:
        auth={'sid':token} if token else {}
        d=_get('/api/stats/summary',auth)
        return{'queries':d.get('queries',{}).get('total',0),'blocked':d.get('ads',{}).get('blocked',0),
               'percent':round(d.get('ads',{}).get('percentage',0.0),1),'status':d.get('gravity',{}).get('status','unknown'),
               'domains':f"{d.get('gravity',{}).get('domains_being_blocked',0):,}"}
    except: pass
    try:
        ep='/admin/api.php?summaryRaw'+(f'&auth={token}' if token else '')
        d=_get(ep)
        return{'queries':d.get('dns_queries_today',0),'blocked':d.get('ads_blocked_today',0),
               'percent':round(d.get('ads_percentage_today',0),1),'status':d.get('status','enabled'),
               'domains':f"{d.get('domains_being_blocked',0):,}"}
    except: return None

def collect_stats(qs):
    stats={'timestamp':datetime.now().strftime('%H:%M:%S')}
    try:
        with open('/etc/os-release') as f:
            for line in f:
                if line.startswith('PRETTY_NAME='): stats['osName']=line.split('=',1)[1].strip().strip('"')
    except: stats['osName']='Linux'
    stats['kernel']    = run(['uname','-r'],cache_key='uname-r',cache_ttl=3600)
    stats['hostname']  = run(['hostname'],cache_key='hostname',cache_ttl=3600)
    stats['defaultIp'] = run(['bash','-c',"ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \\K[\\d.]+'"],timeout=1)
    try:
        uptime_s=float(open('/proc/uptime').read().split()[0])
        d,rem=divmod(int(uptime_s),86400); h,rem=divmod(rem,3600); m=rem//60
        stats['uptime']=(f'{d}d ' if d else '')+f'{h}h {m}m'
        stats['loadavg']=' '.join(open('/proc/loadavg').read().split()[:3])
        ml=open('/proc/meminfo').readlines()
        mm={l.split(':')[0]:int(l.split()[1]) for l in ml if ':' in l}
        tot=mm.get('MemTotal',0)//1024; avail=mm.get('MemAvailable',0)//1024; used=tot-avail
        stats['memory']=f'{used} MiB / {tot} MiB'; stats['memPercent']=round(100*used/tot) if tot>0 else 0
    except: stats.setdefault('uptime','--'); stats.setdefault('loadavg','--'); stats.setdefault('memPercent',0)

    stats['cpuPercent']=get_cpu_percent()
    with _state_lock: stats['cpuHistory']=list(_cpu_history)
    rx_bps,tx_bps=get_net_io()
    stats['netRx']=human_bps(rx_bps); stats['netTx']=human_bps(tx_bps)

    s=run(['sensors'],timeout=2,cache_key='sensors',cache_ttl=5)
    m=re.search(r'(?:Tctl|Package id \d+|Core 0|temp1).*?\+?(\d+\.?\d*)[°℃]',s)
    stats['cpuTemp']=f'{int(float(m.group(1)))}°C' if m else 'N/A'
    gpu_t=run(['nvidia-smi','--query-gpu=temperature.gpu','--format=csv,noheader'],timeout=2,cache_key='nvidia-temp',cache_ttl=5)
    if not gpu_t:
        raw=run(['bash','-c','cat /sys/class/drm/card*/device/hwmon/hwmon*/temp1_input 2>/dev/null | head -1'],timeout=1)
        gpu_t=f'{int(raw)//1000}°C' if raw else 'N/A'
    else: gpu_t=f'{gpu_t}°C'
    stats['gpuTemp']=gpu_t; stats['battery']=get_battery()
    stats['hwCpu']=run(['bash','-c',"lscpu | grep 'Model name' | head -1 | cut -d: -f2 | xargs"],cache_key='lscpu',cache_ttl=3600)
    raw_gpu=run(['bash','-c',"lspci | grep -i 'vga\\|3d' | cut -d: -f3"],cache_key='lspci',cache_ttl=3600)
    stats['hwGpu']=raw_gpu.replace('\n','<br>') if raw_gpu else 'Unknown GPU'

    disks=[]
    for line in run(['df','-BM'],cache_key='df',cache_ttl=10).splitlines()[1:]:
        p=line.split()
        if len(p)>=6 and p[0].startswith('/dev/'):
            mnt=p[5]
            if any(mnt.startswith(x) for x in ('/var/lib/snapd','/boot','/run','/snap')): continue
            try:
                pct=int(p[4].replace('%','')); bc='danger' if pct>=90 else 'warning' if pct>=75 else 'success'
                disks.append({'mount':mnt,'percent':pct,'barClass':bc,'size':p[1].replace('M',' MiB'),'used':p[2].replace('M',' MiB')})
            except: pass
    stats['disks']=disks

    zfs_out=run(['zpool','list','-H','-o','name,health'],timeout=3,cache_key='zpool',cache_ttl=15)
    pools=[{'name':l.split('\t')[0].strip(),'health':l.split('\t')[1].strip()} for l in zfs_out.splitlines() if '\t' in l]
    stats['zfs']={'pools':pools}

    cpu_ps=run(['ps','ax','--format','comm,%cpu','--sort','-%cpu'],timeout=2)
    mem_ps=run(['ps','ax','--format','comm,%mem','--sort','-%mem'],timeout=2)
    def parse_ps(out):
        res=[]
        for line in out.splitlines()[1:6]:
            p=line.strip().rsplit(None,1)
            if len(p)==2 and p[1] not in ('%CPU','%MEM'): res.append({'name':p[0][:16],'val':p[1]+'%'})
        return res
    stats['topCpu']=parse_ps(cpu_ps); stats['topMem']=parse_ps(mem_ps)

    svc_list=[s.strip() for s in qs.get('services',[''])[0].split(',') if s.strip()]
    ip_list =[ip.strip() for ip in qs.get('radar',  [''])[0].split(',') if ip.strip()]
    ph_url  =qs.get('pihole',   [''])[0]
    ph_tok  =qs.get('piholetok',[''])[0]

    with ThreadPoolExecutor(max_workers=max(4,len(svc_list)+len(ip_list)+3)) as ex:
        svc_futs ={ex.submit(get_service_status,s):s  for s in svc_list}
        ping_futs={ex.submit(ping_host,ip):ip          for ip in ip_list}
        ph_fut   =ex.submit(get_pihole,ph_url,ph_tok) if ph_url else None
        ct_fut   =ex.submit(get_containers)

        services=[]
        for fut,svc in svc_futs.items():
            try: status,is_user=fut.result(timeout=4)
            except: status,is_user='error',False
            services.append({'name':svc,'status':status,'is_user':is_user})
        stats['services']=services

        radar=[]
        for fut,ip in ping_futs.items():
            try: ip_r,up,ms=fut.result(timeout=4); radar.append({'ip':ip_r,'status':'Up' if up else 'Down','ms':ms if up else 0})
            except: radar.append({'ip':ip,'status':'Down','ms':0})
        stats['radar']=radar

        try: stats['pihole']=ph_fut.result(timeout=4) if ph_fut else None
        except: stats['pihole']=None
        try: stats['containers']=ct_fut.result(timeout=5)
        except: stats['containers']=[]

    alerts=[]
    cpu=stats.get('cpuPercent',0)
    if   cpu>90: alerts.append({'level':'danger', 'msg':f'CPU critical: {cpu}%'})
    elif cpu>75: alerts.append({'level':'warning','msg':f'CPU high: {cpu}%'})
    ct=stats.get('cpuTemp','N/A')
    if ct!='N/A':
        t=int(ct.replace('°C',''))
        if   t>85: alerts.append({'level':'danger', 'msg':f'CPU temp critical: {t}°C'})
        elif t>70: alerts.append({'level':'warning','msg':f'CPU temp elevated: {t}°C'})
    for disk in stats.get('disks',[]):
        p=disk.get('percent',0)
        if   p>=90: alerts.append({'level':'danger', 'msg':f"Disk {disk['mount']} at {p}%"})
        elif p>=80: alerts.append({'level':'warning','msg':f"Disk {disk['mount']} at {p}%"})
    for svc in stats.get('services',[]):
        if svc.get('status')=='failed': alerts.append({'level':'danger','msg':f"Service failed: {svc['name']}"})
    stats['alerts']=alerts
    return stats

# ── BackgroundCollector ───────────────────────────────────────────────────────
class BackgroundCollector:
    def __init__(self, interval=5):
        self._lock=threading.Lock(); self._latest={}; self._qs={}; self._interval=interval
    def update_qs(self,qs):
        with self._lock: self._qs=dict(qs)
    def get(self):
        with self._lock: return dict(self._latest)
    def start(self):
        threading.Thread(target=self._loop,daemon=True,name='stats-collector').start()
    def _loop(self):
        while not _shutdown_flag.is_set():
            try:
                with self._lock: qs=dict(self._qs)
                data=collect_stats(qs)
                _notif_store.add_alerts(data.get('alerts',[]))
                with self._lock: self._latest=data
            except Exception as e: logger.warning(f'BackgroundCollector: {e}')
            _shutdown_flag.wait(self._interval)

_bg           = BackgroundCollector(interval=5)
_notif_store  = NotificationStore(NOTIF_FILE)
_speed_hist   = SpeedtestHistory(SPEED_FILE)

# ── HTTP Handler ──────────────────────────────────────────────────────────────
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self,*a,**kw): super().__init__(*a,directory='.',**kw)
    def log_message(self,fmt,*args): pass
    def _ip(self): return self.client_address[0] if self.client_address else '0.0.0.0'
    def _json(self,data,status=200):
        body=json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        parsed=urlparse(self.path); qs=parse_qs(parsed.query); path=parsed.path

        # Public
        if path in ('/','index.html'): super().do_GET(); return
        if path=='/api/health':
            self._json({'status':'ok','version':VERSION,'uptime_s':round(time.time()-_server_start_time)}); return

        token_info=authenticate_request(self.headers,qs)
        if not token_info: self.send_error(401,'Unauthorized'); return

        if path=='/api/stats':
            _bg.update_qs(qs)
            cached=_bg.get()
            try: self._json(cached if cached else collect_stats(qs))
            except Exception as e: logger.exception('/api/stats'); self._json({'error':str(e)},500)

        elif path=='/api/settings':
            self._json(read_yaml_settings())

        elif path=='/api/notifications':
            self._json(_notif_store.get_all())

        elif path=='/api/speedtest-history':
            self._json(_speed_hist.get_all())

        elif path=='/api/stream':
            _bg.update_qs(qs)
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream')
            self.send_header('Cache-Control','no-cache')
            self.send_header('Connection','keep-alive')
            self.end_headers()
            try:
                first=_bg.get() or collect_stats(qs)
                self.wfile.write(f'data: {json.dumps(first)}\n\n'.encode()); self.wfile.flush()
                while not _shutdown_flag.is_set():
                    _shutdown_flag.wait(5)
                    if _shutdown_flag.is_set(): break
                    d=_bg.get()
                    if d: self.wfile.write(f'data: {json.dumps(d)}\n\n'.encode()); self.wfile.flush()
            except (BrokenPipeError,ConnectionResetError,OSError): pass
            except Exception as e: logger.warning(f'SSE: {e}')

        elif path=='/api/log-viewer':
            lt=qs.get('type',['syserr'])[0]
            if   lt=='syserr': text=run(['journalctl','-p','3','-n','25','--no-pager'],timeout=4)
            elif lt=='action':
                try: text=strip_ansi(open(ACTION_LOG).read())
                except FileNotFoundError: text='No recent actions.'
            elif lt=='backup':
                try:
                    lines=open(os.path.join(LOG_DIR,'backup-to-nas.log')).readlines()
                    text=strip_ansi(''.join(lines[-30:]))
                except FileNotFoundError: text='No backup log found.'
            else: text='Unknown log type.'
            body=(text or 'Empty.').encode()
            self.send_response(200)
            self.send_header('Content-Type','text/plain; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers(); self.wfile.write(body)

        elif path=='/api/action-log':
            try: text=strip_ansi(open(ACTION_LOG).read())
            except FileNotFoundError: text='Waiting for output…'
            body=text.encode()
            self.send_response(200); self.send_header('Content-Type','text/plain; charset=utf-8')
            self.end_headers(); self.wfile.write(body)

        else: self.send_error(404)

    def do_POST(self):
        path=self.path.split('?')[0]; ip=self._ip()

        if path=='/api/login':
            if _rate_limiter.is_locked(ip):
                self._json({'error':'Too many failed attempts. Try again shortly.'},429); return
            try:
                body=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
                username=body.get('username',''); password=body.get('password','')
                users=load_users()
                user=users.get(username)
                if user and verify_password(user['hash'],password):
                    _rate_limiter.reset(ip)
                    token=generate_token(username,user['role'])
                    self._json({'token':token,'role':user['role'],'username':username})
                else:
                    locked=_rate_limiter.record_failure(ip)
                    msg='Too many failed attempts. Try again shortly.' if locked else 'Invalid credentials'
                    self._json({'error':msg},401)
            except Exception as e:
                logger.exception('/api/login'); self._json({'error':str(e)},500)
            return

        if path=='/api/logout':
            parsed=urlparse(self.path); qs=parse_qs(parsed.query)
            token=None
            ah=self.headers.get('Authorization','')
            if ah.startswith('Bearer '): token=ah[7:]
            elif 'token' in qs: token=qs['token'][0]
            if token: revoke_token(token)
            self._json({'status':'ok'}); return

        token_info=authenticate_request(self.headers)
        if not token_info: self.send_error(401,'Unauthorized'); return

        if path in ADMIN_ONLY_POST and token_info.get('role')!='admin':
            self._json({'error':'Admin role required'},403); return

        if path=='/api/settings':
            try:
                body=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
                ok=write_yaml_settings(body)
                self._json({'status':'ok'} if ok else {'error':'Write failed'}, 200 if ok else 500)
            except Exception as e:
                logger.exception('/api/settings POST'); self._json({'error':str(e)},500)

        elif path=='/api/run':
            try:
                body=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
                script=body.get('script','')
                with open(ACTION_LOG,'w') as f:
                    f.write(f'>> [{datetime.now().strftime("%H:%M:%S")}] Initiating: {script}\n\n')
                success=False
                if script=='speedtest':
                    with open(ACTION_LOG,'a') as f:
                        p=subprocess.Popen(['speedtest-cli','--simple'],stdout=f,stderr=subprocess.STDOUT)
                        p.wait(timeout=120); success=p.returncode==0
                    if success:
                        try:
                            with open(ACTION_LOG) as f: output=f.read()
                            dl,ul,ping=SpeedtestHistory.parse_output(output)
                            if dl is not None and ul is not None and ping is not None:
                                _speed_hist.add(dl,ul,ping)
                        except Exception as e: logger.warning(f'speedtest parse: {e}')
                elif script in SCRIPT_MAP:
                    sfile=os.path.join(SCRIPT_DIR,SCRIPT_MAP[script])
                    if os.path.isfile(sfile):
                        with open(ACTION_LOG,'a') as f:
                            p=subprocess.Popen([sfile,'--verbose'],stdout=f,stderr=subprocess.STDOUT,cwd=SCRIPT_DIR)
                            p.wait(timeout=300); success=p.returncode==0
                    else:
                        with open(ACTION_LOG,'a') as f: f.write(f'[ERROR] Script not found: {sfile}\n')
                else:
                    with open(ACTION_LOG,'a') as f: f.write(f'[ERROR] Unknown script: {script}\n')
                self._json({'success':success})
            except subprocess.TimeoutExpired: self._json({'success':False,'error':'Script timed out'})
            except Exception as e:
                logger.exception('/api/run'); self._json({'success':False,'error':str(e)})

        elif path=='/api/service-control':
            try:
                body=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
                svc=body.get('service','').strip(); action=body.get('action','').strip(); is_user=bool(body.get('is_user',False))
                if action not in ALLOWED_ACTIONS: return self._json({'success':False,'error':f'Action "{action}" not allowed'})
                if not svc: return self._json({'success':False,'error':'No service name'})
                if not validate_service_name(svc): return self._json({'success':False,'error':'Invalid service name'})
                cmd=(['systemctl','--user',action,svc] if is_user else ['sudo','-n','systemctl',action,svc])
                r=subprocess.run(cmd,timeout=10,capture_output=True)
                self._json({'success':r.returncode==0,'stderr':r.stderr.decode().strip()})
            except Exception as e: self._json({'success':False,'error':str(e)})

        else: self.send_error(404)


class ThreadingHTTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address=True; daemon_threads=True

server=None

if __name__=='__main__':
    try:
        with open(PID_FILE,'w') as f: f.write(str(os.getpid()))
    except Exception as e: logger.warning(f'PID file: {e}')

    _bg.start()
    threading.Thread(target=_token_cleanup_loop,daemon=True,name='token-cleanup').start()

    server=ThreadingHTTPServer((HOST,PORT),Handler)

    if USE_HTTPS:
        import ssl
        ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        try:
            ctx.load_cert_chain(CERT_FILE,KEY_FILE)
            server.socket=ctx.wrap_socket(server.socket,server_side=True)
            proto='https'
        except Exception as e:
            print(f'[ERROR] TLS setup failed: {e}',file=sys.stderr)
            print(f'        Run: noba-web --generate-cert',file=sys.stderr)
            sys.exit(1)
    else:
        proto='http'

    url=f'{proto}://{HOST}:{PORT}'
    logger.warning(f'Serving at {url}  (v{VERSION})')
    print(f'Noba server v{VERSION} starting at {url}',file=sys.stderr)

    try: server.serve_forever()
    except KeyboardInterrupt: logger.info('Shutting down…')
    except Exception as e: logger.exception('Unhandled exception')
    finally:
        _shutdown_flag.set(); server.shutdown()
        try: os.unlink(PID_FILE)
        except: pass
        logger.info('Server stopped.')
