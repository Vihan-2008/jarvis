/* Local activity, owner feedback and conservative routing controls. */
(()=>{
const style=document.createElement('style');style.textContent=`
.activity-grid{display:grid;grid-template-columns:260px minmax(0,1fr);gap:20px}.activity-list{display:flex;flex-direction:column;gap:8px;max-height:62vh;overflow:auto}.activity-row{text-align:left;padding:13px;border:1px solid #224859;border-radius:10px;background:#0a1e2e;color:#c6e6ef;cursor:pointer}.activity-row.selected{border-color:#4bd8e7;background:#103446}.activity-row strong,.activity-row small{display:block;overflow-wrap:anywhere}.activity-row small{margin-top:7px;color:#88adb9}.activity-detail{min-width:0}.activity-detail pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:340px;overflow:auto;background:#06131f;padding:14px;border-radius:9px;color:#b7e5ec}.activity-detail ol{padding-left:22px;font-size:13px;line-height:1.8}.assistant-actions{display:flex;gap:9px;flex-wrap:wrap;margin:14px 0}.assistant-check{display:block;margin:15px 0}.assistant-check input{margin-right:9px}.learning-table{overflow:auto;font-size:12px}.learning-table td,.learning-table th{padding:8px;text-align:left;border-bottom:1px solid #23414f}.learning-table table{width:100%}.assistant-muted{color:#8eacb9;font-size:12px;line-height:1.6}.assistant-empty{padding:30px;text-align:center;color:#8eacb9}.assistant-notice{border-left:2px solid #51ceda;padding:10px 14px;margin:12px 0;background:#0c2637}.assistant-path{width:100%;padding:12px;background:#081b29;border:1px solid #2a5262;border-radius:8px;color:#d4eef5}.assistant-updates{max-width:620px;width:90%;background:#091b2a;color:#d4eef5;border:1px solid #387687;border-radius:16px;padding:24px}.assistant-updates::backdrop{background:#020913b8}@media(max-width:760px){.activity-grid{grid-template-columns:1fr}.activity-list{max-height:180px}}`;
document.head.append(style);
toolBar.querySelector('span').insertAdjacentHTML('beforebegin','<button data-workbench="activity">◷ Activity</button>');
tools.insertAdjacentHTML('beforeend','<div id="tool-activity" class="tool-content hidden"><div class="tool-heading"><div><h2>Activity</h2><p>Follow work, review changes and teach JARVIS what worked.</p></div><button id="activity-refresh" class="plain">Refresh</button></div><div class="activity-grid"><div id="activity-list" class="activity-list"></div><section id="activity-detail" class="activity-detail"></section></div></div>');
let selected='',detailSignature='',detailBusy=false,lastActivity='';
const statusLabel=s=>String(s||'queued').replaceAll('_',' ');
function renderList(){
 const jobs=state?.activity||[],sig=JSON.stringify([selected,jobs]);if(sig===lastActivity)return;lastActivity=sig;
 $('activity-list').innerHTML=jobs.map(j=>`<button class="activity-row ${selected===j.id?'selected':''}" data-review-id="${esc(j.id||'')}"><strong>${esc(j.task||'Project job')}</strong><small>${esc(statusLabel(j.status))} · ${esc(j.agent||'Auto')}${j.model?' / '+esc(j.model):''}</small><small>${esc(j.latest_event?.message||'')}</small></button>`).join('')||'<p class="assistant-empty">No jobs yet. Start a task in a project chat.</p>';
}
async function loadDetail(force=false){
 if(!selected||detailBusy)return;
 const job=(state.activity||[]).find(x=>x.id===selected),sig=JSON.stringify([selected,job]);
 if(!force&&sig===detailSignature)return;
 detailBusy=true;const requested=selected;
 try{
  const d=await api('/api/job/details?id='+encodeURIComponent(requested));if(requested!==selected)return;detailSignature=sig;
  const m=d.metrics,feedback=state.learning?.feedback?.[d.id];
  $('activity-detail').innerHTML=`<h3>${esc(d.task||'Job details')}</h3><p>${esc(statusLabel(d.status))}</p><div class="assistant-notice">${esc(d.reason||'Configured model route; no learned decision was recorded for this older job.')}</div><div class="assistant-actions"><a href="${esc(obsidian('Jobs/'+d.id))}">Open job note ↗</a>${jobButtons({id:d.id,status:d.status})}${d.can_merge?'<button class="primary" id="review-merge">Apply these changes</button>':''}${d.can_undo?'<button class="plain" id="review-undo">Undo last change</button>':''}</div><ol>${(d.events||[]).map(e=>'<li><span class="assistant-muted">'+new Date(e.at*1000).toLocaleTimeString()+'</span> · <b>'+esc(statusLabel(e.stage))+'</b> — '+esc(e.message)+'</li>').join('')||'<li>No activity log for this older job.</li>'}</ol>${m?'<p class="assistant-muted">Automatic checks: '+(m.checks_passed===true?'passed':m.checks_passed===false?'not passed':'not measured')+' · '+esc(m.runs?.length||0)+' attempts</p><div class="assistant-actions"><button class="plain" data-job-rating="helpful">'+(feedback==='helpful'?'✓ ':'')+'Helpful</button><button class="plain" data-job-rating="needs_work">'+(feedback==='needs_work'?'✓ ':'')+'Needs work</button></div>':''}${window.deliveryEvidence?window.deliveryEvidence(d):''}<h3>What changed</h3><p class="assistant-muted">${esc((d.files||[]).join(' · ')||'No previewable file changes. Discussion jobs do not change project files.')}</p><pre id="activity-diff"></pre>`;
  $('activity-diff').textContent=d.diff||'No diff available.';
  if($('review-merge'))$('review-merge').onclick=()=>reviewAction('merge',d);
  if($('review-undo'))$('review-undo').onclick=()=>reviewAction('undo',d);
  document.querySelectorAll('[data-job-rating]').forEach(b=>b.onclick=async()=>{try{await api('/api/feedback',{id:d.id,rating:b.dataset.jobRating});await refresh();await loadDetail(true);toast('Feedback saved. JARVIS will use it as routing evidence.')}catch(e){toast(e.message)}});
 }catch(e){$('activity-detail').textContent=e.message}finally{detailBusy=false}
}
async function reviewAction(action,d){
 const buttons=$('activity-detail').querySelectorAll('button');buttons.forEach(b=>b.disabled=true);
 try{toast(action==='undo'?'Checking a separate undo branch…':'Rechecking the reviewed changes…');await api('/api/job/review',{id:d.id,action,revision:d.revision});await refresh();await loadDetail(true);toast(action==='undo'?'Undo passed checks and was merged.':'Reviewed changes passed checks and were merged.')}catch(e){toast(e.message)}finally{buttons.forEach(b=>b.disabled=false)}
}
window.refreshActivity=async()=>{if(!selected)selected=state?.activity?.[0]?.id||'';renderList();await loadDetail(true)};
$('activity-refresh').onclick=()=>window.refreshActivity();
document.addEventListener('click',e=>{const b=e.target.closest('[data-review-id]');if(b){selected=b.dataset.reviewId;renderList();loadDetail(true)}});

// Notifications persist locally even if Windows suppresses a balloon.
const updates=document.createElement('button');updates.className='plain';updates.id='assistant-updates-button';updates.textContent='◷ Updates';$('info').before(updates);
const dialog=document.createElement('dialog');dialog.className='assistant-updates';dialog.innerHTML='<div class="tool-heading"><h2>Updates</h2><button class="plain" id="updates-close">Close</button></div><div id="updates-list"></div>';document.body.append(dialog);
$('updates-close').onclick=()=>dialog.close();
function renderUpdates(){
 const rows=state?.alerts||[],read=Number(localStorage.getItem('jcc-alert-read')||0),unread=rows.filter(x=>x.at>read).length;
 updates.textContent='◷ Updates'+(unread?' ('+unread+')':'');
 $('updates-list').innerHTML=rows.map(x=>'<div class="assistant-notice"><span class="assistant-muted">'+new Date(x.at*1000).toLocaleString()+'</span><p>'+esc(x.message)+'</p><button class="plain" data-review-id="'+esc(x.id)+'">View activity</button></div>').join('')||'<p>No completion, review or failure alerts yet.</p>';
}
updates.onclick=()=>{renderUpdates();localStorage.setItem('jcc-alert-read',String(Date.now()/1000));dialog.showModal();renderUpdates()};
dialog.addEventListener('click',async e=>{const b=e.target.closest('[data-review-id]');if(b){dialog.close();selected=b.dataset.reviewId;await showTool('activity')}});
let alertsLoaded=false,seen=new Set();
function renderAssistant(d){
 renderUpdates();const rows=d.alerts||[];
 if(alertsLoaded){const fresh=rows.find(x=>!seen.has(x.id+':'+x.status));if(fresh)toast(fresh.message+' Open Activity for details.')}
 seen=new Set(rows.map(x=>x.id+':'+x.status));alertsLoaded=true;
 if(activeTool==='activity'){if(!selected)selected=d.activity?.[0]?.id||'';renderList();loadDetail()}
 renderMaintenance();
}
const oldRender=window.renderEfficiencyStatus;window.renderEfficiencyStatus=d=>{if(oldRender)oldRender(d);renderAssistant(d)};
function heartbeat(){if(document.visibilityState==='visible'&&document.hasFocus())api('/api/ui/activity',{focused:true}).catch(()=>{})}
setInterval(heartbeat,5000);window.addEventListener('focus',heartbeat);heartbeat();

const mountRouting=window.mountRoutingSettings;
window.mountRoutingSettings=()=>{
 mountRouting?.();if($('assistant-preferences'))return;
 const p=state.learning?.settings||{},box=document.createElement('div');box.className='settings-box';box.id='assistant-preferences';
 box.innerHTML='<h3>Learn from results</h3><p>JARVIS learns which available model fits each task family using checked results, your ratings, retries, time and reported uncached tokens. It does not spend usage on experiments.</p><form id="assistant-settings-form">'+[['adaptive_routing','Learn automatic model routing'],['review_before_merge','Review every coding change before merging']].map(([key,label])=>'<label class="assistant-check"><input type="checkbox" id="pref-'+key+'" '+(p[key]?'checked':'')+'>'+label+'</label>').join('')+'<button class="primary">Save preferences</button></form><p class="assistant-muted">Manual model and task-size preferences take priority. A candidate needs at least five recent qualifying tasks and three checked or positively rated successes. Critical and large tasks retain their configured strong route. Missing measurements are not estimated.</p><div id="learning-evidence"></div>';
 $('settings-body').append(box);
 const stats=state.learning?.evidence?.stats||[];
 $('learning-evidence').innerHTML=stats.length?'<div class="learning-table"><table><thead><tr><th>Task family</th><th>Model</th><th>Evidence</th><th>Quality</th><th>Median time</th><th>Uncached input</th></tr></thead><tbody>'+stats.slice(0,25).map(x=>`<tr><td>${esc(x.family)} · ${esc(x.level)}</td><td>${esc(x.provider)}/${esc(x.model)}</td><td>${x.tasks} tasks · ${x.eligible?'eligible':'learning'}</td><td>${Math.round(x.success_rate*100)}%</td><td>${Math.round(x.median_seconds)}s</td><td>${x.median_uncached_tokens==null?'unavailable':Math.round(x.median_uncached_tokens).toLocaleString()}</td></tr>`).join('')+'</tbody></table></div>':'<p class="assistant-notice">Building evidence. Configured routes stay active until enough checked work or owner feedback exists.</p>';
 $('assistant-settings-form').onsubmit=async e=>{e.preventDefault();try{const settings={};for(const key of ['adaptive_routing','review_before_merge'])settings[key]=$('pref-'+key).checked;await api('/api/assistant/settings',{settings});await refresh();toast('Assistant preferences saved.')}catch(e){toast(e.message)}};
};

const mountMemory=window.mountMemorySettings;
window.mountMemorySettings=()=>{
 mountMemory?.();const box=document.createElement('div');box.className='settings-box';box.innerHTML='<h3>Memory & backup health</h3><p>Daily local checks suggest duplicate-note, overdue-review and broken-link fixes. Weekly recovery checks download a fresh backup and verify restored file bytes in a temporary folder.</p><p id="memory-audit-summary"></p><p id="restore-summary"></p><div class="assistant-actions"><button class="plain" id="memory-audit-run">Review memory now</button><button class="plain" id="restore-run">Verify backup recovery</button><a id="memory-audit-note">Open memory suggestions ↗</a></div><p class="assistant-muted">Original notes and archives are preserved. Recovery checks do not run code from the backup.</p>';$('settings-body').append(box);$('memory-audit-note').href=obsidian('System/Memory audit');
 for(const [id,action]of [['memory-audit-run','audit'],['restore-run','restore']])$(id).onclick=async()=>{try{$(id).disabled=true;await api('/api/maintenance',{action});toast('Check started. Results will appear here.')}catch(e){toast(e.message)}finally{$(id).disabled=false}};
 renderMaintenance();
};
function renderMaintenance(){
 const m=state?.maintenance||{},a=m['memory-audit']||{},r=m['restore-check']||{};
 if($('memory-audit-summary'))$('memory-audit-summary').textContent='Memory: '+(a.status||'waiting for first daily check')+(a.at?' · '+new Date(a.at*1000).toLocaleString():'')+(a.notes_checked!=null?' · '+a.notes_checked+' notes checked':'');
 if($('restore-summary'))$('restore-summary').textContent='Recovery: '+(r.status||'waiting for first weekly check')+(r.at?' · '+new Date(r.at*1000).toLocaleString():'')+(r.notes_restored?' · '+r.notes_restored+' notes restored and verified':'')+(r.error?' · '+r.error:'');
}

// Existing projects are inspected without running their scripts or changing files.
const originalSettings=openSettings;
openSettings=function(section='memory'){
 originalSettings(section);if(!state||section==='memory'||section==='usage'||$('connect-project-button'))return;
 $('settings-new-project').insertAdjacentHTML('afterend',' <button class="plain" id="connect-project-button">Connect existing project</button>');
 $('connect-project-button').onclick=()=>{$('settings-dialog').close();onboard.showModal()};
};
const onboard=document.createElement('dialog');onboard.className='assistant-updates';onboard.innerHTML='<div class="tool-heading"><h2>Connect a project</h2><button class="plain" id="onboard-close">Close</button></div><p>Choose an existing Git project. JARVIS detects its language, tools and checks before it can code there.</p><form id="onboard-form"><label for="onboard-path">Project folder</label><input id="onboard-path" class="assistant-path" required placeholder="C:\\Users\\you\\Projects\\my-project"><div class="assistant-actions"><button class="primary" id="onboard-inspect">Inspect folder</button><button type="button" class="plain hidden" id="onboard-connect">Connect project</button></div></form><div id="onboard-result" class="assistant-muted"></div>';document.body.append(onboard);
const pathField = $('onboard-path');
const resultText = $('onboard-result');
const connectButton = $('onboard-connect');
let inspected = null;
let revision = 0;
function resetInspection() {
 revision++;
 inspected = null;
 resultText.textContent = '';
 connectButton.classList.add('hidden');
}
pathField.oninput = resetInspection;
$('onboard-close').onclick = () => onboard.close();
onboard.addEventListener('close', resetInspection);
const browseButton = document.createElement('button');
browseButton.type = 'button';
browseButton.className = 'plain';
browseButton.textContent = 'Browse folders…';
pathField.after(browseButton);
browseButton.onclick = async () => {
 browseButton.disabled = true;
 const started = revision;
 try {
  const selection = await api('/api/project/browse',{});
  if (selection.path && onboard.open && started === revision) {
   pathField.value = selection.path;
   resetInspection();
   $('onboard-form').requestSubmit();
  }
 } catch (error) { resultText.textContent = error.message; }
 finally { browseButton.disabled = false; }
};
$('onboard-form').onsubmit = async event => {
 event.preventDefault();
 resetInspection();
 const started = revision;
 try {
  const info = await api('/api/project/inspect',{path:pathField.value.trim()});
  if (revision !== started) return;
  inspected = info;
  const available = info.connected_key || info.ready;
  resultText.textContent = available
   ? info.name + ' · ' + info.stack.join(', ') + (info.connected_key ? ' · Already connected' : ' · Changes will wait for your review.')
   : 'To work here, choose the top folder of a Git project on a named branch with a supported test command.';
  connectButton.textContent = info.connected_key ? 'Start project chat' : 'Connect and start chat';
  connectButton.classList.toggle('hidden', !available);
 } catch (error) { if (revision === started) resultText.textContent = error.message; }
};
connectButton.onclick = async () => {
 const info = inspected;
 if (!info) return;
 connectButton.disabled = true;
 try {
  if (!info.connected_key) {
   const connected = await api('/api/project/connect',{path:info.path});
   info.connected_key = connected.key;
  }
  await refresh();
  await showTool('chat');
  await makeChat(info.connected_key);
  onboard.close();
  document.body.classList.add('workspace-open');
  $('message').focus();
 } catch (error) { resultText.textContent = error.message; }
 finally { connectButton.disabled = false; }
};
const openFolder = document.createElement('button');
openFolder.type = 'button';
openFolder.className = 'plain';
openFolder.textContent = 'Open folder…';
openFolder.onclick = () => {
 resetInspection();
 pathField.value = '';
 onboard.showModal();
 browseButton.click();
};
$('new-project').closest('section').prepend(openFolder);
const composerFolder = openFolder.cloneNode(true);
composerFolder.onclick = openFolder.onclick;
document.querySelector('.composer-bottom').append(composerFolder);

if(state)renderAssistant(state);
})();
