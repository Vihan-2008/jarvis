// Pure DOM-contract tests. No browser, desktop session or screen access.
const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const code=fs.readFileSync(path.join(__dirname,'../jcc/static/delivery.js'),'utf8');
function setup(){
 const nodes=new Map(),created=[],listeners=[],calls=[],modals=[];
 class Element{
  constructor(tag='div'){this.tag=tag;this.dataset={};this.value='';this.disabled=false;this.classes=new Set();this.classList={add:(v)=>this.classes.add(v),remove:v=>this.classes.delete(v),toggle:(v,on)=>on===false?this.classes.delete(v):this.classes.add(v)};created.push(this)}
  set id(v){this._id=v;nodes.set(v,this)}get id(){return this._id}
  set innerHTML(v){this.html=v;for(const match of v.matchAll(/\bid="([^"]+)"/g)){const n=new Element();n.id=match[1]}}
  get innerHTML(){return this.html||''}
  setAttribute(){} append(){} insertAdjacentHTML(_,v){this.innerHTML=v} querySelector(){return new Element()} querySelectorAll(){return []} closest(){return this} focus(){} showModal(){modals.push(this)} close(){}
 }
 const node=id=>{const n=new Element();n.id=id;return n};
 for(const id of ['messages','composer','tool-view','tool-terminal','tool-browser','tool-files','tool-activity','tool-insights','settings-body','message'])node(id);
 nodes.get('message').value='Add a helper. Preserve behavior.';
 const document={createElement:tag=>new Element(tag),head:new Element(),body:new Element(),activeElement:null,addEventListener:(name,fn)=>{if(name==='click')listeners.push(fn)},querySelectorAll:()=>[]};
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const context={document,$:id=>nodes.get(id)||null,optionRow:new Element(),toolBar:new Element(),tools:new Element(),window:null,activeTool:'chat',state:{projects:[]},esc,obsidian:n=>'obsidian://open?file='+encodeURIComponent(n),setInterval:()=>0,openSettings:()=>{},showTool:()=>{},toast:()=>{},FormData:class{},api:async(url,body)=>{calls.push([url,body]);if(url==='/api/delivery/plan')return {items:[{id:'A1',requirement:'Add a helper.'}],scope:'Draft checklist'};if(url==='/api/task-queue')return {tasks:[{id:'20261111-010000-abcd',task:'<script>bad</script>',status:'queued',display_status:'blocked',project:'demo',reason:'Waiting for prerequisite',priority:0,dependencies:[]}],next:null};if(url.startsWith('/api/work-history'))return {results:[{source:'Projects/Demo/Memory',title:'Decision',snippet:'<img src=x onerror=attack()>',status:'done'}],scope:'Local sources'};return {settings:{review_enabled:false,review_timeout_seconds:90,review_context_chars:8000},rollbacks:[]}}};
 context.window=context;vm.createContext(context);vm.runInContext(code,context);
 return {context,nodes,created,listeners,calls,modals};
}
test('checklist click only previews and leaves the draft unchanged',async()=>{const s=setup();await s.created.find(n=>n.textContent==='☑ Checklist').onclick();assert.equal(s.calls.length,1);assert.equal(s.calls[0][0],'/api/delivery/plan');assert.equal(s.nodes.get('message').value,'Add a helper. Preserve behavior.');assert.equal(s.modals.length,1)});
test('task view escapes titles and keeps other panes hidden',async()=>{const s=setup();const button={dataset:{deliveryPane:'queue'}};for(const fn of s.listeners)fn({target:{closest:()=>button}});await new Promise(setImmediate);assert.equal(s.context.activeTool,'queue');assert.match(s.nodes.get('queue-list').innerHTML,/&lt;script&gt;/);assert.doesNotMatch(s.nodes.get('queue-list').innerHTML,/<script>/);assert.equal(s.nodes.get('tool-insights').classes.has('hidden'),true)});
test('work-history snippets stay inert markup',async()=>{const s=setup();s.nodes.get('recall-query').value='SQLite';await s.nodes.get('recall-form').onsubmit({preventDefault(){}});assert.match(s.nodes.get('recall-results').innerHTML,/&lt;img/);assert.doesNotMatch(s.nodes.get('recall-results').innerHTML,/<img/)});
test('acceptance evidence is escaped and labeled as agent-reported',()=>{const s=setup();const html=s.context.deliveryEvidence({acceptance:{scope:'Agent claims',items:[{id:'A1',requirement:'<script>x</script>',claim:'uncertain',evidence:'<img>'}]}});assert.match(html,/Agent report: uncertain/);assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>/)});
test('second opinion remains off until explicitly saved',async()=>{const s=setup();s.context.openSettings('usage');await new Promise(setImmediate);assert.equal(s.nodes.get('delivery-review-enabled').checked,false);s.nodes.get('delivery-review-enabled').checked=true;await s.nodes.get('delivery-settings-form').onsubmit({preventDefault(){}});const saved=s.calls.find(([url,body])=>url==='/api/delivery/settings'&&body);assert.equal(saved[1].settings.review_enabled,true);assert.equal(saved[1].settings.review_timeout_seconds,90)});
