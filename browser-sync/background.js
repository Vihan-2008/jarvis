/* Credentials stay in this extension, never in a website's page context. */
const ENDPOINT='http://127.0.0.1:8765/api/capture';
let flushing=false;
const probes={};
async function reportProbe(diagnostic){
 const source=diagnostic.source;if(Date.now()-(probes[source]||0)<30000)return;probes[source]=Date.now();
 const d=await chrome.storage.local.get(['pairing','error','pending']);if(!d.pairing)return;
 try{await fetch('http://127.0.0.1:8765/api/sync/probe',{method:'POST',credentials:'omit',headers:{'Content-Type':'application/json','X-JCC-Sync':d.pairing},body:JSON.stringify({...diagnostic,error:d.error||'',pending:Object.keys(d.pending||{}).length,version:chrome.runtime.getManifest().version})})}catch(e){}
}

async function flush(){
  if(flushing)return;flushing=true;
  try{
    const {pairing,pending={}}=await chrome.storage.local.get(['pairing','pending']);
    if(!pairing)return;
    for(const [id,payload] of Object.entries(pending)){
      try{
        const r=await fetch(ENDPOINT,{method:'POST',credentials:'omit',headers:{'Content-Type':'application/json','X-JCC-Sync':pairing},body:JSON.stringify(payload)});
        if(r.ok){delete pending[id];await chrome.storage.local.set({lastSync:Date.now(),lastSource:payload.source,error:''})}
        else{const d=await r.json();await chrome.storage.local.set({error:d.error||'Sync rejected'});break}
      }catch(e){await chrome.storage.local.set({error:'JARVIS is offline. Captures will retry automatically.'});break}
    }
    await chrome.storage.local.set({pending});
  }finally{flushing=false}
}
let serial=Promise.resolve();
chrome.runtime.onMessage.addListener((message,sender,reply)=>{
  if(!['capture','probe'].includes(message.type))return;
  const url=sender.tab?.url||'';
  if(!/^https:\/\/(chatgpt\.com|claude\.ai)\//.test(url)){reply({ok:false});return}
  serial=serial.then(async()=>{
    if(message.type==='probe'){
      const {observed={}}=await chrome.storage.local.get('observed');
      observed[message.diagnostic.source]=message.diagnostic;
      await chrome.storage.local.set({observed});await reportProbe(message.diagnostic);return;
    }
    const {pending={}}=await chrome.storage.local.get('pending');
    if(JSON.stringify(message.payload).length>3000000)return;
    pending[message.payload.url]=message.payload;
    const keys=Object.keys(pending);while(keys.length>20)delete pending[keys.shift()];
    await chrome.storage.local.set({pending});await flush();
  }).catch(e=>chrome.storage.local.set({error:String(e)}));
  serial.then(()=>reply({ok:true}));return true;
});
chrome.alarms.create('retry',{periodInMinutes:1});
chrome.alarms.onAlarm.addListener(()=>{serial=serial.then(flush)});
chrome.action.onClicked.addListener(()=>chrome.runtime.openOptionsPage());
chrome.runtime.onInstalled.addListener(()=>chrome.runtime.openOptionsPage());
