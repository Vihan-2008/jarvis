"""Low-overhead background controls; foreground jobs remain explicitly controlled."""
import ctypes
import json
import os
import time
from jcc.vault import atomic_write,parse_frontmatter

DEFAULTS={'pause_background':False,'metered_network':False,'battery_saver':True,'defer_during_jobs':True,'retention_days':30,'max_parallel_jobs':0}


def settings(cfg):
    path=cfg.state_dir/'resources.json'
    from jcc.vault import read_json
    return {**DEFAULTS,**read_json(path,{})}


def configure(cfg,value):
    if not isinstance(value,dict) or set(value)!=set(DEFAULTS):raise ValueError('Supply all resource preferences.')
    if any(not isinstance(value[k],bool) for k in DEFAULTS if k not in ('retention_days','max_parallel_jobs')) or isinstance(value['retention_days'],bool) or not isinstance(value['retention_days'],int) or not 7<=value['retention_days']<=365:raise ValueError('Invalid background or retention preferences.')
    if isinstance(value['max_parallel_jobs'],bool) or not isinstance(value['max_parallel_jobs'],int) or not 0<=value['max_parallel_jobs']<=4:raise ValueError('Choose 0–4 parallel jobs; 0 retains the existing configuration.')
    atomic_write(cfg.state_dir/'resources.json',json.dumps(value));return value


def power():
    if os.name!='nt':return {'on_battery':None,'percent':None}
    class Status(ctypes.Structure):
        _fields_=[('ac',ctypes.c_ubyte),('flag',ctypes.c_ubyte),('percent',ctypes.c_ubyte),('reserved',ctypes.c_ubyte),('life',ctypes.c_ulong),('full',ctypes.c_ulong)]
    status=Status()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):return {'on_battery':None,'percent':None}
    return {'on_battery':status.ac==0 if status.ac in (0,1) else None,'percent':status.percent if status.percent<=100 else None}


def reason(cfg,network=False):
    prefs=settings(cfg)
    if prefs['pause_background']:return 'Background processing paused by owner.'
    if network and prefs['metered_network']:return 'Cloud transfers paused for the selected metered-network preference.'
    if prefs['battery_saver'] and power()['on_battery'] is True:return 'Background processing deferred while on battery.'
    if prefs['defer_during_jobs']:
        for path in (cfg.vault/'Jobs').glob('*.md'):
            if path.is_symlink() or path.stat().st_size>300000:continue
            with path.open('r',encoding='utf-8') as stream:head=stream.read(16000)
            fm,_=parse_frontmatter(head)
            if fm.get('status')=='running':return 'Background processing deferred while a foreground job runs.'
    return None


def cleanup(cfg):
    """Only completed local download artifacts; never notes, jobs, sessions or settings."""
    folder=(cfg.state_dir/'exports').resolve();quarantine=cfg.state_dir/'retained-exports'
    if not folder.is_relative_to(cfg.state_dir.resolve()) or quarantine.is_symlink() or not quarantine.resolve().is_relative_to(cfg.state_dir.resolve()):return 0
    quarantine.mkdir(parents=True,exist_ok=True)
    cutoff=time.time()-settings(cfg)['retention_days']*86400;moved=0
    import re
    for path in folder.glob('handoff-*.zip'):
        if not re.fullmatch(r'handoff-[a-f0-9]{16}\.zip',path.name) or path.is_symlink() or not path.resolve().is_relative_to(folder) or path.stat().st_mtime>=cutoff:continue
        destination=quarantine/path.name
        if not destination.exists():path.replace(destination);moved+=1
    atomic_write(cfg.state_dir/'retention-status.json',json.dumps({'at':time.time(),'quarantined':moved,'scope':'Old handoff downloads moved to retained-exports; no originals deleted.'}))
    return moved
