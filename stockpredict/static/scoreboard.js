(() => {
  "use strict";
  const i18n = window.StockPredictI18n;
  i18n.register({
    "zh-TW": {
      "score.title": "預測成績看板", "score.refresh": "更新成績",
      "score.description": "聯電與台積電 · 盤前原始預測 · 第 1、5 個交易日。待公布不計分，純台股與 ADR 情境分開。",
      "score.records": "原始預測與逐筆成績", "score.calendar": "台美交易日曆與資料狀態",
      "score.method": "誤差＝預測減實際；MAPE＝絕對誤差／實際收盤；方向以預測前收盤為基準，持平為獨立方向。預測與收盤紀錄不可覆寫。",
      "score.calendarNote": "使用交易所日曆，含美股夏令時間及提早收盤。可用時間為保守門檻，仍需來源公布；缺資料不以舊價替代。",
      "score.loading": "正在讀取成績…", "score.unavailable": "成績資料庫尚未就緒，請檢查 PostgreSQL 設定與初始化。",
      "score.ready": "已讀取保存成績。尚無紀錄時顯示 —，不回填歷史預測。",
      "score.taiwan": "純台股", "score.adr": "ADR 情境", "score.pending": "待公布",
      "score.current": "已取得所需交易日", "score.missing": "缺少所需交易日，舊資料不代表當日價格",
      "score.checked": "檢查時間", "score.actualSession": "行情交易日", "score.expected": "所需交易日",
      "score.noCheck": "尚未執行收集排程", "score.error": "資料暫時無法取得",
      "score.columns": "股票,情境,交易日數,已計分,待公布,MAE（TWD）,MAPE,方向命中率",
      "score.recordColumns": "股票,情境,交易日數,保存時間（台北）,目標交易日,預測（TWD）,實際（TWD）,誤差（TWD）,方向",
      "score.hit": "命中", "score.miss": "未命中", "score.next": "下一待公布交易日",
      "score.open": "開盤", "score.close": "收盤", "score.available": "可用門檻",
      "score.publishable": "最近可公布交易日", "score.saved": "已保存", "score.already_saved": "原始預測已保存",
      "score.after_cutoff": "已過盤前保存時間", "score.outside_capture_day": "非預測保存日",
      "score.missing_base_session": "缺少前收盤", "score.missing_us_sessions": "缺少所需美股交易日",
      "score.source_unavailable": "來源暫時無法取得", "score.us_session_not_closed": "美股尚未完成公布",
      "score.stale_history": "台股歷史資料過舊", "score.insufficient_aligned_history": "對齊歷史資料不足",
      "score.auto_csv_missing_session": "自動收盤資料缺少所需交易日",
      "score.auto_csv_unavailable": "自動收盤資料尚未取得",
      "score.auto_csv_invalid_data": "自動收盤資料驗證失敗",
      "score.source_changed_during_capture": "保存期間來源資料已變更，等待下次重試",
    },
    en: {
      "score.title": "Prediction scoreboard", "score.refresh": "Refresh scores",
      "score.description": "UMC and TSMC · Original pre-open predictions · Trading days 1 and 5. Pending results are excluded. Taiwan-only and ADR scenarios are scored separately.",
      "score.records": "Original predictions and individual scores", "score.calendar": "Taiwan / US calendar and data status",
      "score.method": "Error = predicted − actual. MAPE = absolute error / actual close. Direction is measured from the base close; flat is a separate direction. Forecasts and closes are immutable.",
      "score.calendarNote": "Exchange calendars include US daylight saving and early closes. Availability is a conservative gate and still requires published source data. Missing dates never use an older price.",
      "score.loading": "Loading scores…", "score.unavailable": "Score storage is unavailable. Check PostgreSQL configuration and schema initialization.",
      "score.ready": "Saved results loaded. Empty records show —; historical predictions are never backfilled.",
      "score.taiwan": "Taiwan only", "score.adr": "ADR scenario", "score.pending": "Pending publication",
      "score.current": "Required session available", "score.missing": "Required session missing; older data is not today's price",
      "score.checked": "Checked at", "score.actualSession": "Quote session", "score.expected": "Required session",
      "score.noCheck": "Collection job has not run yet", "score.error": "Data temporarily unavailable",
      "score.columns": "Stock,Scenario,Trading days,Scored,Pending,MAE (TWD),MAPE,Direction accuracy",
      "score.recordColumns": "Stock,Scenario,Trading days,Saved at (Taipei),Target session,Prediction (TWD),Actual (TWD),Error (TWD),Direction",
      "score.hit": "Hit", "score.miss": "Miss", "score.next": "Next unpublished session",
      "score.open": "Open", "score.close": "Close", "score.available": "Availability gate",
      "score.publishable": "Latest publishable session", "score.saved": "Saved", "score.already_saved": "Original forecast already saved",
      "score.after_cutoff": "Pre-open capture window closed", "score.outside_capture_day": "Outside capture day",
      "score.missing_base_session": "Previous close missing", "score.missing_us_sessions": "Required US session missing",
      "score.source_unavailable": "Source unavailable", "score.us_session_not_closed": "US close not yet publishable",
      "score.stale_history": "Taiwan history is stale", "score.insufficient_aligned_history": "Insufficient aligned history",
      "score.auto_csv_missing_session": "Required session missing from automated close data",
      "score.auto_csv_unavailable": "Automated close data unavailable",
      "score.auto_csv_invalid_data": "Automated close data failed validation",
      "score.source_changed_during_capture": "Source changed during capture; retry required",
    }
  });
  const $ = id => document.getElementById(id);
  const t = key => i18n.t(`score.${key}`);
  let scores, calendar, status;
  function stamp(value) {
    return value ? new Intl.DateTimeFormat(i18n.getLanguage(), {
      timeZone: "Asia/Taipei", dateStyle: "short", timeStyle: "medium", hour12: false
    }).format(new Date(value)) : "—";
  }
  const number = value => value == null ? "—" : value.toFixed(2);
  const percent = value => value == null ? "—" : `${number(value)}%`;
  const stock = symbol => `${symbol === "2303.TW" ? i18n.t("security.umc") : i18n.t("security.tsmc")} ${symbol}`;
  function row(parent, values, heading = false) {
    const tr = document.createElement("tr");
    values.forEach(value => {
      const cell = document.createElement(heading ? "th" : "td");
      cell.textContent = value;
      if (heading) cell.scope = "col";
      tr.append(cell);
    });
    parent.append(tr);
  }
  function paragraph(parent, text) {
    const p = document.createElement("p"); p.textContent = text; parent.append(p);
  }
  function dataLine(value) {
    return `${t("actualSession")}: ${value.session_date || "—"} · ${t("expected")}: ${value.expected_session_date || "—"} · ${t("checked")}: ${stamp(value.checked_at)} · ${t(value.status === "current" ? "current" : "missing")}`;
  }
  function reason(value) {
    const message = t(value);
    return message.startsWith("score.") ? `${t("error")} (${value})` : message;
  }
  function render() {
    for (const id of ["score-head", "score-summary", "score-record-head", "score-records", "score-calendar"]) $(id).replaceChildren();
    row($("score-head"), t("columns").split(","), true);
    row($("score-record-head"), t("recordColumns").split(","), true);
    $("score-status").textContent = scores?.status === "ready" ? t("ready") : t("unavailable");
    for (const s of scores?.summary || []) row($("score-summary"), [stock(s.symbol), t(s.scenario), s.horizon, s.samples, s.pending, number(s.mae), percent(s.mape), percent(s.direction_accuracy == null ? null : s.direction_accuracy * 100)]);
    for (const s of scores?.predictions || []) row($("score-records"), [stock(s.symbol), t(s.scenario), s.horizon, stamp(s.created_at), s.target_date, number(s.predicted_close), s.actual_close == null ? t("pending") : number(s.actual_close), number(s.error), s.direction_hit == null ? "—" : t(s.direction_hit ? "hit" : "miss")]);
    if (calendar?.markets) {
      paragraph($("score-calendar"), `${t("checked")}: ${stamp(calendar.checked_at)} (Asia/Taipei)`);
      for (const m of calendar.markets) paragraph($("score-calendar"), `${m.exchange} · ${t("publishable")}: ${m.latest_publishable_session} · ${t("next")}: ${m.next_session} · ${t("open")}: ${stamp(m.opens_at)} · ${t("close")}: ${stamp(m.closes_at)} · ${t("available")}: ${stamp(m.available_after)}`);
    } else paragraph($("score-calendar"), t("error"));
    if (scores?.last_check) {
      paragraph($("score-calendar"), `${t("checked")}: ${stamp(scores.last_check.checked_at)}`);
      for (const item of scores.last_check.details) {
        paragraph($("score-calendar"), `${stock(item.symbol)} · ${dataLine(item)}${item.reason ? ` · ${reason(item.reason)}` : ""}`);
        for (const scenario of ["taiwan", "adr"]) if (item[scenario]) paragraph($("score-calendar"), `${t(scenario)}: ${reason(item[scenario])}`);
      }
    } else paragraph($("score-calendar"), t("noCheck"));
    $("analysis-data-status")?.remove();
    if (status) {
      const p = document.createElement("p"); p.id = "analysis-data-status";
      p.className = "source-help"; p.textContent = dataLine(status);
      $("result-date").after(p);
    }
  }
  async function load() {
    $("score-refresh").disabled = true;
    $("score-status").textContent = t("loading");
    const results = await Promise.allSettled([fetch("/api/scoreboard", { cache: "no-store" }).then(r => r.json()), fetch("/api/calendar", { cache: "no-store" }).then(r => r.json())]);
    scores = results[0].status === "fulfilled" ? results[0].value : null;
    calendar = results[1].status === "fulfilled" ? results[1].value : null;
    render(); $("score-refresh").disabled = false;
  }
  $("score-refresh").addEventListener("click", load);
  window.addEventListener("stockpredict-data-status", event => { status = event.detail; render(); });
  i18n.subscribe(render);
  load();
})();
