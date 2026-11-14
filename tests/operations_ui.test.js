// DOM contracts only: no browser, screen, model requests or real downloads.
const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const code=fs.readFileSync(path.join(__dirname,'../jcc/static/operations.js'),'utf8');
function setup(){
 const nodes=new Map(),created=[],calls=[],listeners={},storage=new Map();
 class Element{
  constructor(tag='div'){this.tag=tag;this.dataset={};this.value='';this.open=false;this.checked=false;this.handlers={};this.children=[];created.push(this);this.classList={add(){},remove(){},contains(){return false}}}
  set id(id){this._id=id;nodes.set(id,this)}get id(){return this._id}
  set innerHTML(html){this.html=html;this.children=[];for(const match of html.matchAll(/<(input|textarea|select|button|div|form|h2|nav)[^>]*>/g)){const node=new Element(match[1]),attrs=match[0];for(const a of attrs.matchAll(/([\w-]+)="([^"]*)"/g)){if(a[1]==='id')node.id=a[2];if(a[1]==='value')node.value=a[2];if(a[1].startsWith('data-'))node.dataset[a[1].slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=a[2]}node.checked=/\bchecked\b/.test(attrs);this.children.push(node)}}get innerHTML(){return this.html||''}
  setAttribute(){}append(){}before(){}remove(){}focus(){this.focused=true}click(){if(this.onclick)return this.onclick()}
  insertAdjacentHTML(_,html){this.innerHTML=html}showModal(){this.open=true}close(){this.open=false}
  addEventListener(name,fn){this.handlers[name]=fn}
  querySelectorAll(selector){const m=/\[data-([\w-]+)/.exec(selector);if(!m)return [];const key=m[1].replace(/-([a-z])/g,(_,c)=>c.toUpperCase());return this.children.filter(n=>Object.hasOwn(n.dataset,key))}
 }
 for(const id of ['info','message','composer','new-chat','settings-body','mode','agent','model','effort']){const n=new Element();n.id=id}
 nodes.get('composer').onsubmit=async()=>{nodes.get('message').value=''};
 const document={head:new Element(),body:new Element(),createElement:tag=>new Element(tag),addEventListener:(n,fn)=>{(listeners[n]??=[]).push(fn)}};
 const esc=v=>String(v??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
 const context={document,$:id=>nodes.get(id)||null,window:null,optionRow:new Element(),current:'chat-a',state:{projects:[]},esc,scope:()=>context.selectedProject||'',selectedProject:'',selectProject:key=>{context.selectedProject=key==='all'?'':key;context.current=''},openSettings:()=>{},openChat:async id=>{context.current=id},makeChat:async()=>{context.current='new-chat'},renderState:()=>{},refresh:async()=>{},showTool:()=>{},obsidian:n=>'obsidian://open?file='+encodeURIComponent(n),toast:()=>{},setTimeout:()=>0,Event:class{},TOKEN:'test',localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},api:async(url,body)=>{calls.push([url,body]);
  if(url==='/api/library')return {total:1,views:[],chats:[{id:'chat-a',title:'<script>bad</script>',snippet:'<img onerror=x>',tags:[],project:null}]};
  if(url==='/api/provenance')return {source:'Memory',scope:'Reference',updated:1,age_days:1,confidence:'<script>x</script>',review_due:false,links:[]};
  if(url==='/api/dry-run')return {scope:'No work started',project:'General',level:'small',model:null,milestones:[{id:'M1',title:'<script>plan</script>',done_when:'Verified',requirements:[]}]};
  if(url==='/api/controls')return {resources:{pause_background:false,metered_network:false,battery_saver:true,defer_during_jobs:true,retention_days:30,max_parallel_jobs:0},budgets:{daily_seconds:0,daily_tokens:0,task_tokens:0,reserve_percent:5,projects:{}},prompt:{style:'concise',template:'',review_all:true},restore_points:[]};
  return {};
 }};context.window=context;context.addEventListener=(name,fn)=>{(listeners['window:'+name]??=[]).push(fn)};context.dispatchEvent=()=>{};vm.createContext(context);vm.runInContext(code,context);return {context,nodes,created,calls,listeners,storage};
}
test('opening the module sends no requests and enables no access',()=>{const s=setup();assert.equal(s.calls.length,0);assert.equal(s.created.some(n=>n.textContent==='Control'),true)});
test('conversation titles and search snippets are inert markup',async()=>{const s=setup();await s.context.openJarvisControl('library');const html=s.nodes.get('ops-content').innerHTML;assert.match(html,/&lt;script&gt;/);assert.match(html,/&lt;img/);assert.doesNotMatch(html,/<script>/);assert.equal(s.calls[0][1].action,'query')});
test('task planning only calls the dry-run endpoint',async()=>{const s=setup();s.nodes.get('message').value='Add a helper';await s.context.openJarvisControl('plan');assert.equal(s.calls.length,1);assert.equal(s.calls[0][0],'/api/dry-run');assert.match(s.nodes.get('ops-content').innerHTML,/&lt;script&gt;plan/);assert.equal(s.nodes.get('message').value,'Add a helper')});
test('drafts are isolated by chat and survive an unsent switch',async()=>{const s=setup();s.nodes.get('message').value='Draft A';s.nodes.get('message').handlers.input();await s.context.openChat('chat-b');assert.equal(s.nodes.get('message').value,'');s.nodes.get('message').value='Draft B';s.nodes.get('message').handlers.input();await s.context.openChat('chat-a');assert.equal(s.nodes.get('message').value,'Draft A');assert.equal(s.storage.get('jcc-draft-chat-b'),'Draft B')});
test('successful sending clears only the current local draft',async()=>{const s=setup();s.nodes.get('message').value='Draft';s.storage.set('jcc-draft-other','Keep');await s.nodes.get('composer').onsubmit({preventDefault(){}});assert.equal(s.storage.has('jcc-draft-chat-a'),false);assert.equal(s.storage.get('jcc-draft-other'),'Keep')});
test('settings load without starting maintenance or providers',async()=>{const s=setup();s.context.openSettings('app');await new Promise(setImmediate);assert.equal(s.calls.length,1);assert.equal(s.calls[0][0],'/api/controls');assert.equal(s.nodes.get('ops-prompt-review').checked,true);assert.equal(s.nodes.get('resource-pause_background').checked,false)});
test('Ctrl+K opens commands without executing them',()=>{const s=setup();for(const fn of s.listeners.keydown)fn({ctrlKey:true,key:'k',preventDefault(){}});assert.equal(s.nodes.get('ops-command-search').focused,true);assert.equal(s.calls.length,0)});

test('unsent drafts stay with their project when switching workspaces',()=>{const s=setup();s.context.selectProject('project-a');s.nodes.get('message').value='Project A draft';s.nodes.get('message').handlers.input();s.context.selectProject('project-b');assert.equal(s.nodes.get('message').value,'');s.nodes.get('message').value='Project B draft';s.nodes.get('message').handlers.input();s.context.selectProject('project-a');assert.equal(s.nodes.get('message').value,'Project A draft');assert.equal(s.storage.get('jcc-draft-new-project-b'),'Project B draft')});

test('creating a new chat preserves an unsent draft in the previous chat',async()=>{const s=setup();s.nodes.get('message').value='Previous chat draft';await s.context.makeChat();assert.equal(s.storage.get('jcc-draft-chat-a'),'Previous chat draft');assert.equal(s.nodes.get('message').value,'')});

test('pending attachments stay with their project draft',()=>{const s=setup();s.context.selectProject('project-a');s.context.pendingUploads=[{name:'A.txt',text:'A private draft'}];s.context.jarvisFiles=[{project:'project-a',path:'notes.txt'}];s.context.selectProject('project-b');assert.equal(s.context.pendingUploads.length,0);assert.equal(s.context.jarvisFiles.length,0);s.context.selectProject('project-a');assert.equal(s.context.pendingUploads[0].name,'A.txt');assert.equal(s.context.jarvisFiles[0].project,'project-a')});
test('first-send chat creation retains explicitly attached files',async()=>{const s=setup();s.context.selectProject('project-a');s.context.pendingUploads=[{name:'A.txt',text:'Attached'}];s.context.busy=true;await s.context.makeChat();assert.equal(s.context.pendingUploads[0].name,'A.txt')});

test('an explicitly shared page survives first-send creation but not a project switch',async()=>{const s=setup();s.context.selectProject('project-a');const check={checked:true};s.nodes.set('attach-page',check);s.context.busy=true;await s.context.makeChat();assert.equal(check.checked,true);s.context.busy=false;s.context.selectProject('project-b');assert.equal(check.checked,false)});
