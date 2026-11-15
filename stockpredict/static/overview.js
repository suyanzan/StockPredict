"use strict";
(() => {
  const validPrice = x => Number.isFinite(x) && x > 0;
  // A missing adjacent close must never become a multiple-session daily change.
  function summarize(detail, market) {
    if (!detail || !market) return null;
    const path = Array.isArray(detail.forecast) ? detail.forecast : [];
    const dates = [detail.base_date, ...path.map(p => p.target_date)];
    const closes = new Map();
    if (validPrice(detail.base_close)) closes.set(detail.base_date, detail.base_close);
    for (const p of path) if (validPrice(p.actual_close)) closes.set(p.target_date, p.actual_close);
    const eligible = [...closes.keys()].filter(d => typeof d === "string" && d <= market.latest_publishable_session).sort();
    const day = eligible.at(-1), close = closes.get(day);
    const prior = closes.get(dates[dates.indexOf(day) - 1]);
    const change = validPrice(prior) && validPrice(close) ? close - prior : null;
    const point = path.find(p => p.target_date === market.next_session && validPrice(p.predicted_close));
    return {
      day: day || null, close: close ?? null, change,
      changePct: change == null ? null : change / prior * 100,
      fresh: day === market.latest_publishable_session,
      expected: market.latest_publishable_session,
      target: market.next_session,
      forecast: point?.predicted_close ?? null,
      horizon: point?.horizon ?? null,
      origin: detail.origin_date,
      olderOrigin: detail.origin_date !== market.next_session,
      forecastPct: point && validPrice(close) && day === market.latest_publishable_session
        ? (point.predicted_close / close - 1) * 100 : null,
    };
  }
  window.StockPredictOverview = { summarize };
  const root = document.getElementById("stock-overview");
  if (!root) return;
  const i18n = window.StockPredictI18n;
  i18n.register({
    "zh-TW": {
      "overview.nav": "個股總覽", "overview.kicker": "YOUR MARKET AT A GLANCE",
      "overview.title": "追蹤個股，一眼掌握。", "overview.copy": "每日收盤與純台股封存預測。非即時報價，非投資建議。",
      "overview.refresh": "更新總覽", "overview.loading": "讀取封存資料中…",
      "overview.unavailable": "暫時無法讀取，請稍後更新。", "overview.empty": "尚無此股票的封存紀錄。",
      "overview.calendarMissing": "交易日曆暫時無法取得，無法確認資料新鮮度。",
      "overview.close": "最近保存收盤", "overview.current": "收盤已更新", "overview.stale": "收盤待更新",
      "overview.asof": "資料日期 {date}", "overview.expected": "應有收盤 {date}",
      "overview.changeMissing": "缺少前一交易日收盤，日漲跌暫不計算",
      "overview.target": "估計收盤 · {date}", "overview.noForecast": "尚無目標日的封存預測",
      "overview.archive": "{date} 盤前封存 · 第 {horizon} 日估計",
      "overview.older": "較早起日封存", "overview.onTime": "當日起日封存",
      "overview.relative": "較最新保存收盤 {pct}", "overview.source": "來源：{source} · TWD",
      "overview.details": "查看預測詳情", "overview.note": "估計取自最近一次純台股封存；較早起日的路徑不等於新的當日預測。",
      "overview.loaded": "本次讀取 {time}（台北）", "overview.compare": "查看完整成績與 ADR 比較 →",
    },
    en: {
      "overview.nav": "Stock overview", "overview.kicker": "YOUR MARKET AT A GLANCE",
      "overview.title": "Your stocks. At a glance.", "overview.copy": "Daily closes and archived Taiwan-only forecasts. Not live quotes or investment advice.",
      "overview.refresh": "Refresh overview", "overview.loading": "Loading archived data…",
      "overview.unavailable": "Temporarily unavailable. Please refresh later.", "overview.empty": "No archived forecast for this stock yet.",
      "overview.calendarMissing": "Trading calendar unavailable; data freshness cannot be verified.",
      "overview.close": "Latest saved close", "overview.current": "Close up to date", "overview.stale": "Close update pending",
      "overview.asof": "Data date {date}", "overview.expected": "Expected close {date}",
      "overview.changeMissing": "Previous session close missing; daily change unavailable",
      "overview.target": "Estimated close · {date}", "overview.noForecast": "No archived forecast for the target session",
      "overview.archive": "Archived before open on {date} · Day {horizon} estimate",
      "overview.older": "Earlier forecast origin", "overview.onTime": "Target-day forecast origin",
      "overview.relative": "Versus latest saved close {pct}", "overview.source": "Source: {source} · TWD",
      "overview.details": "View forecast details", "overview.note": "Estimates use the latest Taiwan-only archive. An older-origin path is not a new target-day forecast.",
      "overview.loaded": "Read at {time} (Taipei)", "overview.compare": "Full scores and ADR comparison →",
    },
  });
  const symbols = ["2303.TW", "2330.TW", "2308.TW"];
  const names = { "2303.TW": "security.umc", "2330.TW": "security.tsmc", "2308.TW": "security.delta" };
  let state = {}, market = null, loading = true, loaded = null, generation = 0, controller, watchdog;
  const t = (key, values) => i18n.t(`overview.${key}`, values);
  const node = (tag, className, text) => {
    const e = document.createElement(tag); e.className = className || "";
    if (text != null) e.textContent = text;
    return e;
  };
  const number = x => x == null ? "—" : new Intl.NumberFormat(i18n.getLanguage(), { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(x);
  const signed = x => `${x > 0 ? "+" : ""}${number(x)}`;
  function render() {
    const grid = document.getElementById("overview-cards"); grid.replaceChildren();
    document.getElementById("overview-refresh").disabled = loading;
    document.getElementById("overview-status").textContent = loading ? t("loading") : loaded ? t("loaded", { time: new Intl.DateTimeFormat(i18n.getLanguage(), { timeZone: "Asia/Taipei", dateStyle: "short", timeStyle: "medium" }).format(loaded) }) : t("unavailable");
    root.setAttribute("aria-busy", String(loading));
    for (const symbol of symbols) {
      const entry = state[symbol];
      const card = node("article", "overview-card");
      const head = node("div", "overview-card-head");
      const identity = node("div"); identity.append(node("span", "overview-symbol", symbol), node("h3", "", i18n.t(names[symbol]))); head.append(identity); card.append(head);
      const view = summarize(entry?.detail, market);
      if (loading || !view) {
        card.append(node("p", "overview-empty", loading ? t("loading") : t(entry?.empty ? "empty" : !market && entry?.detail ? "calendarMissing" : "unavailable")));
        grid.append(card); continue;
      }
      const badge = node("span", `overview-badge ${view.fresh ? "" : "overview-warning"}`, t(view.fresh ? "current" : "stale")); head.append(badge);
      card.append(node("p", "overview-label", t("close")), node("div", "overview-price", number(view.close)));
      if (view.change == null) card.append(node("p", "overview-change overview-muted", t("changeMissing")));
      else card.append(node("p", `overview-change ${view.change > 0 ? "overview-up" : view.change < 0 ? "overview-down" : ""}`, `${signed(view.change)}  (${signed(view.changePct)}%)`));
      card.append(node("p", "overview-date", t("asof", { date: view.day || "—" })));
      if (!view.fresh) card.append(node("p", "overview-pending", t("expected", { date: view.expected })));
      const estimate = node("div", "overview-estimate");
      estimate.append(node("p", "overview-label", t("target", { date: view.target })), node("strong", "overview-estimate-price", number(view.forecast)));
      if (view.forecast == null) estimate.append(node("p", "overview-pending", t("noForecast")));
      else {
        estimate.append(node("span", `overview-badge ${view.olderOrigin ? "overview-warning" : ""}`, t(view.olderOrigin ? "older" : "onTime")));
        estimate.append(node("p", "overview-date", t("archive", { date: view.origin, horizon: view.horizon })));
        if (view.forecastPct != null) estimate.append(node("p", "overview-date", t("relative", { pct: `${signed(view.forecastPct)}%` })));
      }
      card.append(estimate, node("p", "overview-date", t("source", { source: entry.detail.source || "—" })));
      const button = node("button", "button button-secondary overview-detail", t("details"));button.type = "button";
      button.addEventListener("click", () => window.StockPredictAudit.showPrediction(entry.detail.id));card.append(button);grid.append(card);
    }
  }
  function reset() {
    generation++; controller?.abort(); clearTimeout(watchdog);
    state = {}; market = null; loaded = null; loading = true; render();
    // Covers a missing producer script/event as well as a stalled request chain.
    watchdog = setTimeout(() => {
      generation++; controller?.abort(); state = {}; market = null;
      loaded = null; loading = false; render();
    }, 40000);
  }
  window.addEventListener("stockpredict-scoreboard-loading", reset);
  window.addEventListener("stockpredict-scoreboard", async event => {
    reset(); const current = generation; let timer;
    try {
      market = event.detail.calendar?.markets?.find(x => x.exchange === "XTAI") || null;
      const scores = event.detail.scores;
      if (scores?.status !== "ready") return;
      const requestController = new AbortController(); controller = requestController;
      timer = setTimeout(() => requestController.abort(), 15000);
      const signal = requestController.signal;
      const entries = await Promise.all(symbols.map(async symbol => {
        const latest = (scores.predictions || []).filter(x => x.symbol === symbol && x.scenario === "taiwan" && x.horizon === 1 && typeof x.origin_date === "string" && Number.isInteger(x.id))
          .sort((a, b) => b.origin_date.localeCompare(a.origin_date) || b.id - a.id)[0];
        if (!latest) return [symbol, { empty: true }];
        try {
          const response = await fetch(`/api/predictions/${encodeURIComponent(latest.id)}`, { cache: "no-store", signal });
          if (!response.ok) throw new Error("unavailable");
          const detail = await response.json();
          if (detail.symbol !== symbol || detail.scenario !== "taiwan" || detail.id !== latest.id || !Array.isArray(detail.forecast)) throw new Error("invalid archive");
          return [symbol, { detail }];
        } catch { return [symbol, {}]; }
      }));
      if (current !== generation) return;
      state = Object.fromEntries(entries); loaded = new Date();
    } catch {
      if (current === generation) { state = {}; market = null; loaded = null; }
    } finally {
      clearTimeout(timer);
      if (current === generation) { clearTimeout(watchdog); loading = false; render(); }
    }
  });
  document.getElementById("overview-refresh").addEventListener("click", () => {
    if (window.StockPredictScoreboard?.refresh) window.StockPredictScoreboard.refresh();
    else window.location.reload();
  });
  i18n.subscribe(render);reset();
})();
