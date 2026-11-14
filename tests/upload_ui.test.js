// Exercise the real upload handler with fake files and a local API stub.
const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../jcc/static/workbench.js'),'utf8');
const handler=source.slice(source.indexOf('upload.onchange=async()=>'),source.indexOf('\ndocument.addEventListener',source.indexOf('upload.onchange=async()=>')));
function setup(){
 const button={textContent:'Add file or photo',disabled:false},send={disabled:false},messages=[],calls=[];
 let finish;
 const context={upload:{files:[{name:'notes.txt',size:5,arrayBuffer:async()=>new Uint8Array([104,101,108,108,111]).buffer}],value:'file'},attachButton:button,$:()=>send,current:'chat-a',scope:()=>'',busy:false,window:{pendingUploads:[]},btoa:text=>Buffer.from(text,'binary').toString('base64'),toast:text=>messages.push(text),renderAttachments:()=>{},api:async(url,body)=>{calls.push([url,body]);return new Promise(resolve=>{finish=resolve})}};
 vm.createContext(context);vm.runInContext(handler,context);return {context,button,send,messages,calls,resolve:()=>finish({name:'notes.txt',text:'hello',notes:[],truncated:false})};
}
test('a late upload cannot attach itself to another conversation',async()=>{const s=setup();const pending=s.context.upload.onchange();await new Promise(setImmediate);assert.equal(s.send.disabled,true);s.context.current='chat-b';s.resolve();await pending;assert.equal(s.context.window.pendingUploads.length,0);assert.match(s.messages[0],/changed chats/);assert.equal(s.send.disabled,false)});
test('normal extraction attaches only after it finishes and restores controls',async()=>{const s=setup();const pending=s.context.upload.onchange();await new Promise(setImmediate);assert.equal(s.context.window.jarvisUploading,true);assert.match(s.button.textContent,/Preparing/);s.resolve();await pending;assert.equal(s.context.window.pendingUploads[0].text,'hello');assert.equal(s.context.window.jarvisUploading,false);assert.equal(s.button.textContent,'Add file or photo');assert.equal(s.calls[0][0],'/api/attachments/extract')});
test('oversized files are explained without an API call',async()=>{const s=setup();s.context.upload.files[0].size=1000001;await s.context.upload.onchange();assert.equal(s.calls.length,0);assert.match(s.messages[0],/1 MB/);assert.equal(s.send.disabled,false)});
