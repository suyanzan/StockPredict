"use strict";
(() => {
 const root=document.getElementById('daily-news');if(!root)return;
 const i18n=window.StockPredictI18n;
 i18n.register({
  'zh-TW':{
   'news.nav':'每日消息','news.kicker':'DAILY NEWS WATCH','news.title':'五則焦點，五檔觀察。',
   'news.copy':'AI 與經濟公開報導整理。觀察名單依新聞關聯選取，非買賣訊號，也不加入股價模型或正式成績。',
   'news.refresh':'更新消息','news.loading':'讀取每日整理中…','news.unavailable':'每日消息暫時無法取得，請稍後重試；原有行情與預測可繼續使用。',
   'news.waiting':'今日整理尚未更新。最近整理日：{date}。','news.partial':'資料不足：已確認 {articles}/5 則消息、{stocks}/5 檔觀察標的，不以舊消息湊數。',
   'news.meta':'{date} 整理 · 完成時間 {time}（台北） · 新聞日期範圍 {start}～{end}',
   'news.schedule':'每日早上約 08:00（台北）開始整理，完成後更新；非即時新聞串流。',
   'news.ai':'AI／科技','news.economy':'經濟／政策','news.summary':'報導重點','news.impact':'市場關注（推論）','news.source':'來源',
   'news.dateOnly':'來源僅提供日期','news.watch':'五檔新聞觀察名單','news.reason':'關注理由','news.risk':'風險觀察','news.direct':'報導直接提及','news.inference':'產業關聯推論','news.related':'對照消息',
   'news.add':'加入追蹤','news.note':'這是新聞關聯清單，不是分散投資組合。列入名單不代表必然受益、股價將上漲，亦不會自動啟用正式盤前收集。',
  },
  en:{
   'news.nav':'Daily news','news.kicker':'DAILY NEWS WATCH','news.title':'Five stories. Five stocks to watch.',
   'news.copy':'Source-linked AI and economic reporting. Stocks are selected for news relevance, not trade signals, and do not enter the price model or formal scores.',
   'news.refresh':'Refresh news','news.loading':'Loading the daily brief…','news.unavailable':'Daily news unavailable. Please retry later; existing quotes and forecasts remain available.',
   'news.waiting':'Today’s brief is not updated yet. Latest brief: {date}.','news.partial':'Insufficient evidence: {articles}/5 stories and {stocks}/5 observation stocks verified. Older news is not used to fill gaps.',
   'news.meta':'Brief {date} · completed {time} (Taipei) · source dates {start}–{end}',
   'news.schedule':'Preparation starts around 08:00 Taipei each morning. The page updates after completion; this is not a live news stream.',
   'news.ai':'AI / technology','news.economy':'Economy / policy','news.summary':'Reported facts','news.impact':'Market focus (inference)','news.source':'Sources',
   'news.dateOnly':'Source provides date only','news.watch':'Five news-linked stocks to watch','news.reason':'Why watch','news.risk':'Risk to monitor','news.direct':'Named in reporting','news.inference':'Industry inference','news.related':'Related stories',
   'news.add':'Add to watchlist','news.note':'This is a news-linked list, not a diversified portfolio. Inclusion does not imply benefits or rising prices and does not enroll stocks in pre-open collection.',
  }
 });
 const t=(key,v)=>i18n.t(`news.${key}`,v),node=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e};
 let data=null,loading=true,generation=0,controller;
 const localized=value=>value?.[i18n.getLanguage()]||value?.['zh-TW']||'';
 const stamp=value=>new Intl.DateTimeFormat(i18n.getLanguage(),{timeZone:'Asia/Taipei',dateStyle:'short',timeStyle:'short'}).format(new Date(value));
 function render(){
  document.getElementById('news-refresh').disabled=loading;
  const status=document.getElementById('news-status'),articles=document.getElementById('news-articles'),stocks=document.getElementById('news-stocks');articles.replaceChildren();stocks.replaceChildren();root.setAttribute('aria-busy',String(loading));
  if(loading){status.textContent=t('loading');return}
  if(!data){status.textContent=t('unavailable');return}
  if(data.status==='waiting'){status.textContent=t('waiting',{date:data.last_brief_date||'—'});return}
  status.textContent=t('meta',{date:data.brief_date,time:stamp(data.generated_at),start:data.window_start,end:data.window_end});
  if(data.status==='partial')articles.append(node('p','news-partial',t('partial',{articles:data.articles.length,stocks:data.watchlist.length})));
  data.articles.forEach((item,index)=>{
   const card=node('article','news-card');card.id=`news-story-${item.id}`;
   const meta=node('div','news-card-meta');meta.append(node('span','news-number',String(index+1).padStart(2,'0')),node('span','overview-badge',t(item.category)));
   meta.append(node('span','news-published',item.published_at?stamp(item.published_at):`${item.published_date} · ${t('dateOnly')}`));
   card.append(meta,node('h3','',localized(item.title)),node('p','news-summary',localized(item.summary)));
   const impact=node('p','news-impact');impact.append(node('strong','',t('impact')+'：'),document.createTextNode(localized(item.impact)));card.append(impact);
   const sources=node('div','news-sources');sources.append(node('span','',t('source')+'：'));
   for(const source of item.sources){const link=node('a','',source.publisher);link.href=source.url;link.target='_blank';link.rel='noopener noreferrer';sources.append(link)}card.append(sources);articles.append(card);
  });
  data.watchlist.forEach(item=>{
   const card=node('article','news-stock');card.append(node('span','overview-symbol',item.symbol),node('h4','',localized(item.name)),node('p','news-sector',localized(item.sector)),node('span','overview-badge',t(item.relationship==='direct'?'direct':'inference')));
   const reason=node('p','news-stock-reason');reason.append(node('strong','',t('reason')+'：'),document.createTextNode(localized(item.reason)));card.append(reason);
   const risk=node('p','news-stock-risk');risk.append(node('strong','',t('risk')+'：'),document.createTextNode(localized(item.risk)));card.append(risk);
   const refs=node('p','news-related');refs.append(document.createTextNode(t('related')+'：'));
   item.article_ids.forEach(id=>{const index=data.articles.findIndex(a=>a.id===id);const link=node('a','',String(index+1));link.href=`#news-story-${id}`;refs.append(link)});card.append(refs);
   const add=node('button','button button-secondary',t('add'));add.type='button';add.addEventListener('click',()=>{window.dispatchEvent(new CustomEvent('stockpredict-watch-symbol',{detail:{symbol:item.symbol}}));document.getElementById('stock-overview').scrollIntoView({behavior:'smooth',block:'start'})});card.append(add);stocks.append(card);
  });
 }
 async function load(){
  const current=++generation;controller?.abort();const request=new AbortController();controller=request;const timer=setTimeout(()=>request.abort(),15000);
  data=null;loading=true;render();
  try{
   const response=await fetch('/api/news/daily',{cache:'no-store',signal:request.signal});if(!response.ok)throw new Error('unavailable');const result=await response.json();
   if(!['ready','partial','waiting'].includes(result.status))throw new Error('invalid brief');
   if(result.status!=='waiting'){
    if(!Array.isArray(result.articles)||!Array.isArray(result.watchlist)||!Number.isFinite(Date.parse(result.generated_at)))throw new Error('invalid content');
    if(result.status==='ready'&&(result.articles.length!==5||result.watchlist.length!==5))throw new Error('incomplete brief');
    for(const item of result.articles)for(const source of item.sources){const u=new URL(source.url);if(u.protocol!=='https:'||u.username||u.password)throw new Error('unsafe source')}
   }
   if(current===generation)data=result;
  }catch{if(current===generation)data=null}
  finally{clearTimeout(timer);if(current===generation){loading=false;render()}}
 }
 document.getElementById('news-refresh').addEventListener('click',load);i18n.subscribe(render);load();
})();
