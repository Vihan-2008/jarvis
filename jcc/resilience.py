"""Detect repeated repairs and reconcile abandoned workers without replaying edits."""
import ctypes
import hashlib
import json
import os
import re
import time
from pathlib import Path
from jcc import activity, projects, receipts
from jcc.lock import InstanceLock
from jcc.vault import Vault, atomic_write, parse_frontmatter, render_note


def process_identity(pid):
    if not isinstance(pid,int) or pid<=0:return None
    if os.name=='nt':
        from ctypes import wintypes
        api=ctypes.WinDLL('kernel32',use_last_error=True)
        api.OpenProcess.restype=wintypes.HANDLE
        api.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        api.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        api.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
        api.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=api.OpenProcess(0x1000,False,pid)
        if not handle:return None
        try:
            code=wintypes.DWORD();times=[wintypes.FILETIME() for _ in range(4)]
            if not api.GetExitCodeProcess(handle,ctypes.byref(code)) or code.value!=259:return None
            if not api.GetProcessTimes(handle,*[ctypes.byref(t) for t in times]):return None
            return str((times[0].dwHighDateTime<<32)+times[0].dwLowDateTime)
        finally:api.CloseHandle(handle)
    try:
        from pathlib import Path
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19]
    except OSError:pass
    return _started_by_ps(pid)


def _started_by_ps(pid,run=None):
    """When a process started, from ps, where there is no /proc (a Mac). Together with the pid it tells this process
    apart from a later one that was given the same number. None when no such process is running."""
    import subprocess
    try:
        done=(run or subprocess.run)(['ps','-o','lstart=','-p',str(int(pid))],capture_output=True,text=True,timeout=5,stdin=subprocess.DEVNULL)
    except (OSError,ValueError,subprocess.TimeoutExpired):return None
    started=' '.join((done.stdout or '').split())
    return started if done.returncode==0 and started else None


def child_alive(work):
    p=work/'active-process.json'
    try:
        row=json.loads(p.read_text('utf-8'))
        return bool(row.get('identity') and process_identity(row.get('pid'))==row['identity'])
    except (ValueError,OSError):return False


def repair_state(checks,repo,attempts):
    errors='\n'.join(c.name+': '+c.tail for c in checks if not c.ok)
    normalized=re.sub(r'\b\d+(?:\.\d+)?s\b|\b\d{2}:\d{2}:\d{2}\b','<time>',errors)
    signature=hashlib.sha256(normalized.encode()).hexdigest()[:20]
    names=projects.changed_files(repo)
    names=[name for name in names if not any(p.lower() in ('.ssh','.git','private') or p.lower().startswith('.env') for p in Path(name).parts)
           and Path(name).suffix.lower() not in ('.key','.pem','.pfx','.p12') and Path(name).name.lower() not in ('credentials.json','auth.json','server.json')]
    diff=projects.git(['diff','HEAD','--',*names],repo,check=False) if names else ''
    # Include untracked contents so a real repair in a new file counts as progress.
    for name in names[:40]:
        p=repo/name
        if not p.is_symlink() and p.resolve().is_relative_to(repo.resolve()) and p.is_file() and p.stat().st_size<100000:
            diff+='\n'+name+'\n'+hashlib.sha256(p.read_bytes()).hexdigest()
    fingerprint=hashlib.sha256(diff.encode()).hexdigest()[:20]
    repeats=[a for a in attempts[:-1] if a.get('repair_signature')==signature]
    stuck=any(a.get('repair_diff')==fingerprint for a in repeats) or len(repeats)>=2
    return {'repair_signature':signature,'repair_diff':fingerprint,'stuck':stuck}


