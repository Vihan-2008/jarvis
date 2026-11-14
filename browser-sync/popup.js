const status=document.getElementById('status');
document.getElementById('settings').onclick=()=>chrome.runtime.openOptionsPage();
document.getElementById('share').onclick=async()=>{
 try{
  const {pairing}=await chrome.storage.local.get('pairing');if(!pairing){status.textContent='Pair JARVIS once in Sync settings first.';return}
  const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
  if(!/^https?:\/\//.test(tab?.url||'')){status.textContent='Open a web page first.';return}
  const results=await chrome.scripting.executeScript({target:{tabId:tab.id},func:()=>({url:location.origin+location.pathname,title:document.title,text:(document.querySelector('main')||document.body).innerText.slice(0,180000)})});
  const response=await fetch('http://127.0.0.1:8765/api/browser/share',{method:'POST',credentials:'omit',headers:{'Content-Type':'application/json','X-JCC-Sync':pairing},body:JSON.stringify(results[0].result)});
  const data=await response.json();if(!response.ok)throw Error(data.error||'Page could not be shared.');status.textContent='Shared. Open the Browser tab in JARVIS.';
 }catch(e){status.textContent=e.message||String(e)}
};
(async()=>{const d=await chrome.storage.local.get(['lastSync','lastSource','error']);status.textContent=d.error||(d.lastSync?'Last sync: '+(d.lastSource||'')+' · '+new Date(d.lastSync).toLocaleTimeString():'Open Sync settings to pair once.')})();

document.getElementById('capture').onclick=async()=>{try{const [tab]=await chrome.tabs.query({active:true,currentWindow:true});if(!/^https:\/\/(chatgpt\.com|claude\.ai)\//.test(tab?.url||''))throw Error('Open a saved ChatGPT or Claude conversation first.');await chrome.scripting.executeScript({target:{tabId:tab.id},files:['content.js']});status.textContent='Capture requested. Check Sync settings for the saved-message status.';}catch(e){status.textContent=e.message}};
