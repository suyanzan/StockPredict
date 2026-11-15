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
