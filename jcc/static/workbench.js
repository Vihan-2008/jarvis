/* The workspace tools share the same local authenticated API as chat. */
window.jarvisFiles=[];window.pendingUploads=[];
let activeTool='chat',terminalSession=null,terminalScope='',lastTerminal='',lastBrowser='';
const toolBar=document.createElement('nav');toolBar.className='workbench-tabs';toolBar.setAttribute('aria-label','Workspace tools');
toolBar.innerHTML='<button class="active" data-workbench="chat">◉ Chat</button><button data-workbench="terminal">⌘ Terminal</button><button data-workbench="browser">◎ Browser</button><button data-workbench="files">▤ Files</button><span>JARVIS WORKBENCH</span>';
$('messages').before(toolBar);
const tools=document.createElement('section');tools.id='tool-view';tools.className='tool-view hidden';tools.innerHTML=`
<div id="tool-terminal" class="tool-content hidden"><div class="tool-heading"><div><h2>Terminal</h2><p id="terminal-location">PowerShell · runs as your Windows user</p></div><div class="settings-buttons"><button class="plain" id="terminal-new">New session</button><button class="plain" id="terminal-stop">Stop</button></div></div><pre id="terminal-output" class="terminal-output" aria-live="polite"></pre><form id="terminal-form" class="terminal-command"><textarea id="terminal-command" rows="2" placeholder="Enter a PowerShell command…" aria-label="Terminal command"></textarea><button class="primary">Run</button></form><div class="small">Commands run in the selected project folder. For full-screen terminal programs, use a native terminal.</div></div>
<div id="tool-browser" class="tool-content hidden"><div class="tool-heading"><div><h2>Browser</h2><p>Browse in Comet and bring a page into your workspace.</p></div></div><form id="browser-open" class="browser-open"><input id="browser-url" placeholder="Enter a web address or search…" aria-label="Web address or search"><button class="primary">Open in browser</button></form><div class="browser-help">Click the JARVIS extension on a page, then <b>Share this page</b>. Its readable text appears here. Browser sign-ins stay in your browser.</div><div class="tool-heading"><a id="browser-source" class="small" target="_blank" rel="noreferrer"></a><button class="plain" id="browser-attach">Attach page to chat</button></div><article id="browser-preview" class="browser-preview">No page shared yet. Websites open in your browser so their own security and sign-ins keep working.</article></div>
<div id="tool-files" class="tool-content hidden"><div class="tool-heading"><div><h2>Project files</h2><p id="file-location">Choose a project on the left.</p></div><div class="settings-buttons"><button class="plain" id="file-up">Up</button><button class="primary hidden" id="file-attach">Attach file to chat</button></div></div><div id="file-list" class="file-list"></div><pre id="file-preview" class="file-preview hidden"></pre></div>`;
$('messages').after(tools);
const optionRow=$('agent').parentElement;
$('agent').classList.add('hidden');
optionRow.insertAdjacentHTML('beforeend','<select id="model" aria-label="AI model"><option value="auto">Auto · best fit</option></select><select id="effort" aria-label="Reasoning effort"><option value="auto">Auto effort</option></select>');
const attachments=document.createElement('div');attachments.id='attachment-chips';attachments.className='attachment-chips';$('message').after(attachments);
const attachButton=document.createElement('button');attachButton.type='button';attachButton.className='attach-button';attachButton.title='Attach text or code files';attachButton.textContent='＋ File';optionRow.prepend(attachButton);
const upload=document.createElement('input');upload.type='file';upload.multiple=true;upload.className='hidden';upload.accept='.txt,.md,.py,.js,.ts,.tsx,.jsx,.html,.css,.json,.toml,.yaml,.yml,.csv,.tsv,.log,.sql,.xml,.docx,.odt,.xlsx,.pptx,.pdf,.png,.jpg,.jpeg';document.body.append(upload);attachButton.onclick=()=>upload.click();
const pageCheck=document.createElement('label');pageCheck.className='page-attach hidden';pageCheck.innerHTML='<input type="checkbox" id="attach-page"> Shared page attached';$('composer').append(pageCheck);
function renderAttachments(){
 $('attachment-chips').innerHTML=[...window.jarvisFiles.map((f,i)=>`<button type="button" data-remove-file="${i}">▤ ${esc(f.path)} ×</button>`),...window.pendingUploads.map((f,i)=>`<button type="button" data-remove-upload="${i}" aria-label="Remove ${esc(f.name)}">▤ ${esc(f.name)}${f.label?' · '+esc(f.label):''} ×</button>`),...(window.jarvisReading?[`<span class="reading" role="status">Reading ${esc(window.jarvisReading)}…</span>`]:[])].join('');
}
window.clearJarvisAttachments=()=>{window.jarvisFiles=[];window.pendingUploads=[];$('attach-page').checked=false;pageCheck.classList.add('hidden');renderAttachments()};
upload.onchange=async()=>{
 const initialScope=current||'new:'+scope(),previousLabel=attachButton.textContent;
 window.jarvisUploading=true;attachButton.disabled=true;attachButton.textContent='Preparing file…';$('send').disabled=true;
 try{for(const f of [...upload.files].slice(0,3)){
  if(/\.(mp3|wav|m4a|ogg|webm|flac|mp4|mpeg|mpga)$/i.test(f.name)&&window.Nova?.transcribe){
   // A recording is written out as text (Whisper), so JARVIS can read what was said.
   try{attachButton.textContent='Writing out the recording…';const said=await window.Nova.transcribe(f);
    if((current||'new:'+scope())!==initialScope){toast('You changed chats while the recording was being written out. Attach it again in the chat you want.');break}
    if(!said){toast(f.name+': no speech was found in this recording.');continue}
    window.pendingUploads.push({name:f.name,text:'What is said in the recording '+f.name+':\n'+said.slice(0,60000)})
   }catch(e){toast(e.message)}
   continue}
  // Documents (PDF, Word, PowerPoint, Excel) go up to 20 MB: JARVIS turns their pages and pictures into images a job can look at.
  const document_=/\.(pdf|docx|pptx|xlsx|odt)$/i.test(f.name),most=document_?20000000:1000000;
  if(f.size>most){toast(document_?f.name+' is '+Math.max(1,Math.round(f.size/1000000))+' MB. The most JARVIS can take is 20 MB.':f.name+' exceeds the 1 MB attachment limit.');continue}
  if(document_&&window.pendingUploads.filter(u=>u.doc_id).length>=3){toast('You can attach three documents to one message.');continue}
  try{if(document_){window.jarvisReading=f.name;attachButton.textContent='Reading '+f.name+'…';renderAttachments()}
   const bytes=new Uint8Array(await f.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));const d=await api('/api/attachments/extract',{name:f.name,base64:btoa(binary)});
   if((current||'new:'+scope())!==initialScope){toast('You changed chats while the file was loading. Attach it again in the chat you want.');break}
   window.pendingUploads.push(d.image_id?{name:d.name,image_id:d.image_id,mime:d.mime}:d.doc_id?{name:d.name,doc_id:d.doc_id,text:d.text,label:d.label}:{name:d.name,text:d.text});
   if(d.notice)toast(d.notice);else if(d.truncated||d.notes.length)toast(d.name+': '+(d.truncated?'text shortened. ':'')+d.notes.join(' '))
  }catch(e){toast(e.message)}finally{window.jarvisReading='';attachButton.textContent='Preparing file…'}
 }}finally{window.jarvisUploading=false;window.jarvisReading='';attachButton.disabled=false;attachButton.textContent=previousLabel;$('send').disabled=typeof busy!=='undefined'&&busy;upload.value='';renderAttachments()}
};
document.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.removeFile!==undefined){window.jarvisFiles.splice(Number(b.dataset.removeFile),1);renderAttachments()}if(b.dataset.removeUpload!==undefined){window.pendingUploads.splice(Number(b.dataset.removeUpload),1);renderAttachments()}if(b.dataset.workbench)showTool(b.dataset.workbench);if(b.dataset.filePath!==undefined)loadFiles(b.dataset.filePath)});
let catalogSignature='';
window.updateModelPicker=d=>{
 if($('cloud-git-status')){const g=d.history.github;$('cloud-git-status').textContent='Private GitHub backup: '+(g?.status||'not connected')+(g?.at?' · '+new Date(g.at*1000).toLocaleTimeString():'')}
 if($('cloud-index-status')){const c=d.history['cloud-memory'];$('cloud-index-status').textContent='Supabase search: '+(c?.status||'not connected')+(c?' · '+c.indexed_notes+' notes · '+(c.indexed_chunks||0)+' passages indexed'+(c.pending_notes?' · '+c.pending_notes+' notes remaining':''):'')}

 const sig=JSON.stringify(d.models||[]);if(sig===catalogSignature)return;catalogSignature=sig;
 const previous=$('model').value!=='auto'?$('model').value:localStorage.getItem('jcc-model')||'auto';
 $('model').innerHTML='<option value="auto">Auto · best fit</option>'+['claude','codex'].map(provider=>'<optgroup label="'+(provider==='claude'?'Claude':'GPT / Codex')+'">'+(d.models||[]).filter(m=>m.provider===provider).map(m=>`<option value="${esc(m.id)}" data-about="${esc(m.about||'')}" title="${esc(m.about||'')}">${esc(m.label)}</option>`).join('')+'</optgroup>').join('');
 $('model').value=[...$('model').options].some(o=>o.value===previous)?previous:'auto';updateEfforts();
};
function updateEfforts(){const model=state?.models?.find(m=>m.id===$('model').value);const options=model?model.efforts:['low','medium','high','xhigh','max','ultra'];const previous=localStorage.getItem('jcc-effort')||'auto';$('effort').innerHTML='<option value="auto">Auto effort</option>'+options.map(e=>`<option value="${esc(e)}">${esc(e==='xhigh'?'Extra high':e[0].toUpperCase()+e.slice(1))}</option>`).join('');$('effort').value=options.includes(previous)?previous:'auto';$('agent').value=model?.provider||'auto'}
$('model').onchange=()=>{localStorage.setItem('jcc-model',$('model').value);updateEfforts()};$('effort').onchange=()=>localStorage.setItem('jcc-effort',$('effort').value);
if(state)window.updateModelPicker(state);
function scope(){return chat?.project||selectedProject||''}
async function showTool(name){activeTool=name;document.querySelectorAll('[data-workbench]').forEach(b=>b.classList.toggle('active',b.dataset.workbench===name));$('messages').classList.toggle('hidden',name!=='chat');$('composer').closest('.composer-wrap').classList.toggle('hidden',name!=='chat');$('tool-view').classList.toggle('hidden',name==='chat');for(const id of ['terminal','browser','files','activity'])$('tool-'+id).classList.toggle('hidden',id!==name);try{if(name==='terminal')await ensureTerminal();if(name==='browser')await refreshBrowser();if(name==='files')await loadFiles('');if(name==='activity'&&window.refreshActivity)await window.refreshActivity()}catch(e){toast(e.message)}}
async function ensureTerminal(force=false){const project=scope();if(force&&terminalSession){try{await api('/api/terminal',{action:'stop',id:terminalSession})}catch(e){}}if(force||terminalScope!==project){terminalSession=null;terminalScope=project}if(!terminalSession){const d=await api('/api/terminal',{action:'start',project:project||null});terminalSession=d.id;lastTerminal=''}await pollTerminal()}
async function pollTerminal(){if(!terminalSession)return;const d=await api('/api/terminal?id='+encodeURIComponent(terminalSession));$('terminal-location').textContent='PowerShell · '+d.cwd+(d.alive?'':' · session ended');if(lastTerminal!==d.output){const box=$('terminal-output'),atBottom=box.scrollHeight-box.scrollTop-box.clientHeight<80;box.textContent=d.output;lastTerminal=d.output;if(atBottom)box.scrollTop=box.scrollHeight}}
$('terminal-form').onsubmit=async e=>{e.preventDefault();try{await ensureTerminal();const command=$('terminal-command').value;if(!command.trim())return;await api('/api/terminal',{action:'run',id:terminalSession,command});$('terminal-command').value='';await pollTerminal()}catch(e){toast(e.message)}};
$('terminal-command').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();$('terminal-form').requestSubmit()}};
$('terminal-new').onclick=()=>ensureTerminal(true).catch(e=>toast(e.message));$('terminal-stop').onclick=async()=>{try{if(terminalSession)await api('/api/terminal',{action:'stop',id:terminalSession});await pollTerminal()}catch(e){toast(e.message)}};
setInterval(()=>{if(activeTool==='terminal')pollTerminal().catch(e=>{terminalSession=null;toast(e.message)});if(activeTool==='browser')refreshBrowser().catch(()=>{})},1500);
$('browser-open').onsubmit=async e=>{e.preventDefault();try{await api('/api/browser/open',{query:$('browser-url').value});toast('Opened in your browser. Use the JARVIS extension to share the page.')}catch(e){toast(e.message)}};
async function refreshBrowser(){const page=await api('/api/browser');if(!page)return;const sig=page.url+page.text.length;if(sig===lastBrowser)return;lastBrowser=sig;$('browser-source').textContent=page.title+' · '+page.url;$('browser-source').href=page.url;$('browser-preview').textContent=page.text.slice(0,70000)}
$('browser-attach').onclick=async()=>{try{const p=await api('/api/browser');if(!p)return toast('Share a page with the extension first.');$('attach-page').checked=true;pageCheck.classList.remove('hidden');await showTool('chat');$('message').focus();toast('The shared page will be included with your next message.')}catch(e){toast(e.message)}};
let filePath='',previewFile=null;
async function loadFiles(path){const project=scope();filePath=path;previewFile=null;$('file-attach').classList.add('hidden');$('file-preview').classList.add('hidden');if(!project){$('file-list').textContent='Choose a project on the left, or create a new project.';return}const data=await api('/api/files?project='+encodeURIComponent(project)+'&path='+encodeURIComponent(path));$('file-location').textContent=projectName(project)+' / '+(path||'');if(data.entries){$('file-list').innerHTML=data.entries.map(f=>`<button class="file-row" data-file-path="${esc(f.path)}">${f.directory?'▸':'▤'} ${esc(f.name)}</button>`).join('')||'<p class="small">This folder is empty.</p>'}else{$('file-list').innerHTML='';$('file-preview').classList.remove('hidden');$('file-preview').textContent=data.text;previewFile={project,path};$('file-attach').classList.remove('hidden')}}
$('file-up').onclick=()=>loadFiles(filePath.split('/').slice(0,-1).join('/')).catch(e=>toast(e.message));$('file-attach').onclick=async()=>{if(!previewFile)return;window.jarvisFiles.push(previewFile);renderAttachments();await showTool('chat');$('message').focus()};
window.renderRichText=text=>{let value=esc(text),blocks=[];value=value.replace(/```[^\n]*\n([\s\S]*?)```/g,(_,code)=>{blocks.push('<div class="reply-document"><button type="button" class="plain" data-edit-copy>Edit a copy</button><pre><code>'+code+'</code></pre></div>');return '\u0000BLOCK'+(blocks.length-1)+'\u0000'});value=value.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g,(_,name,label)=>{const raw=name.replace(/&amp;/g,'&').replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&lt;/g,'<').replace(/&gt;/g,'>');return '<a href="'+esc(obsidian(raw))+'">'+(label||name)+'</a>'});value=value.replace(/^### (.+)$/gm,'<h4>$1</h4>').replace(/^## (.+)$/gm,'<h3>$1</h3>').replace(/^# (.+)$/gm,'<h2>$1</h2>').replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>').replace(/`([^`\n]+)`/g,'<code>$1</code>').replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,'<a href="$2" target="_blank" rel="noreferrer">$1 ↗</a>').replace(/^[-*] (.+)$/gm,'<div class="markdown-bullet">• $1</div>').replace(/\n/g,'<br>');return value.replace(/\u0000BLOCK(\d+)\u0000/g,(_,i)=>blocks[Number(i)])};
if(chat){lastMessages='';renderChat(chat)}

// One-click editing aids. None sends a message until the user presses Send.
const sendActions=document.createElement('div');sendActions.className='send-actions';$('send').before(sendActions);
sendActions.innerHTML='<button type="button" class="prompt-master" id="prompt-master" title="Rewrite the draft with the configured small-task model">✦ Prompt Master</button><button type="button" class="plain hidden" id="undo-prompt">Undo</button>';
sendActions.append($('send'));
let refining=false,previousDraft='',reviewedDraft='';
async function rewriteDraft(text){if(refining)throw Error('Prompt Master is already working.');refining=true;$('prompt-master').disabled=true;$('prompt-master').textContent='✦ Refining…';try{return await api('/api/prompt-master',{text,project:scope()||null})}finally{refining=false;$('prompt-master').disabled=false;$('prompt-master').textContent='✦ Prompt Master'}}
$('prompt-master').onclick=async()=>{const original=$('message').value.trim();if(!original)return toast('Write a rough prompt first.');try{const d=await rewriteDraft(original);if($('message').value.trim()!==original){await navigator.clipboard.writeText(d.prompt);return toast('Your draft changed while refining. The improved prompt was copied; your current draft is unchanged.')}previousDraft=original;reviewedDraft=d.prompt;window.lastPromptRewrite=d;$('message').value=d.prompt;$('undo-prompt').classList.remove('hidden');$('message').focus();toast('Prompt improved. Review it, then Send.')}catch(e){toast(e.message)}};
$('undo-prompt').onclick=()=>{$('message').value=previousDraft;reviewedDraft='';$('undo-prompt').classList.add('hidden')};
window.preparePromptForSend=async text=>{if(localStorage.getItem('jcc-prompt-master-auto')!=='true'||text===reviewedDraft||text.startsWith('/'))return {text};const d=await rewriteDraft(text);window.lastPromptRewrite=d;previousDraft=text;reviewedDraft=d.prompt;$('undo-prompt').classList.remove('hidden');return {text:d.prompt,review:d.needs_review}};

window.mountMemorySettings=()=>{
 const box=document.createElement('div');box.className='settings-box';const git=state.history.github,cloud=state.history['cloud-memory'];
 box.innerHTML='<h3>Online second brain</h3><p id="cloud-git-status">Private GitHub backup: '+esc(git?.status||'not connected')+(git?.at?' · '+new Date(git.at*1000).toLocaleTimeString():'')+'</p><p id="cloud-index-status">Supabase search: '+esc(cloud?.status||'not connected')+(cloud?.indexed_notes?' · '+cloud.indexed_notes+' notes · '+(cloud.indexed_chunks||0)+' passages indexed':'')+'</p><p class="small">Cloud search excludes Private/ and notes marked private: true or cloud_sync: false. Vapi receives a separate read-only search key.</p><div class="settings-buttons"><button class="plain" id="cloud-env-copy">Copy Supabase settings</button><button class="plain" id="cloud-query-copy">Copy Vapi search key</button></div><label for="cloud-endpoint">Supabase Edge Function URL</label><input id="cloud-endpoint" type="url" placeholder="https://your-project.supabase.co/functions/v1/jarvis-brain" style="width:100%;margin:8px 0;padding:10px;background:#0a2031;border:1px solid #2b5266;border-radius:7px;color:#bde8f2"><button class="primary" id="cloud-enable">Enable private cloud indexing</button><p class="small">Enable after configuring the function and its secrets. Connection keys are stored in Windows Credential Manager. Anyone with the Vapi search key can retrieve indexed snippets; keep it private.</p>';
 $('settings-body').append(box);
 $('cloud-env-copy').onclick=async()=>{try{const d=await api('/api/cloud',{action:'pairing'});await navigator.clipboard.writeText(d.env);toast('Supabase settings copied. Paste only into your project’s Edge Function Secrets.')}catch(e){toast(e.message)}};
 $('cloud-query-copy').onclick=async()=>{try{const d=await api('/api/cloud',{action:'pairing'});await navigator.clipboard.writeText(d.query_key);toast('Read-only search key copied. Keep it private.')}catch(e){toast(e.message)}};
 $('cloud-enable').onclick=async()=>{try{await api('/api/cloud',{action:'enable',endpoint:$('cloud-endpoint').value.trim()});await refresh();toast('Private cloud indexing enabled. Progress appears in Settings.')}catch(e){toast(e.message)}};
 };
 
window.mountRoutingSettings=()=>{
 const box=[...$('settings-body').querySelectorAll('.settings-box')].find(b=>b.querySelector('h3')?.textContent==='Automatic model choice');if(!box)return;
 const options='<option value="auto">Auto decide</option>'+(state.models||[]).map(m=>`<option value="${esc(m.id)}" title="${esc(m.about||'')}">${esc(m.label+(m.about?' — '+m.about:''))}</option>`).join('');
 box.innerHTML='<h3>Automatic model choice</h3><p>Choose the preferred model and effort for each task size. Allowance limits still trigger fallback.</p><form id="routing-form">'+['small','medium','large'].map(level=>`<div class="routing-edit-row"><label for="route-${level}">${level[0].toUpperCase()+level.slice(1)} tasks</label><select id="route-${level}">${options}</select><select id="route-effort-${level}" aria-label="${level} effort"></select></div>`).join('')+'<button class="primary" type="submit">Save automatic routing</button></form><div class="prompt-master-setting"><label><input type="checkbox" id="auto-prompt-master"> Automatically improve prompts before sending</label><p class="small">Adds a small-model refinement step. Changes that alter protected actions or increase task complexity pause for review.</p></div>';
 function effortOptions(level){const m=state.models.find(m=>m.id===$('route-'+level).value);const old=$('route-effort-'+level).value||state.routing.choices?.[level]?.effort||'auto';$('route-effort-'+level).innerHTML='<option value="auto">Auto effort</option>'+(m?.efforts||[]).map(e=>`<option value="${esc(e)}">${esc(e)}</option>`).join('');$('route-effort-'+level).value=(m?.efforts||[]).includes(old)?old:'auto'}
 for(const level of ['small','medium','large']){$('route-'+level).value=state.routing.choices?.[level]?.model||'auto';effortOptions(level);$('route-'+level).onchange=()=>effortOptions(level)}
 $('routing-form').onsubmit=async e=>{e.preventDefault();const choices={};for(const level of ['small','medium','large'])choices[level]={model:$('route-'+level).value,effort:$('route-effort-'+level).value};try{await api('/api/routing',{choices});await refresh();toast('Automatic routing saved.');window.mountRoutingSettings()}catch(e){toast(e.message)}};
 $('auto-prompt-master').checked=localStorage.getItem('jcc-prompt-master-auto')==='true';$('auto-prompt-master').onchange=e=>localStorage.setItem('jcc-prompt-master-auto',String(e.target.checked));
};

const archiveButton=document.createElement('button');archiveButton.className='plain';archiveButton.textContent='Archive';archiveButton.title='Move this conversation between Workspace and History';$('project-pill').before(archiveButton);
function updateChatActions(){archiveButton.disabled=!chat;const item=state?.chats.find(c=>c.id===current);archiveButton.textContent=item&&!isWorkspace(item)?'To workspace':'Archive'}
archiveButton.onclick=async()=>{if(!chat)return;const item=state.chats.find(c=>c.id===current);try{await api('/api/chat/update',{id:current,archived:isWorkspace(item)});await refresh();updateChatActions()}catch(e){toast(e.message)}};
setInterval(updateChatActions,1500);
document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();$('sidebar').classList.add('open');$('search').focus()}});
document.addEventListener('click',async e=>{const b=e.target.closest('[data-answer-action]');if(!b)return;const text=chat?.messages[Number(b.dataset.messageIndex)]?.content||'';try{if(b.dataset.answerAction==='copy'){await navigator.clipboard.writeText(text);toast('Answer copied.')}else if(b.dataset.answerAction==='save'){const url=URL.createObjectURL(new Blob([text],{type:'text/markdown'}));const a=document.createElement('a');a.href=url;a.download='JARVIS response.md';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}else{speechSynthesis.cancel();const voices=speechSynthesis.getVoices().filter(v=>v.localService);if(!voices.length)return toast('No local voice is available on this computer.');const utterance=new SpeechSynthesisUtterance(text);utterance.voice=voices[0];speechSynthesis.speak(utterance)}}catch(e){toast(e.message)}});
const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;
const mic=document.createElement('button');mic.type='button';mic.className='attach-button';mic.textContent='Mic';mic.title='Dictate a prompt, or use Windows voice typing with Win+H';optionRow.prepend(mic);
mic.onclick=()=>{if(!Recognition)return toast('Use Windows voice typing: focus the message box and press Win+H.');const recognition=new Recognition();recognition.lang=navigator.language||'en-US';recognition.interimResults=false;recognition.onresult=e=>{$('message').value+=($('message').value?' ':'')+e.results[0][0].transcript;$('message').focus()};recognition.onerror=()=>toast('Browser dictation is unavailable. Windows voice typing (Win+H) works in the message box.');recognition.start()};

