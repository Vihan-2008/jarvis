const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../browser-sync/content.js'),'utf8');
function run(pathname,nodes,headings=[]){const context={location:{hostname:'chatgpt.com',origin:'https://chatgpt.com',pathname},document:{title:'Test conversation',documentElement:{},querySelectorAll:selector=>selector.startsWith("h1,")?headings:nodes},MutationObserver:class{observe(){}},setTimeout:()=>0,clearTimeout:()=>{},clearInterval:()=>{},setInterval:()=>0,chrome:{runtime:{sendMessage:async()=>({ok:true})}}};vm.createContext(context);vm.runInContext(source,context);return vm.runInContext('JCCCapture.collect()',context)}
function node(role,text,attribute='data-message-author-role'){return {innerText:text,contains:()=>false,getAttribute:name=>name===attribute?role:null,querySelector:()=>null}}
test('ordinary saved chats collect role-based messages',()=>{const result=run('/c/abc',[node('user','hello'),node('assistant','hi')]);assert.equal(result.saved,true);assert.equal(result.messages.length,2)});
test('project chat URLs and newer data-turn markup are supported',()=>{const result=run('/g/g-project/c/abc',[node('user','hello','data-turn'),node('assistant','hi','data-turn')]);assert.equal(result.saved,true);assert.equal(result.messages.length,2)});
test('home pages are not captured as conversations',()=>assert.equal(run('/',[]).saved,false));

 test('accessible message articles work when role attributes are absent',()=>{const result=run('/c/abc',[node('You said:','hello','aria-label'),node('ChatGPT said:','hi','aria-label')]);assert.equal(result.messages.length,2);assert.equal(result.messages[0].role,'user')});
 test('unknown articles are not guessed as chat messages',()=>assert.equal(run('/c/abc',[node('Other','unrelated article','aria-label')]).messages.length,0));

test('heading-only ChatGPT layouts find the message ancestor without turn markers',()=>{
 const headings=['You said:','ChatGPT said:'].map((label,i)=>{
  const h={textContent:label};
  const message={innerText:label+'\n'+(i?'What can I help you with?':'g'),querySelector:()=>null,querySelectorAll:()=>[h],contains:()=>false};
  h.parentElement={innerText:label,querySelector:()=>null,querySelectorAll:()=>[h],parentElement:message};return h;
 });
 const r=run('/c/abc',[],headings);assert.equal(r.messages.length,2);assert.equal(r.messages[0].content,'g');assert.equal(r.messages[1].role,'assistant');
});
test('heading fallback refuses a combined turn or draft composer',()=>{
 const h={textContent:'You said:'},other={textContent:'ChatGPT said:'};
 h.parentElement={innerText:'all turns',querySelector:()=>null,querySelectorAll:()=>[h,other]};
 assert.equal(run('/c/abc',[],[h]).messages.length,0);
 h.parentElement={innerText:'You said:\nunsent draft',querySelector:()=>({}),querySelectorAll:()=>[h]};
 assert.equal(run('/c/abc',[],[h]).messages.length,0);
});

test('speaker heading metadata tolerates print-only author text in ChatGPT',()=>{
 const h={textContent:'You said: Owner print name',getAttribute:key=>key==='data-conversation-role'?'user':null};
 h.parentElement={innerText:'g',querySelector:()=>null,querySelectorAll:()=>[h],contains:()=>false};
 const r=run('/c/abc',[],[h]);assert.equal(r.messages.length,1);assert.equal(r.messages[0].role,'user');assert.equal(r.messages[0].content,'g');
});
