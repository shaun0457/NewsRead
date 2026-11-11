const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

function setup(stickers) {
  function element() { return { hidden:false, dataset:{}, attributes:{}, style:{}, children:[], listeners:{}, classList:{toggle(){},contains(){return false}}, addEventListener(type, fn){this.listeners[type]=fn;}, setAttribute(key,value){this.attributes[key]=value;if(key.startsWith('data-'))this.dataset[key.slice(5)]=value;}, getAttribute(key){return this.attributes[key]}, append(node){this.children.push(node);}, remove(){this.removed=true}, querySelector(){return null}, querySelectorAll(){return []}, getScreenCTM(){return {a:1,b:0,c:0,d:1,e:100,f:100}}, getBoundingClientRect(){return {left:100,top:100,right:200,bottom:200,width:100,height:100}}, focus(){}, setPointerCapture(){}}; }
  const panel=element(), bar=element(), layer=element(), toggle=element(), stage=element(), ink=element(), block=element();
  panel.hidden=true; ink.getAttribute=()=> 'true';
  block.dataset.id='p1'; block.innerText='paper';
  const elements={stickerPanel:panel,stickerToggle:toggle,stickerTools:bar,inkLayer:layer,stage,inkToggle:ink,'b-p1':block};
  const document={documentElement:{dataset:{theme:'light'}},body:element(),listeners:{},getElementById:id=>elements[id],querySelector(){return null},addEventListener(type,fn){this.listeners[type]=fn;},createElement(){return element()},createElementNS(_ns,name){const e=element();e.kind=name;e.querySelector=selector=>selector==='image'?e.children.find(child=>child.kind==='image'):selector==='[data-sticker-content]'?e.children.find(child=>Object.hasOwn(child.attributes,'data-sticker-content')):null;return e;}};
  layer.querySelectorAll=selector=>selector==='[data-sticker]'?layer.children.filter(x=>x.dataset.sticker):[];
  const box={id:'t0',assetId:'paperread-text-box',anchor:'p1',textHash:'hash',ref:[100,100],x:0,y:0,width:40,height:40,rotation:0,opacity:1,z:1,locked:false,text:'note'};
  const PR={state:{reader:{stickers:stickers || {t0:box}}}, t:s=>s, esc:s=>String(s||''), md:text=>String(text).replace(/\$([^$]+)\$/g,'<span class="katex">$1</span>'), icon:name=>`<svg data-icon="${name}"></svg>`, ls:{get:(_k,d)=>d,set:()=>true}, on(){}, renderInk(){}, toggleInk(){}, hashText:()=> 'hash', recordStickerHistory(){}, commit(op){if(op.op==='sticker')this.state.reader.stickers[op.sticker.id]=op.sticker;}, $$: () => [block], stickerLasso:require('../easyread/web/js/reader/sticker-lasso.js'), stickerGeometry:require('../easyread/web/js/reader/sticker-geometry.js')};
  let themeChanged;
  class MockImage { constructor() { setTimeout(() => { this.naturalWidth = 24; this.naturalHeight = 24; this.onload?.(); }, 0); } }
  const context={window:{PR,innerWidth:1200,innerHeight:800,addEventListener(){}},document,innerWidth:1200,innerHeight:800,Image:MockImage,URL,MutationObserver:class{constructor(callback){themeChanged=callback}observe(){}},DOMParser:class{parseFromString(){return {querySelector(){return null},documentElement:{localName:'svg'},querySelectorAll(){return []}}}},TextDecoder,Uint8Array,atob:s=>Buffer.from(s,'base64').toString('binary'),console};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../easyread/web/js/reader/stickers.js'),'utf8'),context);
  return {PR,panel,bar,layer,toggle,document,themeChanged};
}

test('finishing a lasso returns to direct object selection',()=>{
  const {PR,layer}=setup();
  PR.setLassoMode(true);
  layer.listeners.pointerdown({button:0,pointerId:1,clientX:110,clientY:110,preventDefault(){},stopPropagation(){}});
  layer.listeners.pointermove({pointerId:1,clientX:130,clientY:110});
  layer.listeners.pointermove({pointerId:1,clientX:120,clientY:130});
  layer.listeners.pointerup({pointerId:1});
  assert.equal(PR.lassoMode,false);
  assert.equal(layer.classList.contains('lasso-mode'),false);
});


test('text box selection renders edge lines and handles',()=>{
  const {PR,layer}=setup();
  PR.setStickerMode(true);
  const group={dataset:{sticker:'t0'}};
  layer.listeners.pointerdown({button:0,target:{dataset:{},closest:()=>group},preventDefault(){},stopPropagation(){},pointerId:1,clientX:120,clientY:120});
  layer.children=[];
  PR.renderStickers(layer,{left:0,top:0},{scrollTop:0},'front');
  const handles=layer.children[0].children.filter(c=>c.dataset?.handle).map(c=>c.dataset.handle);
  for (const h of ['n','s','w','e','nw','se','rotate']) assert.ok(handles.includes(h), h);
});