def recover(cfg,grace=90):
    from jcc import workspace
    workspace.refresh(cfg)
    vault=Vault(cfg.vault);recovered=[]
    for path in sorted((cfg.vault/'Jobs').glob('*.md'),reverse=True)[:200]:
        try:rid=activity.job_id(path.stem)
        except ValueError:continue
        fm,body=parse_frontmatter(path.read_text('utf-8'))
        if fm.get('status')!='running' or grace>0 and time.time()-path.stat().st_mtime<grace:continue
        work=cfg.jobs_root/rid
        lock=InstanceLock(work/'job.lock')
        if not lock.acquire():continue
        try:
            if child_alive(work):continue  # An orphaned agent must finish before replay is possible.
            fm,body=parse_frontmatter(path.read_text('utf-8'))
            if fm.get('status')!='running':continue
            # A crash after the checked merge but before the receipt write must
            # not cause the already merged task to execute for a second time.
            proj=cfg.projects.get(fm.get('project_key'));merged=''
            if proj and proj.path.exists():
                message=f'Merge jcc/{rid} (JARVIS job, all checks passed)'
                found=projects.git(['log',proj.base_branch,'--merges','-1','--fixed-strings','--grep='+message,'--format=%H%x00%s','--'],proj.path,check=False).strip().split('\0',1)
                if len(found)==2 and found[1]==message:merged=found[0]
            # Interrupted by JARVIS itself (a restart, a crash, the PC switched off): it carries on by itself, from where it
            # stopped, at most twice; after that it waits for its owner's Continue.
            again=not merged and int(fm.get('auto_resumes') or 0)<2
            final_status='done' if merged else ('queued' if again else 'paused')
            if not merged and (work/'worker.json').exists() and (work/'worker-heartbeat.json').exists():
                worker=json.loads((work/'worker.json').read_text('utf-8'));beat=json.loads((work/'worker-heartbeat.json').read_text('utf-8'))
                elapsed=max(0,beat.get('at',0)-worker.get('started_at',time.time()))
                runtime_path=work/'runtime.json';runtime=json.loads(runtime_path.read_text('utf-8')) if runtime_path.exists() else {}
                runtime['active_seconds']=max(runtime.get('active_seconds',0),worker.get('prior_seconds',0)+elapsed)
                atomic_write(runtime_path,json.dumps(runtime))
                attempts_path=work/'attempts.json';attempts=json.loads(attempts_path.read_text('utf-8')) if attempts_path.exists() else []
                if elapsed and len(attempts)<=worker.get('prior_attempts',0):
                    attempts.append({'agent':fm.get('agent') or 'unknown','model':fm.get('model') or 'unknown','exit':130,'limit':False,
                        'seconds':round(elapsed,2),'interrupted':True,'recovered':True,'input_tokens':None,'cached_tokens':None,'output_tokens':None})
                    atomic_write(attempts_path,json.dumps(attempts))
            fm.update({'status':final_status,'recovered_at':time.time(),'recovery_reason':'Checked merge recovered; task not replayed.' if merged else 'Worker interrupted; edits preserved.'})
            if again:
                fm['auto_resumes']=int(fm.get('auto_resumes') or 0)+1
                work.mkdir(parents=True,exist_ok=True);atomic_write(work/'control.json',json.dumps({'action':'resume','at':time.time()}))
            if merged:fm.update({'merged':merged,'checks_passed':True})
            vault.write(f'Jobs/{rid}.md',render_note(fm,body+('\n\nChecked merge recovered after a worker interruption. The completed task was not replayed.' if merged else '\n\nWorker interruption detected. Existing files and checkpoints are preserved. Resume explicitly from Activity.')))
            if not merged and not (work/'HANDOFF.md').exists():
                atomic_write(work/'HANDOFF.md','# Interrupted work\n\nGoal: '+str(fm.get('task',''))[:1000]+'\n\nInspect the preserved branch and run checks before continuing. Previous completion is not established.')
            receipts.update_status(vault,rid,final_status)
            if fm.get('chat_id'):
                from jcc.chats import Chats
                Chats(cfg).update(fm['chat_id'],message={'role':'assistant','receipt':rid,'status':final_status,'content':'JARVIS found this task was already merged with passing checks; it was not replayed.' if merged else
                    'JARVIS was interrupted, so this job carries on by itself from where it stopped. Its work so far is kept.' if again else
                    'This job was interrupted again. Its work so far is kept: press Continue, or tell JARVIS what to do next, and it carries on from where it stopped.'})
            activity.emit(cfg,rid,'recovered','Checked merge recovered; the task was not replayed.' if merged else 'The worker stopped unexpectedly. Files and checkpoints were preserved; resume from Activity.')
            activity.alert(cfg,rid,final_status);recovered.append(rid)
        finally:lock.release()
    atomic_write(cfg.state_dir/'recovery-status.json',json.dumps({'at':time.time(),'status':'checked','recovered':recovered}))
    return recovered
