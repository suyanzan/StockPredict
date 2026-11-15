const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const context = {window: {}, document: {getElementById: () => null}};
vm.runInNewContext(fs.readFileSync('stockpredict/static/overview.js', 'utf8'), context);
const summarize = context.window.StockPredictOverview.summarize;
const {normalizeWatchSymbol,parseWatchlist} = context.window.StockPredictOverview;
const {parseWatchlistImport} = context.window.StockPredictOverview;
const {validateResearch} = context.window.StockPredictOverview;
const researchQuote={source:'twse',symbol:'0050.TW',session_date:'2026-11-13',expected_session_date:'2026-11-13',close:102.5,fresh:true};
const researchResult={symbol:'0050.TW',source:'twse',as_of:'2026-11-13',summary:{last_close:102.5},model:{name:'Ridge AR(5)'},history:[{date:'2026-11-13',close:102.5}],data_status:{status:'current',session_date:'2026-11-13',expected_session_date:'2026-11-13',checked_at:'2026-11-15T07:30:00+00:00'},forecast:['16','17','18','19','20'].map((day,i)=>({date:`2026-11-${day}`,close:103+i})),backtest:{model_beats_baseline:false}};
test('research forecast requires the same current symbol, source, basis date and close as its quote',()=>{
 const result=validateResearch(researchResult,researchQuote);
 assert.equal(result.points.length,5);assert.equal(result.points[0].close,103);assert.equal(result.beatsBaseline,false);
 for(const change of [{symbol:'2317.TW'},{source:'demo'},{as_of:'2026-11-12'},{summary:{last_close:100}},{data_status:{...researchResult.data_status,status:'missing'}},{data_status:{...researchResult.data_status,expected_session_date:'2026-11-16'}}])assert.equal(validateResearch({...researchResult,...change},researchQuote),null);
 assert.equal(validateResearch(researchResult,{...researchQuote,fresh:false}),null);
 assert.equal(validateResearch({...researchResult,history:[...researchResult.history,{date:'2026-11-16',close:999}]},researchQuote),null);
});
test('research path rejects partial, nonfinite, duplicate, past, weekend and invalid dates',()=>{
 for(const path of [researchResult.forecast.slice(0,4),researchResult.forecast.map((p,i)=>i===0?{...p,close:NaN}:p),researchResult.forecast.map(p=>({...p,date:'2026-11-16'})),researchResult.forecast.map((p,i)=>i===0?{...p,date:'2026-11-13'}:p),researchResult.forecast.map((p,i)=>i===4?{...p,date:'2026-11-21'}:p),researchResult.forecast.map((p,i)=>i===4?{...p,date:'2026-11-31'}:p)])assert.equal(validateResearch({...researchResult,forecast:path},researchQuote),null);
});
test('import schema rejects malformed or oversized lists without silently dropping invalid codes',()=>{
 const wrap=symbols=>JSON.stringify({format:'stockpredict.watchlist',version:1,symbols});
 assert.equal(JSON.stringify(parseWatchlistImport(wrap(['0050','2330.tw','0050.TW']))),'["0050.TW","2330.TW"]');
 assert.equal(JSON.stringify(parseWatchlistImport(wrap([]))),'[]');
 for(const raw of ['[]','{broken',wrap(['2330','AAPL']),wrap(Array(9).fill('2330')),JSON.stringify({format:'stockpredict.watchlist',version:2,symbols:[]})])assert.throws(()=>parseWatchlistImport(raw));
});
test('reliability summary detects late and duplicate captures instead of treating API success as acceptance',()=>{
 vm.runInNewContext(fs.readFileSync('stockpredict/static/reliability.js','utf8'),context);
 const capture=context.window.StockPredictReliability.capture;
 const row={symbol:'2303.TW',scenario:'taiwan',origin_date:'2026-11-13',horizon:1,created_at:'2026-11-13T00:11:00+00:00'};
 assert.equal(capture([row],row.origin_date).count,1);
 assert.equal(capture([row,row],row.origin_date).invalid,true);
 assert.equal(capture([{...row,created_at:'2026-11-13T01:01:00+00:00'}],row.origin_date).invalid,true);
 assert.equal(capture({},row.origin_date).count,0);
});
test('watchlist validates symbols, preserves ETF leading zeros, deduplicates and bounds storage',()=>{
 assert.equal(normalizeWatchSymbol(' 0050.tw '),'0050.TW');
 for(const value of ['AAPL','2330.TWO','<script>',null,2330])assert.equal(normalizeWatchSymbol(value),null);
 assert.equal(JSON.stringify(parseWatchlist('["2330","2330.TW","0050","AAPL"]')), '["2330.TW","0050.TW"]');
 assert.equal(JSON.stringify(parseWatchlist('[]')),'[]');
 assert.equal(parseWatchlist('{broken').length,3);
 assert.equal(parseWatchlist('{"symbol":"2330"}').length,3);
 assert.equal(parseWatchlist(JSON.stringify(Array.from({length:20},(_,i)=>String(2000+i)))).length,8);
});
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