test('old image stickers from before the library was removed are ignored without errors',()=>{
  const image={id:'img1',assetId:'doodle-smiling-book',anchor:'p1',textHash:'hash',ref:[100,100],x:0,y:0,width:40,height:40,rotation:0,opacity:1,z:1,locked:false};
  const custom={id:'img2',assetId:'custom-abc',customData:'data:image/png;base64,AAAA',anchor:'p1',textHash:'hash',ref:[100,100],x:0,y:0,width:40,height:40,rotation:0,opacity:1,z:2,locked:false};
  const box={id:'t0',assetId:'paperread-text-box',anchor:'p1',textHash:'hash',ref:[100,100],x:0,y:0,width:40,height:40,rotation:0,opacity:1,z:3,locked:false,text:'keep'};
  const {PR,layer}=setup({img1:image,img2:custom,t0:box});
  PR.setStickerMode(true);
  assert.doesNotThrow(()=>PR.renderStickers(layer,{left:0,top:0},{scrollTop:0},'front'));
  assert.deepEqual(layer.children.map(g=>g.dataset.sticker),['t0']);
  const group={dataset:{sticker:'img1'}};
  layer.listeners.pointerdown({button:0,target:{dataset:{},closest:()=>group},preventDefault(){},stopPropagation(){},pointerId:1,clientX:120,clientY:120});
  layer.children=[];
  PR.renderStickers(layer,{left:0,top:0},{scrollTop:0},'front');
  assert.equal(layer.children[0].children.some(c=>c.dataset?.handle),false);  // 舊圖片貼紙點不到、不會被選取
  assert.equal(PR.state.reader.stickers.img1.assetId,'doodle-smiling-book');  // 資料保留，不刪
});

test('the sticker library and its shortcut are gone',()=>{
  const {PR}=setup();
  assert.equal(PR.toggleStickerPanel,undefined);
  assert.equal(PR.closeStickerPanel,undefined);
  const html=fs.readFileSync(path.join(__dirname,'../easyread/web/reader.html'),'utf8');
  assert.doesNotMatch(html,/stickerToggle|stickerPanel|sticker-style/);
  const features=fs.readFileSync(path.join(__dirname,'../easyread/web/js/common/features.js'),'utf8');
  assert.doesNotMatch(features,/stickerToggle/);
  assert.match(html,/data-ink-lasso/);  // 套索選取還在
});

test('text box inserts on the ink layer and saves multiline edits and styles',()=>{
  const {PR,layer,document,bar}=setup(); PR.uid=()=> 'text1';
  PR.renderInk=()=>{layer.children=[];PR.renderStickers(layer,{left:0,top:0},{scrollTop:0},'front')};
  PR.insertInkText(150,160);
  assert.equal(PR.state.reader.stickers.text1.assetId,'paperread-text-box');
  const input=document.body.children.at(-1); assert.ok(input);
  input.value='first line\n第二行'; input.listeners.blur();
  assert.equal(PR.state.reader.stickers.text1.text,'first line\n第二行'); assert.equal(input.removed,true);
  bar.listeners.change({target:{dataset:{field:'textColor'},value:'#335577'}});
  bar.listeners.change({target:{dataset:{field:'textSize'},value:'28'}});
  assert.equal(PR.state.reader.stickers.text1.textColor,'#335577'); assert.equal(PR.state.reader.stickers.text1.textSize,28);
  assert.match(bar.innerHTML,/data-field="textSize" type="number"/);
  assert.doesNotMatch(bar.innerHTML,/data-field="textSize" type="range"/);
  const click=action=>bar.listeners.click({target:{closest:()=>({dataset:{action}})}});
  click('text-size-up'); assert.equal(PR.state.reader.stickers.text1.textSize,29);
  click('text-size-down'); assert.equal(PR.state.reader.stickers.text1.textSize,28);
  bar.listeners.change({target:{dataset:{field:'textSize'},value:'99'}}); assert.equal(PR.state.reader.stickers.text1.textSize,72);
  click('text-size-up'); assert.equal(PR.state.reader.stickers.text1.textSize,72);
  bar.listeners.change({target:{dataset:{field:'textSize'},value:''}}); assert.equal(PR.state.reader.stickers.text1.textSize,72);
  click('text-bold'); assert.equal(PR.state.reader.stickers.text1.textBold,true); assert.match(bar.innerHTML,/data-action="text-bold"[^>]*aria-pressed="true"/);
  PR.state.reader.stickers.text1.text='E = $mc^2$'; layer.children=[]; PR.renderStickers(layer,{left:0,top:0},{scrollTop:0},'front');
  const textGroup=layer.children.find(group=>group.dataset.sticker==='text1');
  assert.match(textGroup.children.find(child=>child.kind==='foreignObject').children[0].innerHTML,/class="katex"/);
});

test('a saved key for the removed sticker shortcut is ignored, so recording keys does not throw', () => {
  const code=fs.readFileSync(path.join(__dirname,'../easyread/web/js/common/features.js'),'utf8');
  const stored={'easyread-keys':{stickerToggle:'g',notes:'h'}};
  const PR={ls:{get:(k,d)=>stored[k]??d,set(){}},t:(s)=>s,emit(){},savePrefs(){}};
  const ctx={window:{PR},Object};
  vm.createContext(ctx); vm.runInContext(code,ctx);
  assert.equal('stickerToggle' in PR.keymap,false);
  assert.equal(PR.keymap.notes,'h');
  PR.applyUi({keys:{stickerToggle:'g',notes:'m'}},false);
  assert.equal('stickerToggle' in PR.keymap,false);
  assert.equal(PR.keymap.notes,'m');
});
