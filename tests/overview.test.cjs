const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const context = {window: {}, document: {getElementById: () => null}};
vm.runInNewContext(fs.readFileSync('stockpredict/static/overview.js', 'utf8'), context);
const summarize = context.window.StockPredictOverview.summarize;
const market = {latest_publishable_session:'2026-11-13',next_session:'2026-11-16'};
const detail = {
 base_date:'2026-11-12',base_close:100,origin_date:'2026-11-13',
 forecast:[
  {target_date:'2026-11-13',actual_close:102,predicted_close:101,horizon:1},
  {target_date:'2026-11-16',actual_close:null,predicted_close:103,horizon:2},
 ]
};
test('daily close and daily change use actual adjacent sessions; estimate is not a quote',()=>{
 const r=summarize(detail,market);
 assert.equal(r.close,102);assert.equal(r.change,2);assert.equal(r.changePct,2);
 assert.equal(r.forecast,103);assert.equal(r.horizon,2);assert.equal(r.olderOrigin,true);
 assert.equal(r.fresh,true);
});
test('missing daily actual is marked stale without relabelling the base price',()=>{
 const r=summarize({...detail,forecast:detail.forecast.map(p=>({...p,actual_close:null}))},market);
 assert.equal(r.day,'2026-11-12');assert.equal(r.close,100);assert.equal(r.fresh,false);
 assert.equal(r.change,null);assert.equal(r.forecastPct,null);
});
test('missing adjacent close never becomes a multi-session daily return',()=>{
 const d={...detail,forecast:[{target_date:'2026-11-13',actual_close:null},
  {target_date:'2026-11-16',actual_close:110,predicted_close:109,horizon:2}]};
 const r=summarize(d,{latest_publishable_session:'2026-11-16',next_session:'2026-11-17'});
 assert.equal(r.close,110);assert.equal(r.change,null);assert.equal(r.forecast,null);
});
test('future actual rows are not published as current daily quotes',()=>{
 const d={...detail,forecast:[...detail.forecast,{target_date:'2026-11-17',actual_close:999}]};
 assert.equal(summarize(d,market).close,102);
});
test('no calendar or archive never produces a usable summary',()=>{
 assert.equal(summarize(detail,null),null);assert.equal(summarize(null,market),null);
});
test('invalid prices cannot produce quotes or estimated returns',()=>{
 const r=summarize({...detail,base_close:NaN,forecast:[{target_date:'2026-11-16',actual_close:false,predicted_close:Infinity}]},market);
 assert.equal(r.close,null);assert.equal(r.forecast,null);assert.equal(r.change,null);
});

test('missing scoreboard script exits loading and retry reloads instead of waiting forever',()=>{
 const timers=new Map(), listeners=new Map(), elements=new Map();let reloaded=false;
 const element=()=>({attributes:{},append(){},replaceChildren(){},
  setAttribute(key,value){this.attributes[key]=value;},
  addEventListener(key,fn){this[key]=fn;}});
 const getElementById=id=>{
  if(!elements.has(id))elements.set(id,element());
  return elements.get(id);
 };
 const sandbox={
  window:{StockPredictI18n:{register(){},subscribe(){},t:key=>key,getLanguage:()=> 'en'},
   addEventListener:(key,fn)=>listeners.set(key,fn),location:{reload:()=>{reloaded=true;}}},
  document:{getElementById,createElement:element},
  setTimeout:(fn,delay)=>{const id=timers.size+1;timers.set(id,{fn,delay});return id;},
  clearTimeout:id=>timers.delete(id),
 };
 vm.runInNewContext(fs.readFileSync('stockpredict/static/overview.js','utf8'),sandbox);
 assert.equal(getElementById('stock-overview').attributes['aria-busy'],'true');
 assert.equal(getElementById('overview-refresh').disabled,true);
 const deadline=[...timers.values()].find(timer=>timer.delay===40000);
 assert.ok(deadline);deadline.fn();
 assert.equal(getElementById('stock-overview').attributes['aria-busy'],'false');
 assert.equal(getElementById('overview-refresh').disabled,false);
 assert.equal(getElementById('overview-status').textContent,'overview.unavailable');
 getElementById('overview-refresh').click();assert.equal(reloaded,true);
});
