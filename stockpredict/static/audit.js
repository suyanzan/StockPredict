(() => {
  "use strict";
  const i18n=window.StockPredictI18n;
  i18n.register({
    "zh-TW": {
      "audit.detail":"查核詳情","audit.predictionDetail":"原始預測查核詳情","audit.close":"關閉",
      "audit.loading":"正在讀取…","audit.error":"暫時無法取得資料，請稍後重試。",
      "audit.savedAt":"原始保存時間（台北）","audit.origin":"預測起日","audit.base":"原始前收盤",
      "audit.model":"模型版本","audit.training":"訓練資料","audit.source":"來源",
      "audit.reference":"原始參考行情","audit.required":"所需美股交易日","audit.none":"未保存／不適用",
      "audit.days":"交易日數,目標交易日,原始預測（TWD）,實際收盤（TWD）,實際取得時間（台北）,狀態,收盤來源",
      "audit.published":"已取得","audit.awaiting_publication":"待公布（不計分）","audit.missing_actual_close":"缺少該日收盤（不計分）",
      "audit.immutable":"原始預測不可覆寫；僅第 1、5 個交易日納入正式成績。",
      "audit.events":"除息與分割事件","audit.dividend":"除息／現金股利","audit.split":"股票分割／合併",
      "audit.eventsNote":"事件由 Yahoo 提供，可能缺漏；未標記不代表沒有事件。價格及成績不因標記而重寫，圖表 D＝除息、S＝分割。",
      "audit.eventsCurrent":"此處事件是目前來源的查詢結果，不代表盤前已知。",
      "audit.eventUnavailable":"事件來源無法確認，不能判定沒有事件。",
      "audit.outside_source_coverage":"超出事件來源涵蓋期間",
      "audit.eventNone":"來源在所示涵蓋期間未回報事件。",
      "audit.notRequested":"示範／CSV 不自動套用真實市場事件。",
      "audit.eventColumns":"日期,來源回報類型,內容,來源",
      "audit.coverage":"來源涵蓋期間","audit.checked":"本次查詢時間（台北）",
      "audit.versionInfo":"版本與資料指紋","audit.save":"保存本次報告","audit.csv":"匯出逐筆 CSV",
      "audit.json":"下載完整快照","audit.replay":"從快照重播核對","audit.savedReports":"最近已保存報告",
      "audit.load":"載入報告","audit.refresh":"更新清單",
      "audit.publicNote":"保存的是公開行情分析，所有訪客可查閱；報告不可覆寫，最多保存 200 份。資料庫不可用時仍可匯出當次 CSV。",
      "audit.saved":"已保存","audit.fingerprint":"資料與結果指紋","audit.draft":"尚未保存；伺服器草稿保留約 15 分鐘。",
      "audit.replayMatch":"重播結果與已保存報告一致，未重新下載行情。",
      "audit.replayMismatch":"重播與已保存結果不一致；原始報告已保留，請停止依賴本次重播結果。",
      "audit.backtest_draft_expired":"報告草稿已過期或服務已重啟，請重新執行回測後保存。",
      "audit.backtest_storage_unavailable":"報告儲存空間尚未就緒或權限不足；仍可下載當次 CSV。",
      "audit.backtest_engine_mismatch":"目前引擎版本與保存版本不同，保留原始報告及下載，無法用新版冒充舊版重播。",
      "audit.backtest_archive_full":"公開報告已達保存上限；可匯出本次 CSV，已保存的快照仍可下載。",
      "audit.backtest_save_rate_limited":"保存過於頻繁，請稍候一分鐘再試。",
      "audit.backtest_run_not_found":"找不到已保存報告。","audit.prediction_not_found":"找不到這筆預測。",
      "audit.backtest_snapshot_corrupted":"快照內容與保存指紋不一致，已停止重播。",
      "audit.scoreboard_storage_unavailable":"預測資料庫暫時無法使用。",
      "audit.selectReport":"請選擇已保存報告","audit.replayIncompatible":"版本已不同，原始報告與快照仍可下載。",
    },
    en: {
      "audit.detail":"Audit details","audit.predictionDetail":"Original prediction audit","audit.close":"Close",
      "audit.loading":"Loading…","audit.error":"Data temporarily unavailable. Please retry later.",
      "audit.savedAt":"Originally saved at (Taipei)","audit.origin":"Forecast origin","audit.base":"Original base close",
      "audit.model":"Model version","audit.training":"Training data","audit.source":"Source",
      "audit.reference":"Original reference quotes","audit.required":"Required US session","audit.none":"Not recorded / not applicable",
      "audit.days":"Trading days,Target session,Original prediction (TWD),Actual close (TWD),Actual observed at (Taipei),Status,Actual source",
      "audit.published":"Available","audit.awaiting_publication":"Pending publication (excluded)","audit.missing_actual_close":"Session close missing (excluded)",
      "audit.immutable":"Original predictions are immutable. Only trading days 1 and 5 enter official scores.",
      "audit.events":"Dividends and stock splits","audit.dividend":"Ex-dividend / cash dividend","audit.split":"Stock split / reverse split",
      "audit.eventsNote":"Events are reported by Yahoo and may be incomplete; no marker does not prove no event. Markers do not rewrite prices or scores. Chart D = dividend, S = split.",
      "audit.eventsCurrent":"Event information is retrieved now; it is not evidence of pre-open knowledge.",
      "audit.eventUnavailable":"Event source unavailable; absence of events cannot be confirmed.",
      "audit.outside_source_coverage":"Outside event source coverage",
      "audit.eventNone":"No events reported by the source within the shown coverage.",
      "audit.notRequested":"Real-market events are not automatically applied to demo or CSV data.",
      "audit.eventColumns":"Date,Provider-reported type,Details,Source",
      "audit.coverage":"Source coverage","audit.checked":"Checked at (Taipei)",
      "audit.versionInfo":"Version and data fingerprints","audit.save":"Save this report","audit.csv":"Export records CSV",
      "audit.json":"Download full snapshot","audit.replay":"Replay saved snapshot","audit.savedReports":"Recently saved reports",
      "audit.load":"Load report","audit.refresh":"Refresh list",
      "audit.publicNote":"Saved reports contain public market analysis and are visible to all visitors. Reports are immutable, with a 200-report cap. CSV export remains available without storage.",
      "audit.saved":"Saved","audit.fingerprint":"Data and result fingerprint","audit.draft":"Unsaved; server draft is retained for about 15 minutes.",
      "audit.replayMatch":"Replay matches the saved report without downloading market data again.",
      "audit.replayMismatch":"Replay differs from the saved result. Original report retained; do not rely on this replay.",
      "audit.backtest_draft_expired":"Draft expired or service restarted. Run the backtest again before saving.",
      "audit.backtest_storage_unavailable":"Report storage is not ready or lacks permissions. Current CSV export is still available.",
      "audit.backtest_engine_mismatch":"Engine version differs from the saved version. Original reports and downloads remain available; replay requires the matching engine.",
      "audit.backtest_archive_full":"Public report archive is full. Export the current CSV; existing saved snapshots remain downloadable.",
      "audit.backtest_save_rate_limited":"Too many saves. Retry in one minute.",
      "audit.backtest_run_not_found":"Saved report not found.","audit.prediction_not_found":"Prediction not found.",
      "audit.backtest_snapshot_corrupted":"Snapshot integrity check failed; replay stopped.",
      "audit.scoreboard_storage_unavailable":"Prediction storage is temporarily unavailable.",
      "audit.selectReport":"Choose a saved report","audit.replayIncompatible":"Engine version changed; original report and snapshot remain downloadable.",
    }
  });
  const t=key=>i18n.t(`audit.${key}`), $=id=>document.getElementById(id);
  const num=v=>v==null?"—":new Intl.NumberFormat(i18n.getLanguage(),{maximumFractionDigits:4}).format(v);
  const stamp=v=>v?new Intl.DateTimeFormat(i18n.getLanguage(),{timeZone:"Asia/Taipei",dateStyle:"short",timeStyle:"medium",hour12:false}).format(new Date(v)):"—";
  function paragraph(parent,text){const p=document.createElement("p");p.textContent=text;parent.append(p);return p;}
  function table(parent,head){const wrap=document.createElement("div");wrap.className="table-scroll";const table=document.createElement("table"),thead=document.createElement("thead"),body=document.createElement("tbody"),tr=document.createElement("tr");for(const label of head){const th=document.createElement("th");th.scope="col";th.textContent=label;tr.append(th);}thead.append(tr);table.append(thead,body);wrap.append(table);parent.append(wrap);return body;}
  function row(parent,values){const tr=document.createElement("tr");for(const value of values){const td=document.createElement("td");td.textContent=value;tr.append(td);}parent.append(tr);}
  function reason(code){const translated=t(code);return translated.startsWith("audit.")?t("error"):translated;}
  function renderEvents(parent,actions){
    parent.replaceChildren();
    if(!actions || actions.status==="not_requested"){paragraph(parent,t("notRequested"));return;}
    if(actions.status==="loading"){paragraph(parent,t("loading"));return;}
    paragraph(parent,t("eventsNote"));
    paragraph(parent,`${t("source")}: ${actions.source||"Yahoo Finance"} · ${t("checked")}: ${stamp(actions.checked_at)}`);
    if(actions.status!=="ready"){paragraph(parent,t("eventUnavailable"));return;}
    paragraph(parent,`${t("coverage")}: ${actions.coverage_start} – ${actions.coverage_end}`);
    if(!actions.events.length){paragraph(parent,t("eventNone"));return;}
    const body=table(parent,t("eventColumns").split(","));
    for(const e of actions.events)row(body,[e.date,t(e.type),e.type==="dividend"?`${num(e.amount)} ${e.currency}`:`${num(e.numerator)} : ${num(e.denominator)}`,e.source]);
  }
  let detail=null,detailError=null,detailSequence=0,currentAnalysis=null;
  function renderDetail(){
    const body=$("prediction-detail-body");body.replaceChildren();
    if(!detail){paragraph(body,detailError?reason(detailError):t("loading"));return;}
    paragraph(body,`#${detail.id} · ${detail.symbol} · ${i18n.t(`score.${detail.scenario}`)}`);
    for(const [label,value] of [["savedAt",stamp(detail.created_at)],["origin",detail.origin_date],["base",`${detail.base_date} · ${num(detail.base_close)} TWD`],["model",detail.model_version],["training",`${detail.training.start} – ${detail.training.end} (${detail.training.samples})`],["source",detail.source],["required",detail.required_us_session_date||t("none")]])paragraph(body,`${t(label)}: ${value}`);
    paragraph(body,t("immutable"));
    const rows=table(body,t("days").split(","));
    for(const p of detail.forecast)row(rows,[p.horizon,p.target_date,num(p.predicted_close),num(p.actual_close),stamp(p.observed_at),p.pending_reason?t(p.pending_reason):t("published"),p.actual_source||"—"]);
    const heading=document.createElement("h3");heading.textContent=t("reference");body.append(heading);
    if(!detail.reference_quotes.length){let message=detail.reference_reason?i18n.t(`overnight.reason.${detail.reference_reason}`):t("none");if(message.startsWith("overnight.reason."))message=t("error");paragraph(body,message);}
    for(const q of detail.reference_quotes)paragraph(body,`${q.symbol} · ${q.session_date} · ${num(q.close)} ${q.currency} · ${detail.reference_source||"—"}`);
    const advanced=document.createElement("details"),summary=document.createElement("summary"),pre=document.createElement("pre");summary.textContent=t("versionInfo");pre.textContent=detail.engine_manifest?JSON.stringify(detail.engine_manifest,null,2):t("none");pre.style.whiteSpace="pre-wrap";advanced.append(summary,pre);body.append(advanced);
    paragraph(body,t("eventsCurrent"));const events=document.createElement("div");body.append(events);renderEvents(events,detail.corporate_actions||{status:"loading"});
  }
  async function showPrediction(id){
    const sequence=++detailSequence;detail=null;detailError=null;renderDetail();$("prediction-detail").showModal();
    try{
      const response=await fetch(`/api/predictions/${id}`,{cache:"no-store"}),data=await response.json();
      if(sequence!==detailSequence)return;if(!response.ok)throw new Error(data.reason||"error");detail=data;renderDetail();
      const events=await fetch(`/api/corporate-actions?symbol=${encodeURIComponent(data.symbol)}`,{cache:"no-store"}).then(r=>r.json()).catch(()=>({status:"unavailable"}));
      if(sequence===detailSequence){detail.corporate_actions=events;renderDetail();}
    }catch(error){if(sequence===detailSequence){detailError=error.message;renderDetail();}}
  }
  $("prediction-detail-close").addEventListener("click",()=>$("prediction-detail").close());
  $("prediction-detail").addEventListener("close",()=>{detailSequence++;});
  window.addEventListener("stockpredict-analysis",async event=>{
    const value=event.detail;currentAnalysis=value;
    if(["demo","csv"].includes(value.source)){value.corporate_actions={status:"not_requested",events:[]};renderEvents($("analysis-actions"),value.corporate_actions);return;}
    if(value.corporate_actions){renderEvents($("analysis-actions"),value.corporate_actions);return;}
    value.corporate_actions={status:"loading",events:[]};renderEvents($("analysis-actions"),value.corporate_actions);
    const actions=await fetch(`/api/corporate-actions?symbol=${encodeURIComponent(value.symbol)}`,{cache:"no-store"}).then(r=>r.json()).catch(()=>({status:"unavailable",events:[]}));
    value.corporate_actions=actions;
    if(currentAnalysis===value){renderEvents($("analysis-actions"),actions);window.dispatchEvent(new CustomEvent("stockpredict-corporate-actions-ready",{detail:{analysis:value,actions}}));}
  });
  i18n.subscribe(()=>{if($("prediction-detail").open)renderDetail();if(currentAnalysis)renderEvents($("analysis-actions"),currentAnalysis.corporate_actions);});
  window.StockPredictAudit={t,num,stamp,reason,renderEvents,showPrediction};
})();
