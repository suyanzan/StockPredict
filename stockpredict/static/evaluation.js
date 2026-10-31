(() => {
  "use strict";
  const i18n = window.StockPredictI18n;
  i18n.register({
    "zh-TW": {
      "evaluation.paired": "同日期公平比較", "evaluation.all": "各自可用資料的成績（樣本可能不同）",
      "evaluation.pairedNote": "僅比較預測起日、目標日、期間與實際收盤相同的純台股及 ADR；覆蓋率分母為已計分的純台股筆數。",
      "evaluation.columns": "股票,交易日數,共同樣本,ADR 覆蓋率,純台股 MAE,ADR MAE,MAE 改善,純台股方向,ADR 方向,前收盤基準 MAE",
      "evaluation.empty": "尚無可比較的已公布樣本。", "evaluation.health": "排程狀態與提醒",
      "evaluation.healthy": "目前未偵測到逾期的排程或資料問題。",
      "evaluation.no_checks": "尚無收集紀錄，請執行收集排程。",
      "evaluation.schedule_stale": "收集排程已逾期（含 45 分鐘寬限），請檢查 GitHub Actions。",
      "evaluation.preopen_missing": "盤前預測未保存；不以盤後預測補成績。",
      "evaluation.actual_close_missing": "已過收盤收集寬限，仍有缺少實際收盤的紀錄。",
      "evaluation.source_unavailable": "最近一次行情來源不完整或無法取得，請查看資料狀態。",
      "evaluation.period": "測試期間", "evaluation.month1": "1 個月（30 日）", "evaluation.month3": "3 個月（90 日）",
      "evaluation.month6": "6 個月（180 日）", "evaluation.month12": "12 個月（365 日）",
      "evaluation.coverage": "可回測交易日／要求交易日", "evaluation.partial": "期間涵蓋不完整，缺少訓練資料的日期已跳過。",
      "evaluation.source": "資料來源", "evaluation.review": "模型評估：先驗證選擇，再獨立測試",
      "evaluation.reviewNote": "固定比較前收盤、現行 AR(5)、60／120 筆訓練窗；先需 120 筆訓練歷史，各至少 20 筆驗證與獨立測試，排除跨入測試期的驗證答案。不自動更改正式模型。",
      "evaluation.reviewColumns": "候選方法,驗證樣本,驗證 MAE,獨立測試樣本,獨立測試 MAE,獨立測試方向",
      "evaluation.insufficient_evidence": "樣本不足，尚無法評估模型調整。",
      "evaluation.baseline_beats_model": "獨立測試顯示前收盤基準優於現行模型，應先參考基準。",
      "evaluation.candidate_for_prospective_test": "候選方法符合改善門檻，建議先做未來盤前測試。",
      "evaluation.retain_current_pending_evidence": "尚無足夠改善證據，暫不更改正式模型。",
      "evaluation.previous_close": "維持前收盤", "evaluation.expanding_ar5": "現行 AR(5)（累積訓練）",
      "evaluation.ar5_60": "AR(5) 最近 60 筆", "evaluation.ar5_120": "AR(5) 最近 120 筆",
      "evaluation.selected": "僅依驗證期選出", "evaluation.holdout": "獨立測試起日",
      "evaluation.interval": "獨立測試 MAE 差的 95% 區間（負值較佳）",
      "evaluation.threshold": "候選須較前收盤與現行模型 MAE 都改善至少 5%，且差值區間上界小於零。區間採依期間分塊的 bootstrap，仍不保證未來表現。",
    },
    en: {
      "evaluation.paired": "Fair comparison · Same dates", "evaluation.all": "Available-data scores (sample sets may differ)",
      "evaluation.pairedNote": "Pair only identical origins, targets, horizons and actual closes. ADR coverage uses scored Taiwan-only records as the denominator.",
      "evaluation.columns": "Stock,Trading days,Paired samples,ADR coverage,Taiwan MAE,ADR MAE,MAE improvement,Taiwan direction,ADR direction,Previous-close baseline MAE",
      "evaluation.empty": "No matching published samples yet.", "evaluation.health": "Collection health and alerts",
      "evaluation.healthy": "No overdue collection or data issues detected.",
      "evaluation.no_checks": "No collection records yet; run the collection job.",
      "evaluation.schedule_stale": "Collection overdue beyond the 45-minute grace period. Check GitHub Actions.",
      "evaluation.preopen_missing": "Pre-open forecast not saved. Post-open forecasts cannot replace it.",
      "evaluation.actual_close_missing": "Actual closing prices remain missing after the collection grace period.",
      "evaluation.source_unavailable": "Latest market source is incomplete or unavailable. Check data status.",
      "evaluation.period": "Test period", "evaluation.month1": "1 month (30 days)", "evaluation.month3": "3 months (90 days)",
      "evaluation.month6": "6 months (180 days)", "evaluation.month12": "12 months (365 days)",
      "evaluation.coverage": "Tested / requested sessions", "evaluation.partial": "Partial period coverage; origins without sufficient training data were skipped.",
      "evaluation.source": "Source", "evaluation.review": "Model review · Validation selection, then independent holdout",
      "evaluation.reviewNote": "Fixed candidates: previous close, current AR(5), 60/120-close training windows. Require 120 preceding training closes and at least 20 validation and 20 holdout samples. Validation outcomes crossing into holdout are purged. Production models are not automatically changed.",
      "evaluation.reviewColumns": "Candidate,Validation samples,Validation MAE,Holdout samples,Holdout MAE,Holdout direction",
      "evaluation.insufficient_evidence": "Insufficient samples to assess a model change.",
      "evaluation.baseline_beats_model": "Previous-close baseline outperforms the current model on the independent holdout; use it as a reference.",
      "evaluation.candidate_for_prospective_test": "Candidate meets improvement criteria; evaluate in future pre-open forecasts first.",
      "evaluation.retain_current_pending_evidence": "No sufficient improvement evidence; keep production unchanged.",
      "evaluation.previous_close": "Previous close", "evaluation.expanding_ar5": "Current expanding AR(5)",
      "evaluation.ar5_60": "AR(5), last 60 closes", "evaluation.ar5_120": "AR(5), last 120 closes",
      "evaluation.selected": "Selected on validation only", "evaluation.holdout": "Holdout starts",
      "evaluation.interval": "95% interval for holdout MAE difference (negative is better)",
      "evaluation.threshold": "A candidate needs at least 5% lower MAE than both baseline and incumbent, with each difference interval entirely below zero. Intervals use horizon-sized block bootstrap; future performance is not guaranteed.",
    }
  });
  const t = key => i18n.t(`evaluation.${key}`);
  const num = n => n == null ? "—" : n.toFixed(2);
  const pct = n => n == null ? "—" : `${num(n)}%`;
  function p(parent, text) {const e=document.createElement("p");e.textContent=text;parent.append(e);return e;}
  function table(parent, columns) {
    const wrap=document.createElement("div");wrap.className="table-scroll";
    const table=document.createElement("table"), head=document.createElement("thead"), body=document.createElement("tbody");
    const tr=document.createElement("tr");
    for(const title of columns){const th=document.createElement("th");th.scope="col";th.textContent=title;tr.append(th);}
    head.append(tr);table.append(head,body);wrap.append(table);parent.append(wrap);return body;
  }
  function row(parent, values){const tr=document.createElement("tr");for(const v of values){const td=document.createElement("td");td.textContent=v;tr.append(td);}parent.append(tr);}
  function comparison(parent, groups){
    parent.replaceChildren();
    if(!groups?.length){p(parent,t("empty"));return;}
    const body=table(parent,t("columns").split(","));
    for(const c of groups) row(body,[c.symbol,c.horizon,c.paired_samples,
      c.adr_coverage == null ? "—" : `${c.paired_samples}/${c.taiwan_scored} (${pct(c.adr_coverage*100)})`,
      num(c.taiwan.mae),num(c.adr.mae),pct(c.mae_improvement_pct),
      pct(c.taiwan.direction_accuracy == null ? null : c.taiwan.direction_accuracy*100),
      pct(c.adr.direction_accuracy == null ? null : c.adr.direction_accuracy*100),num(c.taiwan.baseline_mae)]);
  }
  function alerts(parent, items, ready){
    parent.replaceChildren();if(!ready)return;
    if(!items?.length){p(parent,t("healthy"));return;}
    for(const a of items){const e=p(parent,`${t(a.code)} ${a.symbol||""} ${a.scenario?i18n.t(`score.${a.scenario}`):""} ${a.session_date||a.oldest_target||""}${a.count?` (${a.count})`:""}`);e.dataset.severity=a.severity;}
  }
  function review(parent, report){
    parent.replaceChildren();if(!report)return;
    p(parent,t("threshold"));
    for(const r of report.results){
      p(parent,`${r.horizon} · ${t(r.recommendation)}${r.selected_on_validation?` · ${t("selected")}: ${t(r.selected_on_validation)} · ${t("holdout")}: ${r.holdout_start}`:""}`);
      if(!r.candidates.length)continue;
      const body=table(parent,t("reviewColumns").split(","));
      for(const c of r.candidates)row(body,[t(c.candidate),c.validation.samples,num(c.validation.mae),c.holdout.samples,num(c.holdout.mae),pct(c.holdout.direction_accuracy*100)]);
      for(const [reference,bounds] of Object.entries(r.holdout_mae_delta_95pct||{}))p(parent,`${t("interval")} · ${t(reference)}: [${bounds.map(num).join(", ")}]`);
    }
  }
  window.StockPredictEvaluation={comparison,alerts,review,t};
})();
