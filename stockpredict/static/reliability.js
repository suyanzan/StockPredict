"use strict";
(() => {
  const required = [["2303.TW","taiwan"],["2303.TW","adr"],["2330.TW","taiwan"],["2330.TW","adr"],["2308.TW","taiwan"]];
  const origins = ["2026-11-10","2026-11-11","2026-11-12","2026-11-13","2026-11-16"];
  const fifth = ["2026-11-16","2026-11-17","2026-11-18","2026-11-19","2026-11-20"];
  function capture(rows, day) {
    const records = (Array.isArray(rows)?rows:[]).filter(r=>r.origin_date===day && r.horizon===1);
    const missing = required.filter(([symbol,scenario])=>!records.some(r=>r.symbol===symbol&&r.scenario===scenario));
    const invalid = required.some(([symbol,scenario])=>{
      const matches=records.filter(r=>r.symbol===symbol&&r.scenario===scenario);
      return matches.length>1 || matches.some(r=>!Number.isFinite(Date.parse(r.created_at)) || Date.parse(r.created_at)>=Date.parse(`${day}T09:00:00+08:00`) || Date.parse(r.created_at)<Date.parse(`${day}T00:00:00+08:00`));
    });
    return {count:required.length-missing.length,missing,invalid};
  }
  window.StockPredictReliability={capture};
  const root=document.getElementById("reliability-status");if(!root)return;
  const i18n=window.StockPredictI18n;
  i18n.register({
    "zh-TW":{
      "reliability.title":"資料更新狀態", "reliability.site":"網站回應", "reliability.online":"可讀取", "reliability.unknown":"尚無可確認資料",
      "reliability.run":"最近收集執行", "reliability.success":"最近成功檢查", "reliability.capture":"盤前封存摘要", "reliability.closes":"收盤更新",
      "reliability.loading":"讀取狀態中…", "reliability.unavailable":"狀態暫時無法取得，請更新總覽重試。",
      "reliability.captureValue":"{day} · {count}/5 情境", "reliability.invalid":"存在重複或逾時紀錄", "reliability.missing":"缺漏：{items}",
      "reliability.collecting":"盤前收集時間尚未結束，未保存的情境仍待收集。",
      "reliability.closeValue":"{due} 筆已到期未計分 · {future} 筆待公布", "reliability.alerts":"目前監測：{items}", "reliability.noAlerts":"目前監測未回報告警。",
      "reliability.schedule_stale":"收集排程逾時", "reliability.preopen_missing":"盤前情境缺漏", "reliability.actual_close_missing":"到期收盤缺漏", "reliability.source_unavailable":"資料來源異常", "reliability.no_checks":"尚無收集檢查",
      "reliability.note":"成功檢查代表該次資料檢查正常，不等於全部歷史資料完整、通知已送達或五日驗收通過。",
      "reliability.acceptance":"V1.1 五交易日驗收", "reliability.day":"{day}：封存 {count}/5 · 第五日 {target} · {state}",
      "reliability.pending":"pending／尚未成熟", "reliability.due":"已到期，仍需核對完整證據", "reliability.future":"起日尚未發生", "reliability.evidence":"查看有時間戳記的驗收證據快照（JSON）",
    },
    en:{
      "reliability.title":"Data update status", "reliability.site":"Website response", "reliability.online":"Available", "reliability.unknown":"No verified evidence yet",
      "reliability.run":"Latest collection run", "reliability.success":"Latest successful check", "reliability.capture":"Pre-open archive summary", "reliability.closes":"Close updates",
      "reliability.loading":"Loading status…", "reliability.unavailable":"Status unavailable. Refresh the overview to retry.",
      "reliability.captureValue":"{day} · {count}/5 scenarios", "reliability.invalid":"Duplicate or late records detected", "reliability.missing":"Missing: {items}",
      "reliability.collecting":"Pre-open capture is still open; missing scenarios await collection.",
      "reliability.closeValue":"{due} due, unscored · {future} awaiting publication", "reliability.alerts":"Current monitoring: {items}", "reliability.noAlerts":"No alerts reported by current monitoring.",
      "reliability.schedule_stale":"Collection overdue", "reliability.preopen_missing":"Pre-open scenario missing", "reliability.actual_close_missing":"Due close missing", "reliability.source_unavailable":"Data source failure", "reliability.no_checks":"No collection checks yet",
      "reliability.note":"A successful check does not verify all historical data, notification delivery, or five-day acceptance.",
      "reliability.acceptance":"V1.1 five-session acceptance", "reliability.day":"{day}: {count}/5 archived · Day 5 {target} · {state}",
      "reliability.pending":"pending / not mature", "reliability.due":"Due; full evidence still requires review", "reliability.future":"Origin date has not occurred", "reliability.evidence":"Timestamped acceptance evidence snapshot (JSON)",
    }
  });
  const t=(key,values)=>i18n.t(`reliability.${key}`,values);
  const el=(tag,text,cls)=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e};
  let scores=null,calendar=null,web=null,health=null,loading=true,generation=0,controller,started=false;
  const stamp=value=>Number.isFinite(Date.parse(value))?new Intl.DateTimeFormat(i18n.getLanguage(),{timeZone:"Asia/Taipei",dateStyle:"short",timeStyle:"medium",hour12:false}).format(new Date(value)):t("unknown");
  function render(){
    root.replaceChildren(el("h3",t("title")));
    const grid=el("div",null,"reliability-grid");root.append(grid);
    const cell=(label,value)=>{const box=el("div",null,"reliability-cell");box.append(el("span",t(label)),el("strong",value));grid.append(box)};
    cell("site",loading?t("loading"):web?.status==="ok"?t("online"):t("unknown"));
    cell("run",stamp(health?.last_checked_at));cell("success",stamp(health?.last_successful_checked_at));
    const market=Array.isArray(calendar?.markets)?calendar.markets.find(m=>m.exchange==="XTAI"):null;
    const now=Date.parse(calendar?.checked_at);const ready=scores?.status==="ready"&&market&&Number.isFinite(now);
    let day=null,summary=null;
    if(ready){const today=new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Taipei",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date(now));day=market.next_session===today?today:market.latest_publishable_session;summary=capture(scores.predictions,day)}
    cell("capture",summary?t("captureValue",{day,count:summary.count}):t("unknown"));
    const pending=(scores?.predictions||[]).filter(r=>r.status==="pending");
    const due=ready?pending.filter(r=>r.target_date<=market.latest_publishable_session).length:null;
    cell("closes",due==null?t("unknown"):t("closeValue",{due,future:pending.length-due}));
    if(summary?.invalid)root.append(el("p",t("invalid"),"reliability-warning"));
    if(summary?.missing.length)root.append(el("p",now<Date.parse(`${day}T09:00:00+08:00`)?t("collecting"):t("missing",{items:summary.missing.map(([s,c])=>`${s} / ${c}`).join(", ")}),"reliability-warning"));
    const alerts=health?.status==="ready"&&Array.isArray(health.alerts)?health.alerts:null;
    root.append(el("p",loading?t("loading"):!alerts?t("unavailable"):alerts.length?t("alerts",{items:alerts.map(a=>`${t(a.code)}${a.symbol?` · ${a.symbol}`:""}${a.reason?` (${a.reason})`:""}`).join("; ")}):t("noAlerts"),alerts?.length?"reliability-warning":"overview-date"));
    root.append(el("p",t("note"),"overview-date"));
    const detail=el("details"),list=el("ul");detail.append(el("summary",t("acceptance")),list);
    origins.forEach((origin,index)=>{
      const c=ready?capture(scores.predictions,origin):null;
      const future=Number.isFinite(now)&&now<Date.parse(`${origin}T09:00:00+08:00`);
      const mature=Number.isFinite(now)&&now>=Date.parse(`${fifth[index]}T15:00:00+08:00`);
      list.append(el("li",t("day",{day:origin,count:c?c.count:"—",target:fifth[index],state:t(future?"future":mature?"due":"pending")})));
    });
    const link=el("a",t("evidence"));link.href="/static/acceptance-evidence.json";link.target="_blank";link.rel="noopener";detail.append(link);root.append(detail);
  }
  async function load(){
    started=true;const current=++generation;controller?.abort();controller=new AbortController();const signal=controller.signal;
    web=null;health=null;loading=true;render();const timer=setTimeout(()=>{if(current===generation)controller.abort()},15000);
    try{
      const read=async path=>{const r=await fetch(path,{cache:"no-store",signal});if(!r.ok)throw new Error("unavailable");return r.json()};
      const values=await Promise.allSettled([read("/api/health"),read("/api/reliability/health")]);if(current!==generation)return;
      web=values[0].status==="fulfilled"?values[0].value:null;health=values[1].status==="fulfilled"?values[1].value:null;
    }finally{clearTimeout(timer);if(current===generation){loading=false;render()}}
  }
  window.addEventListener("stockpredict-scoreboard-loading",()=>{scores=null;calendar=null;load()});
  window.addEventListener("stockpredict-scoreboard",event=>{scores=event.detail.scores;calendar=event.detail.calendar;render()});
  window.addEventListener("DOMContentLoaded",()=>{if(!started)load()});
  i18n.subscribe(render);render();
})();
