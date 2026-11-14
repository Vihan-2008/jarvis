"""Read-only project inspection followed by explicit registration."""
import json
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from jcc import projects, workspace
from jcc.config import _project
from jcc.lock import InstanceLock
from jcc.vault import Vault, atomic_write, render_note


def choose_folder():
    try:
        result = subprocess.run(
            [sys.executable, "-m", "jcc.folder_picker"],
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True, timeout=300, check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        raise ValueError("The folder chooser could not open. Paste the folder path instead.") from error


def inspect(cfg, folder):
    if not str(folder or "").strip():
        raise ValueError("Choose a project folder.")
    root = Path(folder).expanduser().resolve()
    if not root.is_dir(): raise ValueError('Choose an existing project folder.')
    for denied in (cfg.vault, *cfg.protected):
        denied = denied.resolve()
        if root.is_relative_to(denied) or denied.is_relative_to(root):
            raise ValueError('Choose a project folder outside the vault and protected folders.')
    def read(name):
        p = root / name
        if p.is_symlink() or not p.resolve().is_relative_to(root) or not p.is_file() or p.stat().st_size > 500000: return ''
        return p.read_text('utf-8')
    git_root = projects.git(['rev-parse', '--show-toplevel'], root, check=False).strip()
    is_repo = bool(git_root) and Path(git_root).resolve() == root
    branch = projects.git(['branch', '--show-current'], root, check=False).strip() if is_repo else ''
    py = root / '.venv/Scripts/python.exe' if sys.platform == 'win32' else root / '.venv/bin/python'
    if not py.exists(): py = Path(sys.executable).with_name('python.exe') if Path(sys.executable).name == 'pythonw.exe' else Path(sys.executable)
    stack, checks, mode, notes = [], [], 'python', []
    package = read('package.json')
    if package:
        data = json.loads(package); stack.append('Node.js / JavaScript')
        tools = set(data.get('dependencies', {})) | set(data.get('devDependencies', {}))
        stack += sorted(tools & {'react','next','vue','vite','typescript','vitest','jest','playwright'})
        if 'test' in data.get('scripts', {}) and 'no test specified' not in data['scripts']['test']:
            npm = shutil.which('npm.cmd') or shutil.which('npm')
            if npm:
                checks = [['cmd.exe','/d','/c',npm,'run','test']] if sys.platform == 'win32' else [[npm,'run','test']]
                mode = 'command'
            notes.append('Detected test script: ' + str(data['scripts']['test'])[:300])
    pyproject = read('pyproject.toml')
    if pyproject or read('requirements.txt') or (root/'tests').is_dir() and not package:
        stack.append('Python')
        data = tomllib.loads(pyproject) if pyproject else {}
        samples = list((root/'tests').glob('test*.py'))[:12]
        pytest = (root/'pytest.ini').exists() or 'pytest' in json.dumps(data).lower()
        texts = [read(p.relative_to(root).as_posix()) for p in samples]
        pytest = pytest or any('def test_' in text and 'unittest.TestCase' not in text for text in texts)
        if pytest: checks = [['-m','pytest','-q']]
        elif (root/'tests').is_dir(): checks = [['-m','unittest','discover','-s','tests']]
        mode = 'python'
    if (root/'Cargo.toml').is_file():
        stack.append('Rust'); checks = [[shutil.which('cargo'),'test']] if shutil.which('cargo') else []; mode = 'command'
    if (root/'go.mod').is_file():
        stack.append('Go'); checks = [[shutil.which('go'),'test','./...']] if shutil.which('go') else []; mode = 'command'
    if not stack and (root/'index.html').is_file(): stack.append('Static website')
    key = re.sub(r'[^a-z0-9]+','-',root.name.lower()).strip('-')[:48]
    package_managers=[name for name in ('package-lock.json','pnpm-lock.yaml','yarn.lock','uv.lock','poetry.lock','Cargo.lock','go.sum') if (root/name).is_file()]
    entries=[p.name+('/' if p.is_dir() else '') for p in root.iterdir() if not p.name.startswith('.') and p.name not in ('node_modules','venv','Private')][:60]
    return {'package_managers':package_managers,'structure':entries,'baseline':'The first coding run records the configured checks before editing. Inspection itself executes no repository code.','name':root.name, 'key':key, 'path':str(root), 'stack':stack or ['Unknown'], 'git':is_repo,
        'branch':branch, 'python':str(py), 'checks':checks, 'check_mode':mode, 'notes':notes,
        'connected_key':next((key for key, project in cfg.projects.items() if project.path.resolve() == root), None),
        'ready':is_repo and bool(branch) and bool(checks)}


def connect(cfg, folder, name=''):
    info = inspect(cfg, folder)
    if not info['ready']: raise ValueError('A Git repository on a named branch and detected test command are required. No files were changed.')
    if not workspace.KEY.fullmatch(info['key']): raise ValueError('Use a project folder name beginning with a letter.')
    lock = InstanceLock(cfg.state_dir/'projects.lock')
    if not lock.acquire(): raise ValueError('Another project is being connected.')
    try:
        workspace.refresh(cfg)
        if info['key'] in cfg.projects or any(p.path.resolve() == Path(info['path']) for p in cfg.projects.values()):
            raise ValueError('This project is already connected.')
        entry = {'name':name.strip()[:100] or info['name'], 'path':info['path'], 'base_branch':info['branch'],
            'python':info['python'], 'pythonpath':['src','.'], 'checks':info['checks'], 'check_mode':info['check_mode'],
            'keywords':[info['key']], 'auto_merge':False, 'no_auto_merge':['.env','.github/','deploy/','Dockerfile','risk_limits']}
        registry = cfg.state_dir/'projects.json'
        values = json.loads(registry.read_text('utf-8')) if registry.exists() else {}
        values[info['key']] = entry; atomic_write(registry,json.dumps(values,indent=2))
        cfg.projects[info['key']] = _project(info['key'],entry)
        Vault(cfg.vault).write(f"Projects/{info['key']}/Memory.md",render_note({'project':info['key']},
            f"# {entry['name']}\n\nStack: {', '.join(info['stack'])}\n\nSource: `{info['path']}`\n\n"
            'Detected checks are reviewed before coding. Auto-merge is off for this existing project.\n\n'+
            '\n'.join('- '+x for x in info['notes'])))
        return info
    finally: lock.release()
