(() => {
  "use strict";
  const i18n = window.StockPredictI18n;
  i18n.register({
    "zh-TW": {
      "history.title": "最近 30 日歷史回測", "history.run": "執行歷史回測",
      "history.description": "逐日使用當時以前至少 60 筆歷史收盤訓練，測試第 1、5 個交易日；純台股與 ADR 情境分開。",
      "history.idle": "按下按鈕取得真實歷史行情並回測。", "history.loading": "正在讀取歷史行情並逐日回測，首次可能需要 20–60 秒…",
      "history.note": "這是事後逐日模擬，歷史行情可能經過修訂，公布時間採日曆假設。結果不寫入盤前成績看板；未到期或缺資料不計分。",
      "history.details": "逐日結果與缺資料原因", "history.period": "測試期間", "history.asof": "行情截至",
      "history.training": "逐日訓練筆數", "history.cutoff": "模擬決策日（台北）",
      "history.error": "歷史回測暫時無法完成，請稍後重試。", "history.baseline": "維持前收盤 MAE（TWD）",
      "history.missing": "缺資料／未使用情境", "history.empty": "無符合條件的回測樣本；請查看缺資料原因。",
      "history.insufficient_or_missing_training_history": "訓練資料不足 60 筆，或缺少前一交易日收盤",
      "history.missing_actual_close": "缺少該日收盤（不計分）",
    },
    en: {
      "history.title": "Historical backtest · Last 30 days", "history.run": "Run historical backtest",
      "history.description": "Train each day on at least 60 preceding historical closes; evaluate trading days 1 and 5. Taiwan-only and ADR scenarios are separate.",
      "history.idle": "Run to fetch real historical prices and evaluate them.", "history.loading": "Fetching historical prices and running walk-forward tests; the first request may take 20–60 seconds…",
      "history.note": "This is a retrospective simulation. Historical prices may be revised, and availability times are calendar assumptions. Results do not enter the live pre-open scoreboard. Pending or missing actuals are excluded.",
      "history.details": "Daily results and missing-data reasons", "history.period": "Test period", "history.asof": "Quotes through",
      "history.training": "Daily training samples", "history.cutoff": "Simulated decision date (Taipei)",
      "history.error": "Historical backtest unavailable. Please retry later.", "history.baseline": "Previous-close baseline MAE (TWD)",
      "history.missing": "Missing data / skipped scenario", "history.empty": "No eligible samples; check missing-data reasons.",
      "history.insufficient_or_missing_training_history": "Fewer than 60 training closes, or previous session close missing",
      "history.missing_actual_close": "Session close missing (excluded)",
    }
  });
  const $ = id => document.getElementById(id);
  const t = key => i18n.t(`history.${key}`);
  const score = key => i18n.t(`score.${key}`);
  const number = value => value == null ? "—" : value.toFixed(2);
  const percent = value => value == null ? "—" : `${number(value)}%`;
  let report = null, state = "idle", loading = false;
  function row(parent, values, heading = false) {
    const tr = document.createElement("tr");
    for (const value of values) {
      const td = document.createElement(heading ? "th" : "td");
      td.textContent = value; if (heading) td.scope = "col"; tr.append(td);
    }
    parent.append(tr);
  }
  function render() {
    for (const id of ["historical-head", "historical-summary", "historical-record-head", "historical-records", "historical-skipped"]) $(id).replaceChildren();
    const columns = score("columns").split(",");
    row($("historical-head"), [...columns, t("baseline")], true);
    row($("historical-record-head"), [t("cutoff"), ...score("recordColumns").split(",").filter((_, i) => i !== 3)], true);
    $("historical-status").textContent = t(state);
    if (!report) return;
    const counts = report.training.map(r => r.training_samples);
    $("historical-status").textContent = `${report.symbol} · ${t("period")}: ${report.test_start} – ${report.test_end} · ${t("asof")}: ${report.data_as_of || "—"} · ${t("training")}: ${counts.length ? `${Math.min(...counts)}–${Math.max(...counts)}` : "—"}${counts.length ? "" : ` · ${t("empty")}`}`;
    for (const s of report.summary) row($("historical-summary"), [s.symbol, score(s.scenario), s.horizon, s.samples, s.pending, number(s.mae), percent(s.mape), percent(s.direction_accuracy == null ? null : s.direction_accuracy * 100), number(s.baseline_mae)]);
    for (const r of report.predictions) {
      const decision = new Intl.DateTimeFormat("sv-SE", {timeZone:"Asia/Taipei"}).format(new Date(r.simulated_cutoff));
      row($("historical-records"), [decision, r.symbol, score(r.scenario), r.horizon, r.target_date, number(r.predicted_close), r.actual_close == null ? (r.pending_reason === "missing_actual_close" ? t("missing_actual_close") : score("pending")) : number(r.actual_close), number(r.error), r.direction_hit == null ? "—" : score(r.direction_hit ? "hit" : "miss")]);
    }
    for (const skip of report.skipped) {
      let reason = t(skip.reason);
      if (reason.startsWith("history.")) reason = score(skip.reason);
      if (reason.startsWith("score.")) reason = `${score("error")} (${skip.reason})`;
      const p = document.createElement("p");
      p.textContent = `${skip.date} · ${skip.scenario === "all" ? t("missing") : score(skip.scenario)} · ${reason}`;
      $("historical-skipped").append(p);
    }
  }
  $("historical-run").addEventListener("click", async () => {
    if (loading) return;
    loading = true; state = "loading"; report = null;
    $("historical-run").disabled = $("historical-symbol").disabled = true; render();
    try {
      const response = await fetch(`/api/historical-backtest?symbol=${encodeURIComponent($("historical-symbol").value)}`, {cache:"no-store"});
      const data = await response.json();
      if (!response.ok) throw new Error(data.reason || "unavailable");
      report = data; state = "idle";
    } catch { state = "error"; }
    finally { loading = false; $("historical-run").disabled = $("historical-symbol").disabled = false; render(); }
  });
  $("historical-symbol").addEventListener("change", () => {report = null; state = "idle"; render();});
  i18n.subscribe(render); render();
})();
