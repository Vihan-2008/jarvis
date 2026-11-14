// Pure DOM-contract tests. No browser, desktop session or screen access.
const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const code=fs.readFileSync(path.join(__dirname,'../jcc/static/reliability.js'),'utf8');
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
 for(const id of ['messages','composer','tool-view','tool-terminal','tool-browser','tool-files','tool-activity','tool-insights','settings-body','message','mode','agent','model','effort'])node(id);
 nodes.get('message').value='Add a helper. Preserve behavior.';nodes.get('mode').value='code';nodes.get('agent').value='auto';
 const document={createElement:tag=>new Element(tag),head:new Element(),body:new Element(),activeElement:null,addEventListener:(name,fn)=>{if(name==='click')listeners.push(fn)},querySelectorAll:()=>[]};
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const context={document,$:id=>nodes.get(id)||null,optionRow:new Element(),toolBar:new Element(),tools:new Element(),window:null,activeTool:'chat',state:{projects:[]},esc,obsidian:n=>'obsidian://open?file='+encodeURIComponent(n),setInterval:()=>0,current:null,scope:()=>null,TOKEN:'test',setTimeout:()=>0,openSettings:()=>{},showTool:()=>{},toast:()=>{},FormData:class{},api:async(url,body)=>{calls.push([url,body]);if(url==='/api/dry-run')return {scope:'Local snapshot',project:'<img onerror=x>',kind:'job',model:{provider:'codex',name:'test',effort:'low'},routing_reason:'Configured route',acceptance:[{requirement:'<script>unsafe</script>'}],actions:['Edit a branch'],restrictions:['No deploy'],required_checks:['unittest'],context:{characters:1,estimated_tokens:1,budget:2200,scope:'Estimate',sources:[],text:'<img>'}};if(url==='/api/evaluations')return {status:'passed',cases:[{name:'<script>case</script>',passed:true}],scope:'Fake agents'};if(url==='/api/project/preferences')return {};return {preferences:{conventions:'',review:'inherit',checks:[]},required_checks:[],check_options:[]}}};
 context.window=context;vm.createContext(context);vm.runInContext(code,context);
 return {context,nodes,created,listeners,calls,modals};
}
test('dry run never sends a chat or changes the draft',async()=>{const s=setup();await s.created.find(n=>n.textContent==='◇ Dry run').onclick();assert.equal(s.calls.length,1);assert.equal(s.calls[0][0],'/api/dry-run');assert.equal(s.nodes.get('message').value,'Add a helper. Preserve behavior.');assert.equal(s.modals.length,1);assert.match(s.nodes.get('dry-run-result').innerHTML,/&lt;script&gt;/);assert.doesNotMatch(s.nodes.get('dry-run-result').innerHTML,/<script>/)});
test('settings expose manual evaluations and handle no connected projects',async()=>{const s=setup();s.context.openSettings('app');await new Promise(setImmediate);assert.equal(s.nodes.get('policy-form').classes.has('hidden'),true);assert.match(s.nodes.get('evaluations-results').innerHTML,/&lt;script&gt;case/);assert.equal(s.calls.some(([u,b])=>u==='/api/evaluations'&&b),false)});
