/* HORIZON: projected 3D geometry and local, inspectable reliability tools. */
(()=>{
 const reduced = matchMedia('(prefers-reduced-motion: reduce)');
 function appearance() {
  document.body.classList.toggle('quiet', localStorage.getItem('jcc-appearance') === 'quiet');
  document.body.classList.toggle('large-text', localStorage.getItem('jcc-text-size') === 'large');
 }
 function startScene() {
  document.body.classList.toggle('orb-still', document.hidden || reduced.matches ||
   window.jarvisLowPower || localStorage.getItem('jcc-motion') === 'off');
 }
 function mountHero() {
  const host = $('messages').querySelector('.welcome');
  if (!host) {
   document.body.classList.remove('home-expanded');
   return;
  }
  if (host.querySelector('.orb-scene')) return;
  const scene = document.createElement('div');
  scene.className = 'orb-scene';
  scene.setAttribute('aria-hidden','true');
  scene.innerHTML = '<div class="orb-heart"></div><div class="orb-ribbon"></div><div class="orb-ribbon"></div><div class="orb-ribbon"></div>';
  host.prepend(scene);
 }
 appearance();
 startScene();
 mountHero();
 new MutationObserver(mountHero).observe($('messages'), {childList:true});
 document.addEventListener('visibilitychange',startScene);
 window.addEventListener('resize',startScene);
 reduced.addEventListener('change',startScene);

 // System details become a deliberate drawer, leaving space for the work.
 const system=document.createElement('button');system.className='plain';system.textContent='◈ System';system.setAttribute('aria-expanded','false');system.setAttribute('aria-controls','details');$('info').before(system);
 document.querySelector('.topbar>div').append($('project-pill'));
 const shade=document.createElement('div');shade.className='close-drawer-shade';document.body.append(shade);
 const closeSystem=document.createElement('button');closeSystem.id='close-details';closeSystem.className='plain';closeSystem.type='button';closeSystem.textContent='Close';closeSystem.setAttribute('aria-label','Close system status');$('close-details').replaceWith(closeSystem);
 function drawer(open){$('details').classList.toggle('open',open);shade.classList.toggle('open',open);system.setAttribute('aria-expanded',String(open));$('sidebar').inert=open;document.querySelector('.center').inert=open;if(open){$('details').setAttribute('role','dialog');$('details').setAttribute('aria-modal','true');$('details').setAttribute('aria-label','System status');$('close-details').focus()}else{$('details').removeAttribute('role');$('details').removeAttribute('aria-modal');system.focus()}}
 system.onclick=()=>drawer(!$('details').classList.contains('open'));shade.onclick=()=>drawer(false);$('close-details').onclick=()=>drawer(false);document.addEventListener('keydown',e=>{if(e.key==='Escape'&&$('details').classList.contains('open'))drawer(false)});
 document.addEventListener('keydown',e=>{if(e.key!=='Tab'||!$('details').classList.contains('open'))return;const items=[...$('details').querySelectorAll('button,a,input,select,[tabindex="0"]')].filter(x=>!x.disabled&&x.offsetParent!==null);if(!items.length)return;if(e.shiftKey&&document.activeElement===items[0]){e.preventDefault();items.at(-1).focus()}else if(!e.shiftKey&&document.activeElement===items.at(-1)){e.preventDefault();items[0].focus()}});
 const coreState=document.createElement('span');coreState.className='core-state';coreState.innerHTML='<i></i><span id="horizon-core-state">CONNECTING</span>';$('chat-caption').after(coreState);

 // Preview uses the same context composer as execution and never sends a job.
 const contextButton=document.createElement('button');contextButton.type='button';contextButton.className='attach-button';contextButton.textContent='◫ Context';contextButton.title='Inspect the memory, history and attachments for this draft';optionRow.append(contextButton);
 const inspector=document.createElement('dialog');inspector.className='horizon-dialog';inspector.setAttribute('aria-labelledby','context-title');inspector.innerHTML='<div class="tool-heading"><h2 id="context-title">Context inspector</h2><button class="plain" id="context-close">Close</button></div><div id="context-result"></div>';document.body.append(inspector);$('context-close').onclick=()=>inspector.close();
 contextButton.onclick=async()=>{
  contextButton.disabled=true;
  try{
   const d=await api('/api/context/inspect',{id:current||'',text:$('message').value.trim(),project:scope()||null,files:window.jarvisFiles||[],uploads:window.pendingUploads||[],use_browser:$('attach-page')?.checked||false});
   $('context-result').innerHTML='<div class="context-stats"><div class="stat-tile"><strong>'+d.characters.toLocaleString()+'</strong><span>context characters</span></div><div class="stat-tile"><strong>~'+d.estimated_tokens.toLocaleString()+'</strong><span>estimated context tokens</span></div><div class="stat-tile"><strong>'+d.budget.toLocaleString()+'</strong><span>character budget</span></div></div><div class="context-budget"><i style="width:'+Math.min(100,d.characters/d.budget*100)+'%"></i></div><p class="assistant-muted">'+esc(d.scope)+'</p><div class="context-sources">'+d.sources.map(s=>'<div class="context-source"><b>'+esc(s.name)+'</b><p>'+esc(s.reason)+'</p></div>').join('')+'</div><details><summary>Read the exact prepared context</summary><pre id="context-text" class="context-preview"></pre></details>';
   $('context-text').textContent=d.text||'No additional context selected.';inspector.showModal();
  }catch(e){toast(e.message)}finally{contextButton.disabled=false}
 };

 // A compact quality-first view of real results, without invented savings.
 toolBar.querySelector('span').insertAdjacentHTML('beforebegin','<button data-insights="true">◴ Efficiency</button>');
 tools.insertAdjacentHTML('beforeend','<div id="tool-insights" class="tool-content hidden"><div class="tool-heading"><div><h2>Efficiency</h2><p>Measured work. Clear evidence. No assumed savings.</p></div><button class="plain" id="insights-refresh">Refresh</button></div><div id="insights-result"></div></div>');
 async function showInsights(){
  activeTool='insights';$('messages').classList.add('hidden');$('composer').closest('.composer-wrap').classList.add('hidden');$('tool-view').classList.remove('hidden');document.querySelectorAll('[data-workbench]').forEach(b=>b.classList.remove('active'));document.querySelector('[data-insights]').classList.add('active');for(const id of ['terminal','browser','files','activity'])$('tool-'+id).classList.add('hidden');$('tool-insights').classList.remove('hidden');
  try{
   const d=await api('/api/insights'),totals=d.totals;
   $('insights-result').innerHTML='<div class="insight-stats"><div class="stat-tile"><strong>'+totals.tasks+'</strong><span>tasks in the last 30 days</span></div><div class="stat-tile"><strong>'+totals.verified+'</strong><span>checked or positively rated successes</span></div><div class="stat-tile"><strong>'+totals.fully_measured+'</strong><span>jobs with complete input measurements</span></div></div><p class="assistant-muted">'+esc(d.scope)+'</p><h3>Like-for-like weekly comparison</h3><div class="insight-table"><table><thead><tr><th>Task / size</th><th>Model / effort</th><th>Verified this week</th><th>Median time</th><th>Median uncached input</th><th>Previous week</th></tr></thead><tbody>'+d.groups.map(g=>'<tr><td>'+esc(g.family)+'<br><span class="assistant-muted">'+esc(g.level)+'</span></td><td>'+esc(g.model)+'<br>'+esc(g.effort)+'</td><td>'+g.current.verified+' / '+g.current.tasks+'<div class="insight-bar"><i style="width:'+(g.current.tasks?g.current.verified/g.current.tasks*100:0)+'%"></i></div></td><td>'+(g.current.median_seconds==null?'unavailable':Math.round(g.current.median_seconds)+'s')+'</td><td>'+(g.current.median_uncached==null?'unavailable':Math.round(g.current.median_uncached).toLocaleString())+'</td><td>'+(g.uncached_change_percent==null?'More evidence needed':(g.uncached_change_percent>0?'+':'')+g.uncached_change_percent+'% uncached input')+'</td></tr>').join('')+'</tbody></table></div>'+(!d.groups.length?'<p class="assistant-empty">Your next jobs will build this view. Older unmeasured jobs are not assigned estimated usage.</p>':'');
  }catch(e){$('insights-result').textContent=e.message}
 }
 document.addEventListener('click',e=>{if(e.target.closest('[data-insights]'))showInsights();if(e.target.closest('[data-workbench]')){$('tool-insights').classList.add('hidden');document.querySelector('[data-insights]').classList.remove('active');startScene()}});$('insights-refresh').onclick=showInsights;

 const oldRender=window.renderEfficiencyStatus;window.renderEfficiencyStatus=d=>{
  oldRender?.(d);const running=(d.jobs||[]).filter(j=>j.status==='running').length;
  const label=running?'WORKING · '+running+' JOB'+(running===1?'':'S'):d.core==='thinking'?'PREPARING YOUR TASK':'READY';
  $('horizon-core-state').textContent=label;if($('reactor-state'))$('reactor-state').textContent=running?'WORK IN PROGRESS · CHECK ACTIVITY':'READY FOR YOUR NEXT IDEA';
 };

 const oldSettings=openSettings;openSettings=function(section='memory'){
  oldSettings(section);if(!state)return;
  if(section==='app'&&!$('horizon-appearance')){
   $('settings-body').insertAdjacentHTML('afterbegin','<div class="settings-box" id="horizon-appearance"><h3>Your command center</h3><p>Holographic depth, readable surfaces. Decorations stay separate from your work.</p><div class="horizon-options"><label>Appearance <select id="horizon-theme" aria-label="Appearance"><option value="horizon">Horizon · holographic</option><option value="quiet">Quiet · less decoration</option></select></label><label>Motion <select id="horizon-motion" aria-label="Motion"><option value="system">Respect system preference</option><option value="off">Off</option></select></label><label>Text size <select id="horizon-text" aria-label="Text size"><option value="standard">Standard</option><option value="large">Larger</option></select></label></div></div>');
   for(const [id,key,def]of [['horizon-theme','jcc-appearance','horizon'],['horizon-motion','jcc-motion','system'],['horizon-text','jcc-text-size','standard']]){$(id).value=localStorage.getItem(key)||def;$(id).onchange=()=>{localStorage.setItem(key,$(id).value);appearance();startScene()}}
  }
  if(section==='memory'&&!$('memory-conflict-list')){
   $('settings-body').insertAdjacentHTML('beforeend','<div class="settings-box"><h3>Project decision conflicts</h3><p>Different values in structured Decisions sections are flagged for review. Choose a source to guide future context without changing either note.</p><p class="assistant-muted">Run “Review memory now” to refresh conflicts. A changed or private source stops being used automatically.</p><div id="memory-conflict-list">Loading local evidence…</div><button class="plain" id="conflicts-refresh">Refresh decisions</button></div>');
   $('conflicts-refresh').onclick=loadConflicts;loadConflicts();
  }
 };
 async function loadConflicts(){
  if(!$('memory-conflict-list'))return;
  try{
   const d=await api('/api/memory/conflicts');$('memory-conflict-list').innerHTML=d.conflicts.map(c=>'<div class="conflict-card"><b>'+esc(c.scope)+' · '+esc(c.key)+'</b><p class="assistant-muted">'+(c.selected?'Owner-selected source: '+esc(c.selected.source):'Different recorded values; review the sources.')+'</p>'+c.sources.map((s,i)=>'<p><a href="'+esc(obsidian(s.source))+'">'+esc(s.source)+' ↗</a><br>'+esc(s.value)+'</p><button class="plain" data-conflict="'+esc(c.id)+'" data-source-index="'+i+'">'+(c.selected?.source===s.source?'✓ Selected source':'Use this source')+'</button>').join('')+'</div>').join('')||'<p>No structured decision conflicts found in the last audit. Unstructured prose is not automatically judged.</p>';
   $('memory-conflict-list').querySelectorAll('[data-conflict]').forEach(b=>b.onclick=async()=>{const c=d.conflicts.find(x=>x.id===b.dataset.conflict),s=c.sources[Number(b.dataset.sourceIndex)];try{await api('/api/memory/resolve',{id:c.id,source:s.source,version:s.version});await loadConflicts();toast('Decision source saved. Original notes are unchanged.')}catch(e){toast(e.message)}});
  }catch(e){if($('memory-conflict-list'))$('memory-conflict-list').textContent=e.message}
 }
 if(state)window.renderEfficiencyStatus(state);
})();