// Budget controls and measured usage share the existing Settings dialog.
function jobButtons(job){return ['running','queued'].includes(job.status)?`<button class="plain" data-job-action="pause" data-job-id="${esc(job.id)}">Pause</button><button class="plain" data-job-action="cancel" data-job-id="${esc(job.id)}">Cancel</button>`:['paused','failed'].includes(job.status)?`<button class="plain" data-job-action="resume" data-job-id="${esc(job.id)}">Continue</button><button class="plain" data-job-action="cancel" data-job-id="${esc(job.id)}">Cancel</button>`:''}
document.addEventListener('click',async e=>{const b=e.target.closest('[data-job-action]');if(!b)return;b.disabled=true;try{const d=await api('/api/job/control',{id:b.dataset.jobId,action:b.dataset.jobAction});toast(d.requested?'Stopping the current step and preserving edits…':'Job '+d.status+'.');await refresh()}catch(e){toast(e.message)}finally{b.disabled=false}});
window.mountEfficiencySettings=()=>{
 // (The efficiency and job limits box is gone: coding jobs have no time limit, and the rest is chosen automatically.)
 renderEfficiencyResults(state);
};
function renderEfficiencyResults(d){if(!$('efficiency-results'))return;$('efficiency-results').innerHTML=d.efficiency.jobs.slice(0,8).map(j=>`<div class="job-card"><a href="${esc(obsidian('Jobs/'+j.id))}">${esc(j.task||j.id)}</a><p>${esc((j.runs||[]).map(a=>a.agent+'/'+a.model).filter((v,i,a)=>a.indexOf(v)===i).join(' → '))} · ${esc(j.level||'')}</p><p>${esc(j.status)} · ${j.attempts} attempts · ${j.retries} retries · ${Math.round(j.seconds)}s · checks ${j.checks_passed?'passed':'not passed / not applicable'}</p><p>${j.input_tokens==null?'Provider token counts unavailable':j.input_tokens.toLocaleString()+' input · '+(j.cached_tokens==null?'cache count unavailable':j.cached_tokens.toLocaleString()+' cached input')+' · '+(j.output_tokens==null?'output count unavailable':j.output_tokens.toLocaleString()+' output')}${j.measured_attempts<j.attempts?' · partial measurement':''}</p>${(j.runs||[]).some(a=>a.resumed)?'<p>Session reused'+((j.runs||[]).some(a=>a.session_reset)?' · automatic fresh start next turn':'')+'</p>':''}${jobButtons(j)}</div>`).join('')||'<p>No measured jobs yet. Historical jobs are not assigned invented token counts.</p>'}
window.renderEfficiencyStatus=d=>{
 renderEfficiencyResults(d);
 for(const j of d.jobs){const card=[...$('jobs').querySelectorAll('.job-card')].find(c=>c.querySelector('a')?.getAttribute('href')===j.obsidian);if(card&&!card.querySelector('[data-job-action]'))card.insertAdjacentHTML('beforeend','<div class="settings-buttons">'+jobButtons(j)+'</div>')}
 const host=$('sync-diagnostics');if(host)host.innerHTML=Object.entries(d.diagnostics).map(([name,x])=>`<div class="job-card"><b>${esc(name)}</b><p>${esc(x.status||'saving local conversations')}${x.last_success?' · last saved '+new Date(x.last_success*1000).toLocaleString():x.at?' · checked '+new Date(x.at*1000).toLocaleTimeString():''}</p>${x.observed?'<small>Extension '+esc(x.observed.version||'unknown')+' · '+x.observed.messages+' messages found · '+x.observed.pending+' waiting</small>':''}${x.error?'<p>'+esc(x.error)+'</p>':''}</div>`).join('');
};
/* Open a local working copy of a reply. Original messages stay in history. */
document.addEventListener('click', event => {
 const button = event.target.closest('[data-edit-copy]');
 if (!button) return;
 const code = button.parentElement.querySelector('pre code');
 if (!code) return;
 const dialog = document.createElement('dialog');
 dialog.className = 'easy-dialog reply-editor';
 dialog.setAttribute('aria-label', 'Edit a copy');
 dialog.innerHTML = '<h2>Edit a copy</h2><label>Document text<textarea spellcheck="false"></textarea></label><div><button type="button" data-download>Download text</button> <button type="button" data-close>Close</button></div>';
 const editor = dialog.querySelector('textarea');
 editor.value = code.textContent;
 const original = editor.value;
 let saved = original;
 dialog.querySelector('[data-download]').onclick = () => {
  const url = URL.createObjectURL(new Blob([editor.value], {type:'text/plain;charset=utf-8'}));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'jarvis-document.txt';
  link.click();
  saved = editor.value;
  setTimeout(() => URL.revokeObjectURL(url), 30000);
 };
 function closeEditor() {
  if (editor.value === saved || confirm('Close and discard your latest edits?')) dialog.close();
 }
 dialog.oncancel = event => { event.preventDefault(); closeEditor(); };
 dialog.querySelector('[data-close]').onclick = closeEditor;
 dialog.onclose = () => { dialog.remove(); button.focus(); };
 document.body.append(dialog);
 dialog.showModal();
 editor.focus();
});
const fileComposer = $('composer');
function attachFromTransfer(event, transfer) {
 if (!transfer?.files.length) return;
 event.preventDefault();
 if (busy || window.jarvisUploading) {
  toast('Wait for the current request or upload to finish, then add your file.');
  return;
 }
 upload.files = transfer.files;
 upload.onchange();
}
fileComposer.addEventListener('dragover', event => {
 if (Array.from(event.dataTransfer.types).includes('Files')) {
  event.preventDefault();
  event.dataTransfer.dropEffect = 'copy';
 }
});
fileComposer.addEventListener('drop', event => attachFromTransfer(event, event.dataTransfer));
fileComposer.addEventListener('paste', event => attachFromTransfer(event, event.clipboardData));
