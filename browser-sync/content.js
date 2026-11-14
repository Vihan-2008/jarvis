/* Capture opened, saved conversations only. No cookies or hidden account requests. */
(()=>{
 if(globalThis.JCCCapture?.stop)globalThis.JCCCapture.stop();
 let previous='',timer,interval;
 function roots(){const found=[document];for(let i=0;i<found.length&&i<30;i++){for(const node of [...found[i].querySelectorAll('*')].slice(0,20000)){if(node.shadowRoot)found.push(node.shadowRoot)}}return found}
 function roleOf(node,claude){
  for(const attr of ['data-message-author-role','data-turn','data-role','data-author']){const v=node.getAttribute(attr);if(['user','human'].includes(v))return 'user';if(['assistant','model'].includes(v))return 'assistant'}
  const testid=node.getAttribute('data-testid')||'';
  if(/(?:^|[-_])(user|human)[-_]message|message[-_](user|human)(?:$|[-_])/.test(testid))return 'user';
  if(/(?:^|[-_])(assistant|model)[-_]message|message[-_](assistant|model)(?:$|[-_])/.test(testid))return 'assistant';
  if(claude&&testid==='user-message')return 'user';
  if(claude&&node.matches?.('.font-claude-response'))return 'assistant';
  const label=(node.getAttribute('aria-label')||node.querySelector('h1,h2,h3,h4,h5,h6,[data-testid="author"]')?.innerText||'').trim();
  if(/^(you(?: said)?|user|human)\s*:?$/i.test(label))return 'user';
  if(/^(chatgpt(?: said)?|assistant|claude|gpt[-\s]?\d[\w. -]*)\s*:?$/i.test(label))return 'assistant';
  const line=(node.innerText||'').trim().split('\n')[0];
  if(/^You said:\s*$/i.test(line))return 'user';if(/^ChatGPT said:\s*$/i.test(line))return 'assistant';
  return null;
 }
 function collect(){
  const claude=location.hostname==='claude.ai';const saved=claude?/^\/chat\/[^/]+/.test(location.pathname):/\/c\/[^/]+/.test(location.pathname);
  const selector='[data-message-author-role],[data-turn="user"],[data-turn="assistant"],[data-role="user"],[data-role="assistant"],[data-testid*="message"],[data-testid^="conversation-turn"],article,[role="article"],.font-claude-response';
  const allRoots=roots(),nodes=[...new Set(allRoots.flatMap(root=>[...root.querySelectorAll(selector)]))];
  const entries=nodes.map(node=>({node,role:roleOf(node,claude)})).filter(x=>x.role&&!x.node.closest?.('form,textarea,[contenteditable="true"],[data-testid="composer"]'));
  const headingSelector='h1,h2,h3,h4,h5,h6,[role="heading"]';
  const headingRole=h=>['user','assistant'].includes(h.getAttribute?.('data-conversation-role'))?h.getAttribute('data-conversation-role'):/^You said:\s*$/i.test((h.textContent||h.innerText||'').trim())?'user':/^ChatGPT said:\s*$/i.test((h.textContent||h.innerText||'').trim())?'assistant':null;
  function visibleMessageText(node){
   if(!node.childNodes)return (node.innerText||'').trim().replace(/^(You said:|ChatGPT said:)(?:\s*\n|\s*$)/i,'').trim();
   let visits=0;
   function walk(n){
    if(++visits>30000)return '';
    if(n.nodeType===3)return n.nodeValue||'';
    if(n.nodeType!==1)return '';
    if(n.matches('button,[role="button"],nav,textarea,[contenteditable="true"],script,style,'+headingSelector))return '';
    const style=getComputedStyle(n);if(style.display==='none'||style.visibility==='hidden')return '';
    if(n.tagName==='BR')return '\n';
    const text=[...n.childNodes].map(walk).join('');
    return /^(DIV|P|PRE|LI|SECTION|BLOCKQUOTE|UL|OL|TABLE|TR)$/.test(n.tagName)?'\n'+text+'\n':text;
   }
   return walk(node).replace(/\n{3,}/g,'\n\n').trim();
  }
  // New ChatGPT layouts expose exact speaker headings without turn attributes
  // or article elements. Stop before an adjacent turn or the draft composer.
  if(!claude&&!entries.length){
   for(const root of allRoots){for(const heading of root.querySelectorAll(headingSelector)){
    const role=headingRole(heading);if(!role)continue;
    let node=heading.parentElement;
    for(let depth=0;node&&depth<9;depth++,node=node.parentElement){
     if(node.querySelector('textarea,[contenteditable="true"],[data-testid="composer"]'))break;
     if([...node.querySelectorAll(headingSelector)].filter(headingRole).length>1)break;
     if(visibleMessageText(node)){entries.push({node,role,headings:true});break}
    }
   }}
  }
  const messages=[];
  for(const {node,role,headings} of entries){
   if(entries.some(x=>x.node!==node&&node.contains(x.node)&&x.role===role))continue;
   const body=node.querySelector('.markdown,.whitespace-pre-wrap,[data-testid="message-content"]')||node;
   const content=headings?visibleMessageText(node):(body.innerText||'').trim().replace(/^(You said:|ChatGPT said:)\s*\n/i,'').trim();
   if(content)messages.push({role,content});
  }
  return {source:claude?'Claude':'ChatGPT',url:location.origin+location.pathname,title:document.title,messages,saved,
    structure:{roots:allRoots.length,candidates:nodes.length,recognized:entries.length}};
 }
 async function sync(){
  const payload=collect();
  try{await chrome.runtime.sendMessage({type:'probe',diagnostic:{source:payload.source,path:location.pathname,messages:payload.messages.length,saved:payload.saved,structure:payload.structure,at:Date.now()}})}catch(e){}
  if(!payload.saved||!payload.messages.length)return;
  const fingerprint=JSON.stringify(payload);if(previous===fingerprint)return;
  try{const result=await chrome.runtime.sendMessage({type:'capture',payload});if(result?.ok)previous=fingerprint}catch(e){}
 }
 const observer=new MutationObserver(()=>{clearTimeout(timer);timer=setTimeout(sync,1800)});
 observer.observe(document.documentElement,{subtree:true,childList:true,characterData:true});interval=setInterval(sync,12000);
 globalThis.JCCCapture={collect,sync,stop:()=>{observer.disconnect();clearInterval(interval);clearTimeout(timer)}};sync();
})();
