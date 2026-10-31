(() => {
  "use strict";
  const audit=window.StockPredictAudit,$=id=>document.getElementById(id);
  let active=window.StockPredictHistorical.getReport(),busy=false,message=null,runs=[];
  function render(){
    const loading=busy||window.StockPredictHistorical.isLoading();
    $("report-save").disabled=loading||!active?.archive?.draft_id||active.archive.saved;
    $("report-csv").disabled=loading||!active;
    $("report-json").disabled=$("report-replay").disabled=loading||!active?.archive?.run_id;
    $("report-load").disabled=loading||!$("report-saved").value;$("report-refresh").disabled=loading;
    const a=active?.archive;
    $("report-archive-status").textContent=message?audit.reason(message):a?`${audit.t(a.saved?"saved":"draft")} ${a.run_id||""}${a.saved_at?` · ${audit.stamp(a.saved_at)}`:""} · ${audit.t("fingerprint")}: ${a.fingerprint}${a.replay_compatible===false?` · ${audit.t("replayIncompatible")}`:""}`:"";
  }
  async function request(url,options={}){
    const response=await fetch(url,{cache:"no-store",...options});const data=await response.json();
    if(!response.ok)throw new Error(data.reason||"error");return data;
  }
  async function refresh(){
    const selected=$("report-saved").value;
    try{const data=await request("/api/backtest-runs");runs=data.runs;}
    catch(error){runs=[];message=error.message;}
    $("report-saved").replaceChildren();const first=document.createElement("option");first.value="";first.textContent=audit.t("selectReport");$("report-saved").append(first);
    for(const r of runs){const option=document.createElement("option");option.value=r.id;option.textContent=`${r.symbol} · ${r.months} · ${audit.stamp(r.saved_at)} · ${r.id.slice(0,8)}`;$("report-saved").append(option);}
    $("report-saved").value=selected;render();
  }
  function download(blob,name){const url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  const fields=["origin_date","symbol","scenario","horizon","simulated_cutoff","target_date","base_close","predicted_close","actual_close","status","pending_reason","error","absolute_error_pct","direction_hit","corporate_action_dates","corporate_action_types","corporate_action_status"];
  function cell(value){let text=value==null?"":String(value);if(typeof value==="string"&&/^[=+\-@\t\r]/.test(text))text="'"+text;return '"'+text.replaceAll('"','""')+'"';}
  $("report-csv").addEventListener("click",()=>{
    if(!active)return;const lines=[fields.map(cell).join(",")];
    for(const r of active.predictions){const row={...r,corporate_action_dates:[...new Set((r.corporate_actions||[]).map(e=>e.date))].sort().join(";"),corporate_action_types:[...new Set((r.corporate_actions||[]).map(e=>e.type))].sort().join(";")};lines.push(fields.map(k=>cell(row[k])).join(","));}
    download(new Blob(["\ufeff"+lines.join("\r\n")+"\r\n"],{type:"text/csv;charset=utf-8"}),`backtest-${active.archive?.run_id||`${active.symbol}-${active.months}`}.csv`);
  });
  $("report-save").addEventListener("click",async()=>{
    if(busy||!active?.archive?.draft_id)return;const original=active;busy=true;message="loading";render();
    try{const result=await request("/api/backtest-runs",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({draft_id:original.archive.draft_id})});
      if(active===original)window.StockPredictHistorical.showReport(result.report);message=null;await refresh();
    }catch(error){message=error.message;}finally{busy=false;render();}
  });
  $("report-load").addEventListener("click",async()=>{
    const id=$("report-saved").value;if(!id||busy)return;const original=active;busy=true;message="loading";render();
    try{const result=await request(`/api/backtest-runs/${encodeURIComponent(id)}`);if(active===original)window.StockPredictHistorical.showReport(result.report);message=null;}
    catch(error){message=error.message;}finally{busy=false;render();}
  });
  $("report-json").addEventListener("click",async()=>{
    if(!active?.archive?.run_id||busy)return;const id=active.archive.run_id;busy=true;message="loading";render();
    try{const result=await request(`/api/backtest-runs/${id}`);download(new Blob([JSON.stringify(result,null,2)],{type:"application/json"}),`backtest-${id}-snapshot.json`);message=null;}
    catch(error){message=error.message;}finally{busy=false;render();}
  });
  $("report-replay").addEventListener("click",async()=>{
    if(!active?.archive?.run_id||busy)return;const original=active;busy=true;message="loading";render();
    try{const result=await request(`/api/backtest-runs/${original.archive.run_id}/replay`,{method:"POST"});if(active===original)message=result.matches_saved_result?"replayMatch":"replayMismatch";}
    catch(error){message=error.message;}finally{busy=false;render();}
  });
  $("report-refresh").addEventListener("click",refresh);$("report-saved").addEventListener("change",render);
  window.addEventListener("stockpredict-historical-report",event=>{if(active!==event.detail)message=null;active=event.detail;render();});
  window.StockPredictI18n.subscribe(()=>{render();const first=$("report-saved").options[0];if(first)first.textContent=audit.t("selectReport");});
  render();refresh();
})();
