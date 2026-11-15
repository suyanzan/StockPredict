"use strict";
(() => {
 const root=document.getElementById('weekly-accuracy');if(!root)return;
 const i18n=window.StockPredictI18n;
 i18n.register({
  'zh-TW':{
   'weekly.kicker':'PREDICTION TRACK RECORD','weekly.title':'先看過去一週的預測實績。','weekly.copy':'盤前已封存、收盤後核對的隔日預測。價格偏差與方向命中分開看，成績隨資料更新。',
   'weekly.refresh':'更新實績','weekly.loading':'核對最近五個交易日的封存成績…','weekly.unavailable':'實績暫時無法確認，請重試；不沿用舊數字。',
   'weekly.period':'{start}～{end} · 最近 5 個可公布交易日 · 核對 {time}（台北）',
   'weekly.price':'平均價格偏差','weekly.priceExplain':'換算每 100 元實際收盤，平均差約 {error} 元。','weekly.priceNote':'平均絕對百分比誤差（MAPE），越低越好；不是每次誤差上限。',
   'weekly.direction':'漲跌方向命中','weekly.directionExplain':'{n} 次中猜對 {hits} 次；上漲、持平、下跌分開判斷。',
   'weekly.samples':'可計分樣本','weekly.coverage':'涵蓋 {dates}/5 個日期 · 缺漏 {missing} 筆／待取得收盤 {pending} 筆／排除異常 {excluded} 筆。',
   'weekly.better':'本週價格偏差較基準低，仍需累積證據。','weekly.worse':'目前未優於前收盤基準。','weekly.equal':'目前與前收盤基準相當。','weekly.noSamples':'尚無可計分樣本，不能判定準不準。',
   'weekly.baseline':'相同樣本：模型平均偏差 {model}%，前收盤基準 {baseline}%。基準指直接預測收盤等於前一交易日收盤。',
   'weekly.scope':'主摘要只含聯電、台積電、台達電的純台股隔日預測，不含 ADR、自選研究預測或五日結果。缺漏不算命中，也不當成零誤差。',
   'weekly.caution':'樣本僅涵蓋少數日期，多檔同日結果也不是獨立交易日；尚不足證明長期可靠或未來獲利。這是歷史誤差，不是「100% 減誤差」的準確率。',
   'weekly.details':'展開個股與 ADR 實績','weekly.columns':'股票／情境,樣本,平均價格偏差,方向命中,相同樣本基準偏差,有效日期',
   'weekly.taiwan':'純台股','weekly.adr':'ADR 情境','weekly.detailNote':'每列基準只比相同樣本；不同情境有效日期可能不同，不能直接比較成實驗優劣。五日結果與正式可靠性驗收另見成績看板。','weekly.all':'查看完整成績與逐筆紀錄 →',
  },
  en:{
   'weekly.kicker':'PREDICTION TRACK RECORD','weekly.title':'Start with the past week’s actual results.','weekly.copy':'Original pre-open next-session forecasts checked against actual closes. Price error and direction accuracy are reported separately.',
   'weekly.refresh':'Refresh results','weekly.loading':'Checking the last five publishable trading sessions…','weekly.unavailable':'Results cannot be verified right now. Please retry; old figures are cleared.',
   'weekly.period':'{start}–{end} · Last 5 publishable sessions · checked {time} (Taipei)',
   'weekly.price':'Average price error','weekly.priceExplain':'Equivalent to an average error of {error} per 100 of actual closing price.','weekly.priceNote':'Mean absolute percentage error (MAPE). Lower is better; this is not a per-forecast error limit.',
   'weekly.direction':'Direction accuracy','weekly.directionExplain':'{hits} correct out of {n}; up, flat and down are separate directions.',
   'weekly.samples':'Scorable samples','weekly.coverage':'{dates}/5 dates covered · {missing} missing / {pending} awaiting actual close / {excluded} invalid slots excluded.',
   'weekly.better':'Lower price error than baseline this week; more evidence is needed.','weekly.worse':'Not outperforming the previous-close baseline.','weekly.equal':'Currently matching the previous-close baseline.','weekly.noSamples':'No scorable samples yet; accuracy cannot be assessed.',
   'weekly.baseline':'Identical samples: model error {model}%, previous-close baseline {baseline}%. The baseline predicts the prior session’s close.',
   'weekly.scope':'Main summary: Taiwan-only next-session forecasts for UMC, TSMC and Delta. Excludes ADR, custom research forecasts and five-session results. Missing records are neither hits nor zero errors.',
   'weekly.caution':'Only a few dates are covered; multiple stocks on one date are not independent sessions. This does not establish long-term reliability or future profits. Error is not an accuracy rate calculated as 100% minus MAPE.',
   'weekly.details':'Stock and ADR results','weekly.columns':'Stock / scenario,Samples,Average price error,Direction hits,Matched baseline error,Scored dates',
   'weekly.taiwan':'Taiwan only','weekly.adr':'ADR scenario','weekly.detailNote':'Each baseline uses the same samples as its row. Scenario dates can differ, so rows are not a controlled comparison. Five-session results and formal reliability acceptance remain on the scoreboard.','weekly.all':'View full scores and individual records →',
  }
 });
 const t=(key,args)=>i18n.t('weekly.'+key,args),el=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e};
 const number=n=>Number.isFinite(n)?n.toFixed(2):'—',percent=n=>Number.isFinite(n)?`${number(n)}%`:'—';
 let data=null,loading=true;
 function render(){
  const body=document.getElementById('weekly-content'),status=document.getElementById('weekly-status');body.replaceChildren();document.getElementById('weekly-refresh').disabled=loading;root.setAttribute('aria-busy',String(loading));
  if(loading){status.textContent=t('loading');return}if(!data){status.textContent=t('unavailable');return}
  const m=data.taiwan;status.textContent=t('period',{start:data.sessions[0],end:data.sessions.at(-1),time:new Intl.DateTimeFormat(i18n.getLanguage(),{timeZone:'Asia/Taipei',dateStyle:'short',timeStyle:'short'}).format(new Date(data.checked_at))});
  const cards=el('div','weekly-grid');
  function card(label,value,explain,note){const c=el('article','weekly-card');c.append(el('h3','',t(label)),el('p','weekly-number',value),el('p','weekly-explain',explain));if(note)c.append(el('p','weekly-note',note));cards.append(c)}
  card('price',percent(m.mape),m.samples?t('priceExplain',{error:number(m.mape)}):t('noSamples'),t('priceNote'));
  card('direction',m.samples?percent(m.hits/m.samples*100):'—',t('directionExplain',{hits:m.hits,n:m.samples}));
  card('samples',`${m.samples}/${m.expected}`,t('coverage',{dates:m.dates.length,missing:m.missing,pending:m.pending,excluded:m.excluded}));body.append(cards);
  const delta=m.mape-m.baseline_mape;
  const verdict=el('div','weekly-verdict');verdict.append(el('strong','',t(!m.samples?'noSamples':Math.abs(delta)<1e-9?'equal':delta<0?'better':'worse')));if(m.samples)verdict.append(el('p','',t('baseline',{model:number(m.mape),baseline:number(m.baseline_mape)})));body.append(verdict,el('p','weekly-note',t('scope')),el('p','weekly-caution',t('caution')));
  const details=el('details','weekly-details');details.append(el('summary','',t('details')));const wrap=el('div','weekly-table-wrap'),table=el('table','weekly-table'),head=el('thead'),tr=el('tr');
  for(const label of t('columns').split(',')){const cell=el('th','',label);cell.scope='col';tr.append(cell)}head.append(tr);table.append(head);const tbody=el('tbody');
  for(const stock of data.stocks){const row=el('tr');const key={'2303.TW':'security.umc','2330.TW':'security.tsmc','2308.TW':'security.delta'}[stock.symbol];for(const value of [`${i18n.t(key)} ${stock.symbol} · ${t(stock.scenario)}`,String(stock.samples),percent(stock.mape),stock.samples?`${stock.hits}/${stock.samples}`:'—',percent(stock.baseline_mape),stock.dates.join(' / ')||'—'])row.append(el('td','',value));tbody.append(row)}table.append(tbody);wrap.append(table);details.append(wrap,el('p','weekly-note',t('detailNote')));body.append(details);const link=el('a','weekly-link',t('all'));link.href='#scoreboard';body.append(link);
 }
 window.addEventListener('stockpredict-scoreboard-loading',()=>{loading=true;data=null;render()});
 window.addEventListener('stockpredict-scoreboard',event=>{const value=event.detail?.scores?.weekly_accuracy;data=event.detail?.scores?.status==='ready'&&value?.scope==='preopen_day1_target_sessions'&&Array.isArray(value.sessions)&&value.sessions.length===5&&value.taiwan&&Array.isArray(value.stocks)&&Number.isFinite(Date.parse(value.checked_at))?value:null;loading=false;render()});
 document.getElementById('weekly-refresh').addEventListener('click',()=>{if(window.StockPredictScoreboard)window.StockPredictScoreboard.refresh();else window.location.reload()});
 setTimeout(()=>{if(loading){loading=false;data=null;render()}},25000);i18n.subscribe(render);render();
})();
