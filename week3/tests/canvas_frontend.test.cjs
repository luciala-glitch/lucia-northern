/* DOM harness tests for our canvas logic, using only Node's standard library.
   This does not replace the real-browser integration check. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../landmark_canvas/index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function browser() {
  const sent = [], listeners = {};
  let ids;
  class Element {
    constructor(id='') {
      this.id=id;this.attrs={};this.style={};this.children=[];this.events={};this.textContent='';this.srcChanges=0;
      this._left=0;this._top=0;this.captured=new Set();
      const classes=new Set();
      this.classList={toggle(name,value){value?classes.add(name):classes.delete(name);},contains(name){return classes.has(name);}};
    }
    get clientWidth(){return this.id==='viewport'?640:this.getBoundingClientRect().width;}
    get clientHeight(){return this.id==='viewport'?460:this.getBoundingClientRect().height;}
    get scrollLeft(){return this._left;}
    set scrollLeft(value){this._left=Math.max(0,Math.min(value,(Number.parseFloat(ids.stage.style.width)||1100)-640));}
    get scrollTop(){return this._top;}
    set scrollTop(value){this._top=Math.max(0,Math.min(value,(Number.parseFloat(ids.stage.style.width)||1100)*1024/2041-460));}
    setAttribute(k,v) { this.attrs[k]=v; }
    getAttribute(k) { return this.attrs[k] ?? null; }
    removeAttribute(k) { delete this.attrs[k]; }
    append(child) { this.children.push(child); }
    replaceChildren() { this.children=[]; }
    addEventListener(type, handler) { this.events[type]=handler; }
    setPointerCapture(id){this.captured.add(id);}
    hasPointerCapture(id){return this.captured.has(id);}
    releasePointerCapture(id){this.captured.delete(id);}
    set src(value) { this.srcChanges++; this.attrs.src=value; }
    getBoundingClientRect() {
      if(this.id==='viewport')return {left:10,top:20,width:640,height:460};
      const width=Number.parseFloat(this.style.width)||1100;
      return {left:10-(ids?.viewport.scrollLeft||0),top:20-(ids?.viewport.scrollTop||0),width,height:width*1024/2041};
    }
  }
  ids=Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(match=>[match[1],new Element(match[1])]));
  const parent={postMessage(message){sent.push(structuredClone(message));}};
  const window={parent,addEventListener(type,fn){listeners[type]=fn;}};
  const document={body:{scrollHeight:600},getElementById:id=>ids[id],createElementNS:()=>new Element()};
  vm.runInNewContext(script,{window,document,ResizeObserver:class {observe(){}}});
  function fireClick(clientX,clientY){
    const event={clientX,clientY,button:0,pointerId:1,preventDefault(){}};
    ids.stage.events.pointerdown(event);ids.stage.events.pointerup(event);ids.stage.events.click(event);
  }
  return {ids,sent,render(args){listeners.message({source:parent,data:{type:'streamlit:render',args}});},load(){ids.xray.events.load();},
    click(x,y){const r=ids.stage.getBoundingClientRect();fireClick(r.left+(Number.isInteger(x)?x+0.25:x)*r.width/2041,r.top+(Number.isInteger(y)?y+0.25:y)*r.height/1024);},
    clickVisible(x=250,y=180){fireClick(10+x,20+y);},
    button(id){ids[id].events.click();},
    key(type,event){listeners[type]({...event,preventDefault(){}});},
    wheel(x,y,deltaY){ids.viewport.events.wheel({clientX:10+x,clientY:20+y,deltaY,ctrlKey:true,preventDefault(){}});},
    drag(dx,dy){
      const base={clientX:260,clientY:200,button:0,pointerId:2,preventDefault(){}};
      ids.stage.events.pointerdown(base);
      ids.stage.events.pointermove({...base,clientX:260+dx,clientY:200+dy});
      ids.stage.events.pointerup({...base,clientX:260+dx,clientY:200+dy});
      ids.stage.events.click({...base,clientX:260+dx,clientY:200+dy});
    },
    values(){return sent.filter(m=>m.type==='streamlit:setComponentValue').map(m=>m.value);}
  };
}

const initial = { image_id:'raw-id',src:'data:image/png;base64,example',image_width:2041,image_height:1024,display_width:1100,
  names:['mesial.cej','mesial.bc','distal.cej','distal.bc','apex'],labels:['M CEJ','M BC','D CEJ','D BC','Apex'],points:{},epoch:1,revision:0 };

test('image load is acknowledged; marker updates do not reload the image',()=>{
  const b=browser();b.render(initial);b.click(100,100);
  assert.equal(b.values().length,0,'do not record clicks before decoding');
  b.load();assert.equal(b.values().at(-1).type,'image_ready');
  b.render({...initial,src:null});b.click(100.9,200.8);
  const click=b.values().at(-1);
  assert.equal(click.type,'points');assert.deepEqual(click.points['mesial.cej'],[100,200]);
  assert.equal(click.image_id,'raw-id');
  b.render({...initial,src:null,revision:click.revision,points:click.points});
  assert.equal(b.ids.xray.srcChanges,1);
  const dot=b.ids.overlay.children.find(node=>'cx' in node.attrs);
  assert.equal(dot.attrs.cx,100.5);assert.equal(dot.attrs.cy,200.5);
});

test('rapid clicks survive an older server acknowledgement and undo/reset',()=>{
  const b=browser();b.render(initial);b.load();b.click(100,100);
  const first=b.values().at(-1);b.click(100,200);
  b.render({...initial,src:null,revision:1,points:first.points});
  assert.match(b.ids.instruction.textContent,/Click 3\/5/);
  b.render({...initial,src:null,epoch:2,revision:0,points:first.points});
  assert.match(b.ids.instruction.textContent,/Click 2\/5/);
  b.click(110,210);assert.deepEqual(b.values().at(-1).points['mesial.bc'],[110,210]);
  b.render({...initial,src:null,epoch:3,revision:0,points:{}});
  assert.match(b.ids.instruction.textContent,/Click 1\/5/);
  assert.equal(b.ids.xray.srcChanges,1);
});

test('reloaded iframe requests its missing image and recovers existing points',()=>{
  const b=browser();b.render({...initial,src:null,points:{'mesial.cej':[99,88]},revision:1});
  assert.equal(b.values().at(-1).type,'image_needed');
  assert.equal(b.values().at(-1).image_id,'raw-id');
  b.render({...initial,points:{'mesial.cej':[99,88]},revision:1});b.load();
  assert.equal(b.values().at(-1).type,'image_ready');
  assert.match(b.ids.instruction.textContent,/Click 2\/5/);
  b.click(110,210);assert.deepEqual(b.values().at(-1).points['mesial.cej'],[99,88]);
});

test('changing condition loads and acknowledges a new image once',()=>{
  const b=browser();b.render(initial);b.load();
  b.render({...initial,src:null,epoch:2,image_id:'clahe-id'});
  assert.equal(b.values().at(-1).type,'image_needed');
  b.render({...initial,src:'data:image/png;base64,enhanced',epoch:2,image_id:'clahe-id'});b.load();
  assert.equal(b.values().at(-1).image_id,'clahe-id');
  b.render({...initial,src:null,epoch:2,image_id:'clahe-id'});
  assert.equal(b.ids.xray.srcChanges,2);
  b.click(10,20);assert.equal(b.values().at(-1).image_id,'clahe-id');
});

test('all five landmarks complete without a sixth point; image edges are clamped',()=>{
  const b=browser();b.render(initial);b.load();
  [[0,0],[100,100],[200,100],[200,200],[3000,2000],[42,42]].forEach(([x,y])=>b.click(x,y));
  const event=b.values().at(-1);
  assert.equal(Object.keys(event.points).length,5);
  assert.deepEqual(event.points.apex,[2040,1023]);
  assert.match(b.ids.instruction.textContent,/All landmarks placed/);
  assert.ok(JSON.stringify(event).length<1024);
});


test('fit shows the whole image; zoom preserves the centre and can pan to the right',()=>{
  const b=browser();b.render(initial);b.load();
  assert.ok(b.ids.stage.getBoundingClientRect().width<=640);
  const before=(b.ids.viewport.scrollLeft+320)/b.ids.stage.getBoundingClientRect().width;
  b.button('zoom-in');
  assert.ok(Math.abs((b.ids.viewport.scrollLeft+320)/b.ids.stage.getBoundingClientRect().width-before)<1e-10);
  for(let i=0;i<4;i++)b.button('zoom-in');
  const left=b.ids.viewport.scrollLeft,top=b.ids.viewport.scrollTop;
  b.button('mode-pan');b.drag(-300,-120);
  assert.equal(b.ids.viewport.scrollLeft,left+300);
  assert.equal(b.ids.viewport.scrollTop,top+120);
  assert.equal(b.values().length,1,'navigation must not submit a landmark');
  b.button('fit-view');assert.equal(b.ids.viewport.scrollLeft,0);assert.equal(b.ids.viewport.scrollTop,0);
  assert.ok(b.ids.stage.getBoundingClientRect().width<=640);
});

test('dragging in mark mode pans without adding a point; clicking after pan uses original pixels',()=>{
  const b=browser();b.render(initial);b.load();
  for(let i=0;i<4;i++)b.button('zoom-in');
  b.drag(-280,-100);
  assert.equal(b.values().length,1);
  const rect=b.ids.stage.getBoundingClientRect();
  const expectedX=Math.floor((260-rect.left)*2041/rect.width);
  const expectedY=Math.floor((200-rect.top)*1024/rect.height);
  b.clickVisible();
  assert.deepEqual(b.values().at(-1).points['mesial.cej'],[expectedX,expectedY]);
});

test('pan mode never marks on click, and Space temporarily pans without changing mode',()=>{
  const b=browser();b.render(initial);b.load();
  b.button('mode-pan');b.clickVisible();assert.equal(b.values().length,1);
  b.button('mode-mark');b.key('keydown',{code:'Space',target:{tagName:'DIV'}});
  b.clickVisible();assert.equal(b.values().length,1);
  b.key('keyup',{code:'Space'});b.clickVisible();assert.equal(b.values().at(-1).type,'points');
});

test('wheel zoom keeps the cursor target fixed; server acknowledgements retain zoom and pan',()=>{
  const b=browser();b.render(initial);b.load();
  const fraction=160/b.ids.stage.getBoundingClientRect().width;
  b.wheel(160,100,-240);
  assert.ok(Math.abs((b.ids.viewport.scrollLeft+160)/b.ids.stage.getBoundingClientRect().width-fraction)<1e-10);
  b.clickVisible();const event=b.values().at(-1);
  const width=b.ids.stage.getBoundingClientRect().width,left=b.ids.viewport.scrollLeft,top=b.ids.viewport.scrollTop;
  b.render({...initial,src:null,revision:event.revision,points:event.points});
  assert.equal(b.ids.stage.getBoundingClientRect().width,width);
  assert.equal(b.ids.viewport.scrollLeft,left);assert.equal(b.ids.viewport.scrollTop,top);
  assert.equal(b.ids.xray.srcChanges,1);
  b.render({...initial,src:null,display_width:1800,revision:event.revision,points:event.points});
  assert.equal(b.ids.stage.getBoundingClientRect().width,1800);
});

test('registered tooth location is distinct from landmarks; find centres the selected tooth',()=>{
  const b=browser();
  b.render({...initial,names:['locator'],labels:['Tooth crown centre'],markers:[{id:3,x:1700,y:700}],focus:[1700,700]});b.load();
  assert.ok(b.ids.overlay.children.some(n=>n.textContent==='3'));
  assert.equal(b.values().filter(v=>v.type==='points').length,0);
  b.button('focus-tooth');
  const r=b.ids.stage.getBoundingClientRect();
  assert.ok(Math.abs(b.ids.viewport.scrollLeft-Math.min(r.width-640,Math.max(0,1700*r.width/2041-320)))<1,'centre the location as far as the image edge permits');
  assert.ok(r.height<=460/0.55+1,'default view leaves enough vertical room for a whole tooth');
  b.click(1720,720);
  assert.deepEqual(b.values().at(-1).points,{locator:[1720,720]});
  b.click(1730,730);
  assert.equal(b.values().filter(v=>v.type==='points').length,1,'one location per registration');
});

test('selected tooth box is fitted completely with margin on first render',()=>{
  const b=browser();
  const box=[800,100,1100,900];
  b.render({...initial,markers:[{id:1,x:950,y:500,selected:true}],focus:[950,500],focus_box:box});b.load();
  const r=b.ids.stage.getBoundingClientRect();
  const scale=r.width/2041;
  const visibleLeft=box[0]*scale-b.ids.viewport.scrollLeft;
  const visibleRight=box[2]*scale-b.ids.viewport.scrollLeft;
  const visibleTop=box[1]*scale-b.ids.viewport.scrollTop;
  const visibleBottom=box[3]*scale-b.ids.viewport.scrollTop;
  assert.ok(visibleLeft>=0&&visibleRight<=640,'whole tooth width is visible');
  assert.ok(visibleTop>=0&&visibleBottom<=460,'whole tooth height is visible');
  assert.ok(visibleLeft>12&&640-visibleRight>12,'horizontal breathing room');
  assert.ok(visibleTop>12&&460-visibleBottom>12,'vertical breathing room');
});

test('recorded tooth cannot be marked again, but can still pan and zoom',()=>{
  const b=browser();b.render({...initial,locked:true});b.load();
  b.click(100,100);
  assert.equal(b.values().filter(v=>v.type==='points').length,0);
  assert.match(b.ids.instruction.textContent,/Recorded.*locked/);
  b.button('zoom-in');b.drag(-100,0);
  assert.ok(b.ids.viewport.scrollLeft>0);
});

test('practice feedback draws expert rings joined to the locked reader points',()=>{
  const points={'mesial.cej':[100,100],'mesial.bc':[100,200],'distal.cej':[300,100],'distal.bc':[300,200],apex:[200,500]};
  const b=browser();
  b.render({...initial,points,revision:1,locked:true,locked_message:'Practice submitted',reference:{'mesial.cej':[110.5,104.25]}});b.load();
  assert.match(b.ids.instruction.textContent,/Practice submitted/);
  const ring=b.ids.overlay.children.find(node=>node.attrs['data-reference']==='mesial.cej');
  assert.equal(ring.attrs.cx,110.5);assert.equal(ring.attrs.cy,104.25);
  const link=b.ids.overlay.children.find(node=>node.attrs.x2===110.5);
  assert.equal(link.attrs.x1,100.5);assert.equal(link.attrs.y1,100.5);
  assert.ok(b.ids.overlay.children.some(node=>node.textContent==='Expert M-CEJ'));
  b.click(50,50);assert.equal(b.values().filter(v=>v.type==='points').length,0);
});

test('two clicked corners draw the tooth box in either order',()=>{
  const b=browser();
  b.render({...initial,names:['box.a','box.b'],labels:['First corner','Opposite corner'],points:{'box.a':[300,400],'box.b':[200,100]},revision:2});b.load();
  const box=b.ids.overlay.children.find(node=>node.attrs['data-tooth-box']);
  assert.equal(box.attrs.x,200.5);assert.equal(box.attrs.y,100.5);
  assert.equal(box.attrs.width,100);assert.equal(box.attrs.height,300);
  assert.ok(b.ids.overlay.children.some(node=>node.textContent==='Corner 2'));
});

test('measurement locations are hidden by default and can be shown without covering the crown',()=>{
  const b=browser();b.render({...initial,markers:[{id:1,x:900,y:500}]});b.load();
  assert.ok(!b.ids.overlay.children.some(n=>n.textContent==='1'));
  b.button('toggle-locations');
  assert.ok(b.ids.overlay.children.some(n=>n.textContent==='1'));
  assert.ok(!b.ids.overlay.children.some(n=>'rx' in n.attrs),'no filled tooth boxes during measurement');
  b.button('toggle-locations');
  assert.ok(!b.ids.overlay.children.some(n=>n.textContent==='1'));
  b.click(900,500);
  assert.deepEqual(b.values().at(-1).points['mesial.cej'],[900,500]);
});

test('only the selected tooth has a subtle locator by default; switching teeth centres the new location',()=>{
  const b=browser();
  const a={...initial,markers:[{id:1,x:600,y:450,selected:true},{id:2,x:1300,y:450}],focus:[600,450]};
  b.render(a);b.load();
  assert.ok(b.ids.overlay.children.some(n=>n.textContent==='1'));
  assert.ok(!b.ids.overlay.children.some(n=>n.textContent==='2'));
  assert.ok(!b.ids.overlay.children.some(n=>n.attrs['data-role']==='tooth-locator'),'locator is a number only');
  const markers=[{id:1,x:600,y:450},{id:2,x:1300,y:450,selected:true}];
  b.render({...a,src:null,markers,focus:[1300,450],epoch:2});
  assert.ok(b.ids.overlay.children.some(n=>n.textContent==='2'));
  assert.ok(!b.ids.overlay.children.some(n=>n.textContent==='1'));
  const r=b.ids.stage.getBoundingClientRect();
  assert.ok(Math.abs(1300*r.width/2041-b.ids.viewport.scrollLeft-320)<1);
});

test('saving the current tooth retains image, zoom and pan',()=>{
  const b=browser();const a={...initial,markers:[{id:2,x:1300,y:500,selected:true}],focus:[1300,500]};
  b.render(a);b.load();b.button('zoom-in');b.drag(-60,-40);
  const before={width:b.ids.stage.style.width,left:b.ids.viewport.scrollLeft,top:b.ids.viewport.scrollTop};
  b.render({...a,src:null,locked:true});
  assert.deepEqual({width:b.ids.stage.style.width,left:b.ids.viewport.scrollLeft,top:b.ids.viewport.scrollTop},before);
  assert.equal(b.ids.xray.srcChanges,1);
});
