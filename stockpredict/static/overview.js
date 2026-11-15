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
  function parseWatchlistImport(raw) {
    const payload = JSON.parse(raw);
    if (!payload || payload.format !== "stockpredict.watchlist" || payload.version !== 1 || !Array.isArray(payload.symbols) || payload.symbols.length > maxStocks || payload.symbols.some(x => !normalizeWatchSymbol(x))) throw new Error("invalid import");
    return [...new Set(payload.symbols.map(normalizeWatchSymbol))];
  }
  function validateResearch(result, quote) {
    if (!quote?.fresh || !validPrice(quote.close) || quote.source !== "twse" || typeof result?.backtest?.model_beats_baseline !== "boolean" || typeof quote.expected_session_date !== "string" || quote.expected_session_date !== quote.session_date || !result || result.symbol !== quote.symbol || result.source !== "twse" || result.as_of !== quote.session_date || result.summary?.last_close !== quote.close || result.data_status?.status !== "current" || result.data_status.session_date !== quote.session_date || result.data_status.expected_session_date !== quote.expected_session_date || result.model?.name !== "Ridge AR(5)" || !Number.isFinite(Date.parse(result.data_status.checked_at))) return null;
    if (!Array.isArray(result.history) || !result.history.length || result.history.at(-1).date !== quote.session_date || result.history.at(-1).close !== quote.close || result.history.some(p=>typeof p.date!=="string" || p.date>result.as_of)) return null;
    const points = result.forecast;
    if (!Array.isArray(points) || points.length !== 5) return null;
    let previous = result.as_of;
    for (const point of points) {
      if (!validPrice(point.close) || typeof point.date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(point.date) || point.date <= previous) return null;
      const time=Date.parse(`${point.date}T00:00:00Z`);
      if (!Number.isFinite(time) || new Date(time).toISOString().slice(0,10)!==point.date || [0,6].includes(new Date(time).getUTCDay())) return null;
      previous=point.date;
    }
    return {points:points.map(p=>({date:p.date,close:p.close})),asOf:result.as_of,checkedAt:result.data_status.checked_at,beatsBaseline:result.backtest?.model_beats_baseline};
  }
  window.StockPredictOverview = { summarize, normalizeWatchSymbol, parseWatchlist, parseWatchlistImport, validateResearch };
  const root = document.getElementById("stock-overview");
  if (!root) return;
  const i18n = window.StockPredictI18n;
  i18n.register({
    "zh-TW": {
      "overview.nav": "個股總覽", "overview.kicker": "YOUR MARKET AT A GLANCE",
      "overview.title": "追蹤個股，一眼掌握。", "overview.copy": "每日行情與研究預測；正式追蹤股票另顯示封存估計。非即時報價，非投資建議。",
      "overview.export": "匯出清單", "overview.import": "匯入清單", "overview.importApply": "套用並取代清單", "overview.importCancel": "取消",
      "overview.importPreview": "將以 {symbols} 取代目前清單。只驗證檔案格式，行情將逐檔讀取；不會啟用正式預測。",
      "overview.importInvalid": "匯入失敗。請使用本網站匯出的 JSON，最多 8 檔且檔案不超過 4 KB。原清單未變更。",
      "overview.imported": "已匯入 {count} 檔，清單已取代。", "overview.exported": "已匯出股票代碼清單，不包含行情或預測紀錄。",
      "overview.importEmpty": "空清單", "overview.retry": "重試此檔", "overview.queued": "排隊讀取 · 第 {position}/{total} 檔",
      "overview.reloadQuote": "更新此檔行情與研究預測",
      "overview.research": "研究預測", "overview.researchQueued": "等待計算研究預測…", "overview.researchLoading": "計算研究預測中…（上限 20 秒）",
      "overview.researchFailed": "研究預測暫時無法取得；行情仍可查看，請重試。", "overview.researchStale": "缺少最新應有收盤，暫停研究預測。",
      "overview.researchRetry": "重試研究預測", "overview.researchNote": "本次依現有資料計算，未盤前封存、不列入正式成績。",
      "overview.researchBasis": "Ridge AR(5) · 依 {date} 收盤計算", "overview.researchPath": "五交易日估計路徑",
      "overview.researchRisk": "每日價格未還原權息，分割可能影響估計；五日預測表現尚未驗證。",
      "overview.researchBaseline": "這段一日回測未優於維持前收盤基準。",
      "overview.researchChecked": "資料檢查 {time}（台北）",
      "overview.fetching": "讀取行情中 · 已 {seconds} 秒／上限 30 秒", "overview.validating": "驗證 {symbol} 行情中 · 已 {seconds} 秒／上限 30 秒",
      "overview.admission": "檢查正式追蹤條件", "overview.admissionLoading": "檢查條件中…", "overview.admissionFailed": "檢查暫時無法完成，請稍後重試。",
      "overview.admissionReview": "行情與五交易日試算符合前置條件；尚未啟用正式收集。",
      "overview.admissionBlocked": "前置條件尚未符合，仍維持行情追蹤。",
      "overview.admissionNote": "仍需審核、保存流程驗證與正式啟用，再從未來盤前開始累積成績；本次檢查不寫入預測。",
      "overview.admissionAsOf": "檢查時間 {time} · 資料日期 {date}", "overview.check_valid_history": "有效歷史資料", "overview.check_exchange_sessions": "交易日有效性",
      "overview.check_latest_session": "最新應有收盤", "overview.check_previous_close": "精確前一交易日", "overview.check_five_session_path": "五交易日試算",
      "overview.pass": "符合", "overview.fail": "未符合", "overview.addLabel": "新增追蹤代碼", "overview.addPlaceholder": "例如 2317 或 0050",
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
      "overview.details": "查看預測詳情", "overview.note": "原三檔顯示封存估計；其它股票顯示本次研究預測，未盤前封存且不列入成績。",
      "overview.loaded": "本次讀取 {time}（台北）", "overview.compare": "查看完整成績與 ADR 比較 →",
    },
    en: {
      "overview.nav": "Stock overview", "overview.kicker": "YOUR MARKET AT A GLANCE",
      "overview.title": "Your stocks. At a glance.", "overview.copy": "Daily closes and research forecasts, with archived estimates for formally tracked stocks. Not live quotes or investment advice.",
      "overview.export": "Export list", "overview.import": "Import list", "overview.importApply": "Apply and replace list", "overview.importCancel": "Cancel",
      "overview.importPreview": "Replace your list with {symbols}. Only file format is checked; quotes load individually. Formal forecasts stay unchanged.",
      "overview.importInvalid": "Import failed. Use a StockPredict export JSON with up to 8 symbols, at most 4 KB. Your list was not changed.",
      "overview.imported": "Imported {count} stocks and replaced the list.", "overview.exported": "Exported symbols only; no quotes or forecast history.",
      "overview.importEmpty": "an empty list", "overview.retry": "Retry this stock", "overview.queued": "Queued · stock {position}/{total}",
      "overview.reloadQuote": "Refresh this quote and research forecast",
      "overview.research": "Research forecast", "overview.researchQueued": "Research forecast queued…", "overview.researchLoading": "Computing research forecast… (20s limit)",
      "overview.researchFailed": "Research forecast unavailable. Daily quotes remain available; please retry.", "overview.researchStale": "Latest required close missing; research forecast paused.",
      "overview.researchRetry": "Retry research forecast", "overview.researchNote": "Computed from current data; not archived before open and excluded from formal scores.",
      "overview.researchBasis": "Ridge AR(5) · based on the {date} close", "overview.researchPath": "Five-session estimate path",
      "overview.researchRisk": "Daily prices are not adjusted for corporate actions. Splits can affect estimates; five-day forecast performance is unvalidated.",
      "overview.researchBaseline": "The one-day backtest did not beat the previous-close baseline.",
      "overview.researchChecked": "Data checked {time} (Taipei)",
      "overview.fetching": "Loading quote · {seconds}s elapsed / 30s limit", "overview.validating": "Checking {symbol} · {seconds}s elapsed / 30s limit",
      "overview.admission": "Check forecast prerequisites", "overview.admissionLoading": "Checking prerequisites…", "overview.admissionFailed": "Prerequisite check unavailable. Please retry later.",
      "overview.admissionReview": "Quote and five-session dry run meet prerequisites. Formal collection is not enabled.",
      "overview.admissionBlocked": "Prerequisites are not met. This remains quote tracking only.",
      "overview.admissionNote": "Review, archive validation and activation are still required before collecting future pre-open forecasts. This check saves no predictions.",
      "overview.admissionAsOf": "Checked {time} · data date {date}", "overview.check_valid_history": "Valid history", "overview.check_exchange_sessions": "Exchange sessions",
      "overview.check_latest_session": "Latest required close", "overview.check_previous_close": "Exact previous session", "overview.check_five_session_path": "Five-session dry run",
      "overview.pass": "Met", "overview.fail": "Not met", "overview.addLabel": "Add a listed symbol", "overview.addPlaceholder": "e.g. 2317 or 0050",
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
      "overview.details": "View forecast details", "overview.note": "The original three stocks show archived estimates. Other stocks show current research forecasts, without pre-open archiving or formal scoring.",
      "overview.loaded": "Read at {time} (Taipei)", "overview.compare": "Full scores and ADR comparison →",
    },
  });
  let symbols;
  try { symbols = parseWatchlist(window.localStorage.getItem(storageKey)); }
  catch { symbols = [...defaults]; }
  let quotes = {}, quoteGeneration = 0, quoteController, adding = false, revision = 0;
  let messageKey = "", messageValues = {}, storageAvailable = true;
  let quoteQueue = [], quoteRunning = null, progressTimer, addingStarted = null, addingSymbol = "";
  let importSymbols = null, importGeneration = 0, admissions = {};
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
    updateProgress();
    if (!symbols.length) grid.append(node("p", "watchlist-empty", t("watchEmpty")));
    for (const symbol of symbols) {
      const enrolled = defaults.includes(symbol);
      const entry = enrolled ? state[symbol] : quotes[symbol];
      const card = node("article", "overview-card");
      card.setAttribute("aria-busy", String(enrolled ? loading : !!entry?.loading || !!entry?.research?.loading));
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
        if (!enrolled) {
          const progress = card.lastElementChild; progress.classList.add("quote-progress"); progress.setAttribute("data-quote-symbol", symbol);
          progress.textContent = quoteProgress(symbol);
          const retry = node("button", "button button-secondary overview-detail", t("retry")); retry.type = "button"; retry.disabled = !!entry?.loading;
          retry.addEventListener("click", () => retryQuote(symbol));card.append(retry);
        }
        grid.append(card); continue;
      }
      const badge = node("span", `overview-badge ${view.fresh ? "" : "overview-warning"}`, t(view.fresh ? "current" : "stale")); head.append(badge);
      card.append(node("p", "overview-label", t(enrolled ? "close" : "quoteClose")), node("div", "overview-price", number(view.close)));
      if (view.change == null) card.append(node("p", "overview-change overview-muted", t("changeMissing")));
      else card.append(node("p", `overview-change ${view.change > 0 ? "overview-up" : view.change < 0 ? "overview-down" : ""}`, `${signed(view.change)}  (${signed(view.changePct)}%)`));
      card.append(node("p", "overview-date", t("asof", { date: view.day || "—" })));
      if (!view.fresh) card.append(node("p", "overview-pending", t("expected", { date: view.expected })));
      if (!enrolled) {
        const note = node("div", "overview-estimate research-estimate");
        note.append(node("span", "overview-badge research-badge", t("research")));
        const preview = entry.research?.data;
        if (preview) {
          const first=preview.points[0];
          note.append(node("p", "overview-label", t("target", {date:first.date})), node("strong", "research-estimate-price", number(first.close)), node("p", "overview-date", t("researchBasis",{date:preview.asOf})));
          note.append(node("p", "overview-date", t("researchChecked",{time:new Intl.DateTimeFormat(i18n.getLanguage(),{timeZone:"Asia/Taipei",dateStyle:"short",timeStyle:"medium"}).format(new Date(preview.checkedAt))})));
          const path=node("details", "research-path");path.append(node("summary", "", t("researchPath")));
          for (const point of preview.points) path.append(node("p", "overview-date", `${point.date} · ${number(point.close)} TWD`));note.append(path);
          if (preview.beatsBaseline === false) note.append(node("p", "overview-pending", t("researchBaseline")));
        } else {
          note.append(node("p", "overview-pending", t(!quote.fresh ? "researchStale" : entry.research?.error ? "researchFailed" : entry.research?.loading ? "researchLoading" : "researchQueued")));
          if (quote.fresh && entry.research?.error) {
            const retry=node("button", "button button-secondary", t("researchRetry"));retry.type="button";retry.addEventListener("click",()=>retryQuote(symbol));note.append(retry);
          }
        }
        note.append(node("p", "research-disclosure", t("researchNote")),node("p", "overview-date", t("researchRisk")));
        card.append(note, node("p", "overview-date", t("source", { source: quote.source })));
        const reload = node("button", "button button-secondary overview-detail", t("reloadQuote")); reload.type = "button";reload.disabled=!!entry.research?.loading || quoteQueue.includes(symbol);reload.addEventListener("click",()=>retryQuote(symbol));card.append(reload);
        const analyze = node("button", "button button-secondary overview-detail", t("analyze")); analyze.type = "button";
        analyze.addEventListener("click", () => {
          document.getElementById("symbol").value = symbol;
          document.getElementById("source").value = "twse";
          document.getElementById("source").dispatchEvent(new Event("change", { bubbles: true }));
          document.getElementById("analysis").scrollIntoView({ behavior: "smooth", block: "start" });
          document.getElementById("symbol").focus({ preventScroll: true });
        }); card.append(analyze);
        const check = node("button", "button button-secondary overview-detail", t(admissions[symbol]?.loading ? "admissionLoading" : "admission")); check.type = "button";check.disabled = !!admissions[symbol]?.loading;
        check.addEventListener("click", () => checkAdmission(symbol));card.append(check);
        if (admissions[symbol]?.error) card.append(node("p", "overview-pending", t("admissionFailed")));
        const report = admissions[symbol]?.report;
        if (report) {
          const box = node("div", "admission-report");box.append(node("p", "", t(report.status === "review_required" ? "admissionReview" : "admissionBlocked")));
          for (const key of ["valid_history","exchange_sessions","latest_session","previous_close","five_session_path"]) box.append(node("p", "overview-date", `${t(`check_${key}`)}：${t(report.checks[key] ? "pass" : "fail")}`));
          box.append(node("p", "overview-date", t("admissionAsOf", {time:report.checked_at,date:report.session_date || "—"})),node("p", "overview-date", t("admissionNote")));card.append(box);
        }
        grid.append(card); continue;
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
  function clearImport() {
    importGeneration++;importSymbols=null;
    document.getElementById("watchlist-import-review").hidden=true;
    document.getElementById("watchlist-import").value="";
  }
  document.getElementById("watchlist-export").addEventListener("click",()=>{
    const blob=new Blob([JSON.stringify({format:"stockpredict.watchlist",version:1,symbols},null,2)],{type:"application/json"});
    const url=URL.createObjectURL(blob),link=document.createElement("a");link.href=url;link.download="stockpredict-watchlist.json";link.click();setTimeout(()=>URL.revokeObjectURL(url),0);
    messageKey="exported";render();
  });
  document.getElementById("watchlist-import").addEventListener("change",async event=>{
    const file=event.target.files?.[0];if(!file)return;const current=++importGeneration;
    importSymbols=null;document.getElementById("watchlist-import-review").hidden=true;
    try {
      if(file.size>4096)throw new Error("large file");const list=parseWatchlistImport(await file.text());if(current!==importGeneration)return;
      importSymbols=list;document.getElementById("watchlist-import-preview").textContent=t("importPreview",{symbols:list.join(", ")||t("importEmpty")});
      document.getElementById("watchlist-import-review").hidden=false;messageKey="";render();
    } catch {if(current===importGeneration){messageKey="importInvalid";render()}}
  });
  document.getElementById("watchlist-import-cancel").addEventListener("click",clearImport);
  document.getElementById("watchlist-import-apply").addEventListener("click",()=>{
    if(!importSymbols)return;revision++;symbols=[...importSymbols];saveList();if(storageAvailable){messageKey="imported";messageValues={count:symbols.length};}clearImport();
    if(window.StockPredictScoreboard?.refresh)window.StockPredictScoreboard.refresh();else loadQuotes(true);render();
  });
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
  function quoteProgress(symbol) {
    const entry = quotes[symbol];
    if (!entry?.loading) return t("quoteFailed");
    if (entry.started != null) return t("fetching", {seconds:Math.max(0,Math.floor((Date.now()-entry.started)/1000))});
    return t("queued", {position:Math.max(1,quoteQueue.indexOf(symbol)+1),total:Math.max(1,quoteQueue.length)});
  }
  function updateProgress() {
    document.querySelectorAll?.(".quote-progress").forEach(e=>{e.textContent=quoteProgress(e.getAttribute("data-quote-symbol"))});
    if (adding && addingStarted != null) document.getElementById("watchlist-message").textContent = t("validating", {symbol:addingSymbol,seconds:Math.max(0,Math.floor((Date.now()-addingStarted)/1000))});
    const active=adding || Object.values(quotes).some(q=>q.loading);
    if (active && !progressTimer) progressTimer=setInterval(updateProgress,1000);
    if (!active && progressTimer) {clearInterval(progressTimer);progressTimer=null;}
  }
  async function drainQuotes(current) {
    if (quoteRunning === current) return;
    quoteRunning=current;
    try {
      while (quoteQueue.length && current === quoteGeneration) {
        const symbol=quoteQueue.shift();if(!symbols.includes(symbol))continue;
        const request=new AbortController();quoteController=request;
        const cached=quotes[symbol]?.quote;
        if (!cached) quotes[symbol]={loading:true,started:Date.now()};
        render();let timer=setTimeout(()=>request.abort(),30000);
        try {
          const quote=cached || await fetchQuote(symbol,request.signal);
          if(current!==quoteGeneration || !symbols.includes(symbol))return;
          quotes[symbol]={quote};clearTimeout(timer);
          if (quote.fresh) {
            quotes[symbol].research={loading:true};render();
            timer=setTimeout(()=>request.abort(),20000);
            try {
              const params=new URLSearchParams({symbol,source:"twse",horizon:"5",market_context:"none",lang:i18n.getLanguage()});
              const response=await fetch(`/api/analysis?${params}`,{cache:"no-store",signal:request.signal});
              if(!response.ok)throw new Error("research unavailable");
              const data=validateResearch(await response.json(),quote);
              if(!data)throw new Error("research validation failed");
              if(current===quoteGeneration && symbols.includes(symbol))quotes[symbol]={quote,research:{data}};
            } catch {if(current===quoteGeneration && symbols.includes(symbol))quotes[symbol]={quote,research:{error:true}};}
          }
        } catch {if(current===quoteGeneration && symbols.includes(symbol))quotes[symbol]={};}
        finally {clearTimeout(timer)}
        if(current===quoteGeneration)render();
      }
    } finally {if(current===quoteGeneration){quoteRunning=null;render()}}
  }
  function loadQuotes(refresh = false) {
    const current=++quoteGeneration;quoteController?.abort();quoteRunning=null;
    const selected=symbols.filter(x=>!defaults.includes(x));
    if(refresh)admissions={};
    quotes=Object.fromEntries(selected.map(symbol=>[symbol,!refresh&&quotes[symbol]?.quote?quotes[symbol]:{loading:true}]));
    quoteQueue=selected.filter(symbol=>!quotes[symbol]?.quote || (quotes[symbol].quote.fresh && !quotes[symbol].research));render();drainQuotes(current);
  }
  function retryQuote(symbol) {
    if(!symbols.includes(symbol)||quotes[symbol]?.loading||quotes[symbol]?.research?.loading||quoteQueue.includes(symbol))return;
    quotes[symbol]={loading:true};quoteQueue.push(symbol);render();drainQuotes(quoteGeneration);
  }
  async function checkAdmission(symbol) {
    const current=quoteGeneration,request=new AbortController(),timer=setTimeout(()=>request.abort(),30000);
    admissions[symbol]={loading:true};render();
    try {
      const response=await fetch(`/api/collection/readiness?symbol=${encodeURIComponent(symbol)}`,{cache:"no-store",signal:request.signal});
      if(!response.ok)throw new Error("unavailable");const report=await response.json();
      if(report.symbol!==symbol||report.read_only!==true||!["review_required","blocked"].includes(report.status)||!report.checks)throw new Error("invalid check");
      if(current===quoteGeneration&&symbols.includes(symbol))admissions[symbol]={report};
    } catch {if(current===quoteGeneration&&symbols.includes(symbol))admissions[symbol]={error:true};}
    finally {clearTimeout(timer);if(current===quoteGeneration)render()}
  }
  document.getElementById("watchlist-form").addEventListener("submit", async event => {
    event.preventDefault(); if (adding) return;
    const symbol = normalizeWatchSymbol(document.getElementById("watchlist-symbol").value);
    messageKey = !symbol ? "invalid" : symbols.includes(symbol) ? "duplicate" : symbols.length >= maxStocks ? "limit" : "";
    if (messageKey) { render(); return; }
    const current = revision;
    const request = new AbortController(); const timer = setTimeout(() => request.abort(), 30000);
    adding = true; addingStarted=Date.now();addingSymbol=symbol; render();
    try {
      const quote = defaults.includes(symbol) ? null : await fetchQuote(symbol, request.signal);
      if (current !== revision) return;
      symbols.push(symbol); if (quote) quotes[symbol] = { quote }; saveList();
      if (storageAvailable) { messageKey = "added"; messageValues = { symbol }; }
      document.getElementById("watchlist-symbol").value = "";
      if (defaults.includes(symbol)) window.StockPredictScoreboard?.refresh();
      else if (quote.fresh) {quoteQueue.push(symbol);drainQuotes(quoteGeneration);}
    } catch { if (current === revision) messageKey = "addFailed"; }
    finally { clearTimeout(timer); adding = false; addingStarted=null; render(); }
  });
  window.addEventListener("stockpredict-watch-symbol",event=>{
    const symbol=normalizeWatchSymbol(event.detail?.symbol);if(!symbol)return;
    document.getElementById("watchlist-symbol").value=symbol;
    document.getElementById("watchlist-form").requestSubmit();
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
  i18n.subscribe(()=>{render();if(importSymbols)document.getElementById("watchlist-import-preview").textContent=t("importPreview",{symbols:importSymbols.join(", ")||t("importEmpty")});});reset();
})();
