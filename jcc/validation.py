"""Conservative Python import dependencies; full configured checks remain mandatory."""
import ast
import importlib.util
import json
from jcc import job_control
import time
from dataclasses import replace
from pathlib import Path
from jcc import projects
from jcc.vault import atomic_write


def focused(project,root):
    if project.check_mode!='python':return [],'Command projects use their configured full checks.'
    changed=projects.changed_files(root)
    # Any config, fixture, deletion or unsupported test runner requires the full suite.
    if not changed or any(not n.endswith('.py') or Path(n).name in ('conftest.py','setup.py','__init__.py') or not (root/n).is_file() for n in changed):return [],'Shared files, configuration or unsupported changes require full checks.'
    files=[]
    for folder in ('src','tests'):
        for path in (root/folder).rglob('*.py'):
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):return [],'Unsafe source path; full checks.'
            if path.stat().st_size>200000:return [],'Large source; full checks.'
            files.append(path)
            if len(files)>600:return [],'Dependency graph limit; full checks.'
    if any(root/n not in files for n in changed):return [],'Changed source is outside the supported layout.'
    modules={}
    for p in files:
        rel=p.relative_to(root).with_suffix('');parts=list(rel.parts)
        if parts[0]=='src':parts=parts[1:]
        if parts[-1]=='__init__':parts=parts[:-1]
        modules[p]='.'.join(parts)
    graph={}
    try:
        for path,module in modules.items():
            tree=ast.parse(path.read_text('utf-8-sig'));imports=set()
            package=module if path.name=='__init__.py' else module.rpartition('.')[0]
            for node in ast.walk(tree):
                if isinstance(node,ast.Call) and (isinstance(node.func,ast.Name) and node.func.id in ('__import__','exec','eval') or isinstance(node.func,ast.Attribute) and node.func.attr in ('import_module','spec_from_file_location','run_module','run_path')):return [],'Dynamic dependency; full checks.'
                if isinstance(node,ast.Import):imports.update(a.name for a in node.names)
                if isinstance(node,ast.ImportFrom):
                    name=node.module or ''
                    if node.level:name=importlib.util.resolve_name('.'*node.level+name,package)
                    imports.add(name);imports.update(name+'.'+a.name for a in node.names)
            graph[module]={m for m in modules.values() if any(i==m or i.startswith(m+'.') for i in imports)}
    except (SyntaxError,UnicodeError,ValueError,ImportError,OSError):return [],'Dependency analysis was inconclusive; full checks.'
    tests=[p for p in files if p.relative_to(root).parts[0]=='tests' and p.name.startswith('test') and p.name!='__init__.py']
    changed_modules={modules[root/n] for n in changed};affected=[];covered=set()
    for test in tests:
        seen=set();todo=[modules[test]]
        while todo:
            module=todo.pop()
            if module in seen:continue
            seen.add(module);todo.extend(graph.get(module,set())-seen)
        hit=changed_modules & seen
        if hit:affected.append(test);covered.update(hit)
    if not affected or len(affected)>=len(tests) or covered!=changed_modules:return [],'No safe smaller test set; full checks.'
    checks=[]
    for command in project.checks:
        if command[:2]==['-m','pytest'] and not any(x in command for x in ('--cov','--collect-only','--lf','--last-failed','-k')):
            # The leading -m belongs to Python; permit the common simple runner only.
            checks.append(['-m','pytest','-q',*[p.relative_to(root).as_posix() for p in affected]])
        elif command[:3]==['-m','unittest','discover'] and all((p.parent/'__init__.py').exists() for p in affected):
            checks.append(['-m','unittest',*[modules[p] for p in affected]])
        else:return [],'Custom checks use the full configured commands.'
    return checks,'Transitive Python imports identify '+str(len(affected))+' of '+str(len(tests))+' test files.'


def run(project,root,env,timeout_s,work,repair=False):
    deadline=time.monotonic()+timeout_s;selected,reason=focused(project,root) if repair else ([], 'Initial implementation uses full checks.')
    report={'strategy':'focused_then_full' if selected else 'full','reason':reason,'focused_checks':selected,'full_ran':False}
    if selected:
        results=projects.run_checks(replace(project,checks=selected),root,env,max(1,int(deadline-time.monotonic())))
        if not results or not all(c.ok for c in results):
            report['focused_passed']=False;atomic_write(work/'validation.json',json.dumps(report));return results
        if time.monotonic()>=deadline or (work/'control.json').exists() and job_control.signal(work) in ('pause','cancel'):
            atomic_write(work/'validation.json',json.dumps(report));return [projects.CheckResult('full checks',False,'Paused or time budget reached before required full checks.')]
        report['focused_passed']=True
    report['full_ran']=True
    results=projects.run_checks(project,root,env,max(1,int(deadline-time.monotonic())))
    report['full_passed']=bool(results) and all(c.ok for c in results);atomic_write(work/'validation.json',json.dumps(report))
    return results
