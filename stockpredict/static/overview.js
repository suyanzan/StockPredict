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
  const defaults = ["2303.TW", "2330.TW", "2308.TW"];
  const maxStocks = 8, storageKey = "stockpredict.watchlist.v1";
  function normalizeWatchSymbol(value) {
    if (typeof value !== "string") return null;
    const symbol = value.trim().toUpperCase();
    return /^[0-9]{4,6}(?:\.TW)?$/.test(symbol) ? symbol.replace(/(?:\.TW)?$/, ".TW") : null;
  }
  function parseWatchlist(raw) {
    try {
      if (raw == null) return [...defaults];
      const values = JSON.parse(raw);
      if (!Array.isArray(values)) return [...defaults];
      const result = [...new Set(values.map(normalizeWatchSymbol).filter(Boolean))].slice(0, maxStocks);
      return values.length && !result.length ? [...defaults] : result;
    } catch { return [...defaults]; }
  }
  window.StockPredictOverview = { summarize, normalizeWatchSymbol, parseWatchlist };
  const root = document.getElementById("stock-overview");
  if (!root) return;
  const i18n = window.StockPredictI18n;
  i18n.register({
    "zh-TW": {
      "overview.nav": "個股總覽", "overview.kicker": "YOUR MARKET AT A GLANCE",
      "overview.title": "追蹤個股，一眼掌握。", "overview.copy": "自選每日行情；已納入收集的股票另顯示封存預測。非即時報價，非投資建議。",
      "overview.addLabel": "新增追蹤代碼", "overview.addPlaceholder": "例如 2317 或 0050",
      "overview.add": "加入追蹤", "overview.adding": "驗證行情中…", "overview.restore": "恢復預設",
      "overview.watchHelp": "支援台灣上市股票／ETF，最多 8 檔。清單只保存在此瀏覽器；新增追蹤不會加入正式盤前收集。",
      "overview.remove": "移除 {symbol}", "overview.invalid": "請輸入 4–6 位上市代碼，例如 2317 或 0050；不支援上櫃與美股。",
      "overview.duplicate": "這檔股票已在清單中。", "overview.limit": "最多追蹤 8 檔，請先移除一檔。",
      "overview.added": "已加入 {symbol}，可在下方卡片查看。",
      "overview.addFailed": "無法驗證上市行情，尚未加入。請確認代碼，或稍後重試；新上市或長期停牌也可能資料不足。",
      "overview.storageFailed": "瀏覽器無法保存清單，本次變更僅保留到頁面關閉。",
      "overview.watchEmpty": "尚未追蹤股票。請輸入代碼加入，或恢復預設清單。",
      "overview.quoteLoading": "讀取每日行情中…", "overview.quoteFailed": "每日行情暫時無法取得，請更新總覽重試。",
      "overview.quoteOnly": "行情追蹤", "overview.noCollection": "未納入正式盤前預測",
      "overview.quoteClose": "最近公布收盤",
      "overview.noCollectionNote": "加入清單僅讀取每日行情，不會自動收集、保存或回填預測成績。",
      "overview.analyze": "前往分析工作台", "overview.refresh": "更新總覽", "overview.loading": "讀取封存資料中…",
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
      "overview.title": "Your stocks. At a glance.", "overview.copy": "Your daily watchlist, with archived forecasts for enrolled stocks. Not live quotes or investment advice.",
      "overview.addLabel": "Add a listed symbol", "overview.addPlaceholder": "e.g. 2317 or 0050",
      "overview.add": "Add stock", "overview.adding": "Checking daily quote…", "overview.restore": "Restore defaults",
      "overview.watchHelp": "Taiwan listed stocks / ETFs, up to 8. Saved in this browser only; adding a stock does not enroll it in pre-open collection.",
      "overview.remove": "Remove {symbol}", "overview.invalid": "Enter a 4–6 digit listed symbol, such as 2317 or 0050. OTC and US stocks are not supported.",
      "overview.duplicate": "This stock is already on your list.", "overview.limit": "You can follow up to 8 stocks. Remove one first.",
      "overview.added": "Added {symbol}. Its card appears below.",
      "overview.addFailed": "Daily quote could not be verified; stock was not added. Check the code or retry later. Newly listed or suspended stocks may lack history.",
      "overview.storageFailed": "Browser storage unavailable. Changes last only until this page closes.",
      "overview.watchEmpty": "Your list is empty. Add a symbol or restore the default stocks.",
      "overview.quoteLoading": "Loading daily quote…", "overview.quoteFailed": "Daily quote unavailable. Refresh the overview to retry.",
      "overview.quoteOnly": "Quote tracking", "overview.noCollection": "Not enrolled in pre-open forecasts",
      "overview.quoteClose": "Latest published close",
      "overview.noCollectionNote": "Adding to this list only reads daily quotes; it does not collect, save or backfill forecast scores.",
      "overview.analyze": "Open analysis workbench", "overview.refresh": "Refresh overview", "overview.loading": "Loading archived data…",
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
  let symbols;
  try { symbols = parseWatchlist(window.localStorage.getItem(storageKey)); }
  catch { symbols = [...defaults]; }
  let quotes = {}, quoteGeneration = 0, quoteController, adding = false, revision = 0;
  let messageKey = "", messageValues = {}, storageAvailable = true;
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
    document.getElementById("watchlist-add").disabled = adding;
    document.getElementById("watchlist-add").textContent = t(adding ? "adding" : "add");
    document.getElementById("watchlist-message").textContent = messageKey ? t(messageKey, messageValues) : "";
    if (!symbols.length) grid.append(node("p", "watchlist-empty", t("watchEmpty")));
    for (const symbol of symbols) {
      const enrolled = defaults.includes(symbol);
      const entry = enrolled ? state[symbol] : quotes[symbol];
      const card = node("article", "overview-card");
      card.setAttribute("aria-busy", String(enrolled ? loading : !!entry?.loading));
      const head = node("div", "overview-card-head");
      const identity = node("div"); identity.append(node("span", "overview-symbol", symbol), node("h3", "", (names[symbol] ? i18n.t(names[symbol]) : entry?.quote?.name || symbol))); head.append(identity);
      const remove = node("button", "watchlist-remove", "×"); remove.type = "button";
      remove.setAttribute("aria-label", t("remove", { symbol }));
      remove.addEventListener("click", () => {
        revision++; symbols = symbols.filter(x => x !== symbol); saveList(); loadQuotes(); render();
      }); head.append(remove); card.append(head);
      const quote = entry?.quote;
      const view = enrolled ? summarize(entry?.detail, market) : quote ? {
        day: quote.session_date, close: quote.close, change: quote.day_change,
        changePct: quote.day_change_pct, fresh: quote.fresh, expected: quote.expected_session_date,
      } : null;
      if ((enrolled && loading) || !view) {
        card.append(node("p", "overview-empty", (enrolled && loading) ? t("loading") : !enrolled ? t(entry?.loading ? "quoteLoading" : "quoteFailed") : t(entry?.empty ? "empty" : !market && entry?.detail ? "calendarMissing" : "unavailable")));
        grid.append(card); continue;
      }
      const badge = node("span", `overview-badge ${view.fresh ? "" : "overview-warning"}`, t(view.fresh ? "current" : "stale")); head.append(badge);
      card.append(node("p", "overview-label", t(enrolled ? "close" : "quoteClose")), node("div", "overview-price", number(view.close)));
      if (view.change == null) card.append(node("p", "overview-change overview-muted", t("changeMissing")));
      else card.append(node("p", `overview-change ${view.change > 0 ? "overview-up" : view.change < 0 ? "overview-down" : ""}`, `${signed(view.change)}  (${signed(view.changePct)}%)`));
      card.append(node("p", "overview-date", t("asof", { date: view.day || "—" })));
      if (!view.fresh) card.append(node("p", "overview-pending", t("expected", { date: view.expected })));
      if (!enrolled) {
        const note = node("div", "overview-estimate");
        note.append(node("span", "overview-badge", t("quoteOnly")), node("h4", "", t("noCollection")), node("p", "overview-date", t("noCollectionNote")));
        card.append(note, node("p", "overview-date", t("source", { source: quote.source })));
        const analyze = node("button", "button button-secondary overview-detail", t("analyze")); analyze.type = "button";
        analyze.addEventListener("click", () => {
          document.getElementById("symbol").value = symbol;
          document.getElementById("source").value = "twse";
          document.getElementById("source").dispatchEvent(new Event("change", { bubbles: true }));
          document.getElementById("analysis").scrollIntoView({ behavior: "smooth", block: "start" });
          document.getElementById("symbol").focus({ preventScroll: true });
        }); card.append(analyze); grid.append(card); continue;
      }
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
  function saveList() {
    try { window.localStorage.setItem(storageKey, JSON.stringify(symbols)); storageAvailable = true; }
    catch { storageAvailable = false; }
    messageKey = storageAvailable ? "" : "storageFailed";
  }
  async function fetchQuote(symbol, signal) {
    const response = await fetch(`/api/quotes/taiwan?symbol=${encodeURIComponent(symbol)}`, { cache: "no-store", signal });
    if (!response.ok) throw new Error("quote unavailable");
    const quote = await response.json();
    if (quote.status !== "ready" || quote.symbol !== symbol || !validPrice(quote.close) || typeof quote.session_date !== "string" || typeof quote.fresh !== "boolean") throw new Error("invalid quote");
    return quote;
  }
  async function loadQuotes(refresh = false) {
    const current = ++quoteGeneration; quoteController?.abort();
    const selected = symbols.filter(x => !defaults.includes(x));
    quotes = Object.fromEntries(selected.map(symbol => [symbol, !refresh && quotes[symbol]?.quote ? quotes[symbol] : { loading: true }])); render();
    // Serialize cold requests to respect the existing source pacing/lock.
    for (const symbol of selected) {
      if (quotes[symbol]?.quote) continue;
      const request = new AbortController(); quoteController = request;
      const timer = setTimeout(() => request.abort(), 30000);
      try {
        const quote = await fetchQuote(symbol, request.signal);
        if (current !== quoteGeneration) return;
        quotes[symbol] = { quote };
      } catch { if (current === quoteGeneration) quotes[symbol] = {}; }
      finally { clearTimeout(timer); }
      if (current !== quoteGeneration) return;
      render();
    }
  }
  document.getElementById("watchlist-form").addEventListener("submit", async event => {
    event.preventDefault(); if (adding) return;
    const symbol = normalizeWatchSymbol(document.getElementById("watchlist-symbol").value);
    messageKey = !symbol ? "invalid" : symbols.includes(symbol) ? "duplicate" : symbols.length >= maxStocks ? "limit" : "";
    if (messageKey) { render(); return; }
    const current = revision;
    const request = new AbortController(); const timer = setTimeout(() => request.abort(), 30000);
    adding = true; render();
    try {
      const quote = defaults.includes(symbol) ? null : await fetchQuote(symbol, request.signal);
      if (current !== revision) return;
      symbols.push(symbol); if (quote) quotes[symbol] = { quote }; saveList();
      if (storageAvailable) { messageKey = "added"; messageValues = { symbol }; }
      document.getElementById("watchlist-symbol").value = "";
      if (defaults.includes(symbol)) window.StockPredictScoreboard?.refresh();
    } catch { if (current === revision) messageKey = "addFailed"; }
    finally { clearTimeout(timer); adding = false; render(); }
  });
  document.getElementById("watchlist-restore").addEventListener("click", () => {
    revision++; symbols = [...defaults]; saveList(); loadQuotes(); render();
    window.StockPredictScoreboard?.refresh();
  });
  window.addEventListener("stockpredict-scoreboard-loading", () => { reset(); loadQuotes(true); });
  window.addEventListener("stockpredict-scoreboard", async event => {
    reset(); const current = generation; let timer;
    try {
      market = event.detail.calendar?.markets?.find(x => x.exchange === "XTAI") || null;
      const scores = event.detail.scores;
      if (scores?.status !== "ready") return;
      const requestController = new AbortController(); controller = requestController;
      timer = setTimeout(() => requestController.abort(), 15000);
      const signal = requestController.signal;
      const entries = await Promise.all(symbols.filter(symbol => defaults.includes(symbol)).map(async symbol => {
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
