"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const form = $("analysis-form");
  const source = $("source");
  const symbol = $("symbol");
  const horizon = $("horizon");
  const overnightControl = $("us-overnight");
  const factorSource = $("us-factor-source");
  const I18n = window.StockPredictI18n;
  const t = I18n.t;
  let number;
  let shortNumber;
  let dateLabel;
  let weekday;

  function updateFormatters() {
    const locale = I18n.getLanguage();
    number = new Intl.NumberFormat(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    shortNumber = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 });
    dateLabel = new Intl.DateTimeFormat(locale, { month: "2-digit", day: "2-digit", timeZone: "UTC" });
    weekday = new Intl.DateTimeFormat(locale, { weekday: "short", timeZone: "UTC" });
  }
  updateFormatters();
  const ns = "http://www.w3.org/2000/svg";
  const sourceKey = { demo: "source.demoShort", yahoo: "source.yahoo", twse: "source.twseShort", csv: "source.csv" };
  let analysis = null;
  let csvText = null;
  let range = 126;
  let request = null;
  let requestId = 0;
  let chartPoints = [];
  let chartGeometry = null;
  let chartIndex = -1;
  let twseRetry = null;
  let errorState = null;
  let loading = false;
  let loadingSource = source.value;
  const factorFiles = ["umc", "soxx"].map((id) => ({ id, text: null, name: "", state: "empty", version: 0 }));
  let referenceCatalog = null;
  let catalogState = "loading";
  let referencePatterns = null;
  let factorSelectionKey = null;

  function presentation() {
    return analysis?.locales?.[I18n.getLanguage()] || analysis;
  }

  const format = (value) => Number.isFinite(value) ? number.format(value) : "—";
  const percent = (value, signed = false) => Number.isFinite(value) ? `${signed && value > 0 ? "+" : ""}${format(value)}%` : "—";
  const parsedDate = (value) => new Date(`${value}T00:00:00Z`);
  const changeClass = (element, value) => {
    element.classList.remove("positive", "negative");
    if (Number.isFinite(value) && value !== 0) element.classList.add(value > 0 ? "positive" : "negative");
  };
  const text = (id, value) => { $(id).textContent = value; };

  function renderError() {
    if (!errorState) return;
    const language = I18n.getLanguage();
    const message = errorState.key ? t(errorState.key) : errorState.locales?.[language]
      || (errorState.language === language ? errorState.message : t("error.generic"));
    const prefix = errorState.symbol ? `${errorState.symbol} (${t(sourceKey[errorState.source])}): ` : "";
    const previous = analysis ? ` ${t("error.preserved", { symbol: analysis.symbol, source: presentation().source_label })}` : "";
    text("error-text", `${prefix}${message}${previous}`);
    $("twse-retry").hidden = !twseRetry;
    $("error-message").hidden = false;
  }

  function showError(state, retry = null) {
    errorState = typeof state === "string" ? { message: state, language: I18n.getLanguage() } : state;
    twseRetry = retry;
    renderError();
  }

  function translatedError(key) {
    const error = new Error(t(key));
    error.translationKey = key;
    return error;
  }

  function updateSourceUi() {
    $("csv-area").hidden = source.value !== "csv";
    $("source-help").hidden = source.value !== "twse";
    const supported = supportsOvernight();
    overnightControl.disabled = !supported;
    if (!supported) overnightControl.checked = false;
    updateFactorFilesUi();
  }

  function validProfile(profile) {
    return profile && profile.market === "taiwan" && typeof profile.id === "string"
      && ["adr_sector", "broad_market"].includes(profile.kind)
      && Array.isArray(profile.symbols) && profile.symbols.length === 2
      && new Set(profile.symbols).size === 2
      && profile.symbols.every((code) => typeof code === "string" && /^[A-Z][A-Z0-9.-]{0,9}$/.test(code))
      && ["zh-TW", "en"].every((language) => Array.isArray(profile.names?.[language])
        && profile.names[language].length === 2 && profile.names[language].every((name) => typeof name === "string" && name.length <= 100));
  }

  function canonicalTaiwanSymbol(value) {
    if (!referencePatterns) return null;
    const normalized = value.trim().toUpperCase();
    return referencePatterns.bare.test(normalized) ? `${normalized}.TW` : referencePatterns.taiwan.test(normalized) ? normalized : null;
  }

  function profileForSymbol(value) {
    const normalized = canonicalTaiwanSymbol(value);
    if (!referenceCatalog || !normalized) return null;
    const id = referenceCatalog.stock_profiles[normalized] || referenceCatalog.default_taiwan_profile;
    return referenceCatalog.profiles[id] || null;
  }

  function formProfile(value = symbol.value, selectedSource = source.value) {
    const normalized = canonicalTaiwanSymbol(value);
    if (!["twse", "yahoo"].includes(selectedSource) || !normalized) return null;
    if (selectedSource === "twse" && !/^[0-9]{4,6}\.TW$/.test(normalized)) return null;
    return profileForSymbol(normalized);
  }

  function profileNames(profile) {
    return profile?.names?.[I18n.getLanguage()] || profile?.symbols || [];
  }

  function returnedProfile(context) {
    if (validProfile(context.reference_profile)) return context.reference_profile;
    const configured = profileForSymbol(analysis.symbol);
    if (configured) return configured;
    // Compatibility with responses from the original UMC-only release.
    return analysis.symbol === "2303.TW" ? {
      id: "umc", market: "taiwan", kind: "adr_sector", symbols: ["UMC", "SOXX"],
      names: { "zh-TW": ["聯電 ADR（UMC）", "半導體 ETF（SOXX）"], en: ["UMC ADR (UMC)", "Semiconductor ETF (SOXX)"] },
    } : null;
  }

  async function loadReferenceCatalog() {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 4000);
    try {
      const response = await fetch("/api/reference-profiles", { signal: controller.signal });
      if (!response.ok) throw new Error("Reference catalog unavailable");
      const catalog = await response.json();
      if (!catalog || typeof catalog.profiles !== "object" || !catalog.profiles || Array.isArray(catalog.profiles)
          || !Object.values(catalog.profiles).every(validProfile)
          || typeof catalog.stock_profiles !== "object" || !catalog.stock_profiles || Array.isArray(catalog.stock_profiles)
          || !catalog.profiles[catalog.default_taiwan_profile]
          || !Object.values(catalog.stock_profiles).every((id) => typeof id === "string" && catalog.profiles[id])
          || typeof catalog.taiwan_pattern !== "string" || catalog.taiwan_pattern.length > 160
          || typeof catalog.bare_taiwan_pattern !== "string" || catalog.bare_taiwan_pattern.length > 160) throw new Error("Invalid reference catalog");
      const patterns = { taiwan: new RegExp(catalog.taiwan_pattern), bare: new RegExp(catalog.bare_taiwan_pattern) };
      referenceCatalog = catalog;
      referencePatterns = patterns;
      catalogState = "ready";
    } catch {
      catalogState = "unavailable";
    } finally {
      window.clearTimeout(timeout);
    }
  }

  function supportsOvernight(value = symbol.value, selectedSource = source.value) {
    return Boolean(formProfile(value, selectedSource));
  }

  function clearFactorFiles() {
    for (const file of factorFiles) {
      file.version += 1;
      file.text = null;
      file.name = "";
      file.state = "empty";
      $(`${file.id}-csv-file`).value = "";
    }
  }

  function updateFactorFilesUi() {
    const profile = formProfile();
    const selectedTarget = canonicalTaiwanSymbol(symbol.value) || symbol.value.trim().toUpperCase();
    const selectionKey = `${selectedTarget}:${profile?.id || "unsupported"}`;
    if (factorSelectionKey !== selectionKey) {
      clearFactorFiles();
      factorSelectionKey = selectionKey;
    }
    const names = profileNames(profile);
    text("us-overnight-label", profile ? t("overnight.enable", { symbols: profile.symbols.join(" + ") }) : t("overnight.enableGeneric"));
    text("us-overnight-help", catalogState === "ready" ? t(profile?.kind === "broad_market" ? "overnight.controlHelpMarket" : "overnight.controlHelp") : t(catalogState === "loading" ? "overnight.catalogLoading" : "overnight.catalogUnavailable"));
    text("us-factor-csv-option", profile ? t("overnight.sourceCsv", { symbols: profile.symbols.join(" + ") }) : t("overnight.sourceCsvGeneric"));
    const active = overnightControl.checked && supportsOvernight();
    $("us-factor-options").hidden = !active;
    factorSource.disabled = !active;
    $("us-factor-files").hidden = factorSource.value !== "csv";
    for (const [index, file] of factorFiles.entries()) {
      const code = profile?.symbols[index] || String(index + 1);
      $(`${file.id}-csv-label`).textContent = t("overnight.factorCsv", { name: names[index] || t("overnight.factorSlot", { index: index + 1 }) });
      $(`${file.id}-csv-file`).disabled = !active || factorSource.value !== "csv";
      const key = file.state === "ready" ? "overnight.csvLoaded" : file.state === "reading" ? "overnight.csvReading" : file.state === "empty" ? "overnight.csvNotSelected" : file.state;
      $(`${file.id}-csv-status`).textContent = t(key, { symbol: code, name: file.name });
    }
  }

  async function readFactorFile(index, event) {
    const state = factorFiles[index];
    const version = ++state.version;
    state.text = null;
    const file = event.target.files[0];
    state.name = file?.name || "";
    state.state = file ? "reading" : "empty";
    updateFactorFilesUi();
    if (!file) return;
    if (file.size > 2_000_000) {
      state.state = "overnight.csvTooLarge";
      updateFactorFilesUi();
      showError({ key: state.state });
      return;
    }
    try {
      const contents = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
      if (state.version !== version) return;
      if (!contents.trim()) {
        state.state = "overnight.csvEmpty";
        showError({ key: state.state });
      } else {
        state.text = contents;
        state.state = "ready";
      }
    } catch {
      if (state.version !== version) return;
      state.state = "overnight.csvRead";
      showError({ key: state.state });
    }
    updateFactorFilesUi();
  }

  function setLoading(active, requestedSource = loadingSource) {
    loading = active;
    loadingSource = requestedSource;
    $("loading-message").hidden = !loading;
    text("loading-text", t(requestedSource === "twse" ? "loading.twse" : "loading.analysis"));
    $("analyze-button").disabled = loading;
    $("analyze-button").querySelector("span").textContent = t(loading ? "controls.analyzing" : "controls.analyze");
    $("results").setAttribute("aria-busy", String(loading));
    document.querySelectorAll("[data-symbol]").forEach((button) => { button.disabled = loading; });
  }

  function errorDetail(body) {
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return t("error.validation");
    return t("error.generic");
  }

  async function runAnalysis() {
    const requestedSymbol = symbol.value.trim().toUpperCase();
    if (!requestedSymbol) { showError({ key: "error.symbol" }); symbol.focus(); return; }
    if (source.value === "csv" && csvText === null) { showError({ key: "error.csvRequired" }); $("csv-file").focus(); return; }
    symbol.value = requestedSymbol;
    const requestedSource = source.value;
    const requestedHorizon = horizon.value;
    const requestedLanguage = I18n.getLanguage();
    const requestedContext = overnightControl.checked && supportsOvernight(requestedSymbol, requestedSource);
    const requestedProfile = requestedContext ? formProfile(requestedSymbol, requestedSource) : null;
    const factorsFromCsv = requestedContext && factorSource.value === "csv";
    const requestedFactors = requestedProfile ? Object.fromEntries(requestedProfile.symbols.map((code, index) => [code, factorFiles[index].text])) : null;
    if (factorsFromCsv && Object.values(requestedFactors).some((contents) => !contents)) {
      const reading = factorFiles.some((file) => file.state === "reading");
      showError({ key: reading ? "overnight.csvReading" : "overnight.csvRequired" });
      $(`${factorFiles.find((file) => !file.text).id}-csv-file`).focus();
      return;
    }
    if (request) request.abort();
    const controller = new AbortController();
    request = controller;
    const currentRequest = ++requestId;
    $("error-message").hidden = true;
    errorState = null;
    $("twse-retry").hidden = true;
    twseRetry = null;
    $("empty-state").hidden = true;
    setLoading(true, requestedSource);
    const timeout = window.setTimeout(() => controller.abort(), requestedContext ? 90000 : requestedSource === "twse" ? 60000 : 35000);
    try {
      const fromCsv = requestedSource === "csv";
      const params = new URLSearchParams({ symbol: requestedSymbol, source: requestedSource, horizon: requestedHorizon, lang: requestedLanguage });
      if (requestedContext) params.set("market_context", "us_overnight");
      const endpoint = factorsFromCsv ? `/api/analysis/overnight/csv?${new URLSearchParams({ lang: requestedLanguage })}` : fromCsv ? `/api/analysis/csv?${new URLSearchParams({ lang: requestedLanguage })}` : `/api/analysis?${params}`;
      const response = await fetch(endpoint, factorsFromCsv ? {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: requestedSymbol, source: requestedSource, horizon: Number(requestedHorizon), factor_csvs: requestedFactors }),
        signal: controller.signal,
      } : fromCsv ? {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: requestedSymbol, horizon: Number(requestedHorizon), csv: csvText }),
        signal: controller.signal,
      } : { signal: controller.signal });
      let body;
      try { body = await response.json(); } catch { throw translatedError("error.response"); }
      if (!response.ok) {
        const error = new Error(errorDetail(body));
        error.locales = body.locales;
        if (Array.isArray(body.detail)) error.translationKey = "error.validation";
        throw error;
      }
      if (currentRequest !== requestId) return;
      analysis = body;
      renderResults();
    } catch (error) {
      if (currentRequest !== requestId) return;
      const retry = requestedSource === "yahoo" && /^\d{4,6}(?:\.TW)?$/.test(requestedSymbol) ? { symbol: requestedSymbol, horizon: requestedHorizon } : null;
      const key = error.name === "AbortError" ? "error.timeout" : error.translationKey
        || (error instanceof TypeError ? "error.connection" : null);
      showError({ key, message: error.message || t("error.connection"), locales: error.locales,
        language: requestedLanguage, symbol: requestedSymbol, source: requestedSource }, retry);
      $("empty-state").hidden = Boolean(analysis);
    } finally {
      window.clearTimeout(timeout);
      if (currentRequest === requestId) setLoading(false);
    }
  }

  function renderResults() {
    const { summary, backtest, forecast, history } = analysis;
    const view = presentation();
    $("results").hidden = false;
    text("security-name", presentation().name || analysis.symbol);
    text("security-initial", (presentation().name || analysis.symbol).slice(0, 1));
    text("result-symbol", analysis.symbol);
    text("result-date", t("result.date", { date: analysis.as_of, count: history.length }));
    text("source-badge", view.source_label);
    $("source-badge").classList.toggle("real", analysis.source !== "demo");
    text("currency-label", analysis.currency || t("result.price"));
    text("last-close", format(summary.last_close));
    text("day-change", t("result.dayChange", { change: percent(summary.day_change_pct, true) }));
    changeClass($("day-change"), summary.day_change_pct);
    text("forecast-change", percent(summary.forecast_change_pct, true));
    changeClass($("forecast-change"), summary.forecast_change_pct);
    text("forecast-caption", t("result.forecastCaption", { count: forecast.length, price: format(forecast.at(-1).close) }));
    text("volatility", percent(summary.annualized_volatility_pct));
    text("mae", format(backtest.mae));
    text("mae-caption", t("result.maeCaption", { currency: analysis.currency || t("result.priceUnit") }));
    text("model-mae", format(backtest.mae));
    text("baseline-mae", format(backtest.baseline_mae));
    text("backtest-description", t("backtest.description", { count: backtest.observations }));
    text("direction-accuracy", percent(backtest.direction_accuracy_pct));
    text("rmse", format(backtest.rmse));
    text("mape", percent(backtest.mape_pct));
    text("observations", t("backtest.count", { count: backtest.observations }));
    const maxError = Math.max(backtest.mae, backtest.baseline_mae, Number.EPSILON);
    $("model-bar").style.width = `${Math.max(0, backtest.mae / maxError * 100)}%`;
    $("baseline-bar").style.width = `${Math.max(0, backtest.baseline_mae / maxError * 100)}%`;
    $("baseline-comparison").classList.toggle("underperform", !backtest.model_beats_baseline);
    text("baseline-comparison", t(backtest.model_beats_baseline ? "backtest.better" : "backtest.worse"));
    $("model-description").removeAttribute("data-i18n");
    $("interval-description").removeAttribute("data-i18n");
    text("model-description", view.model.description);
    text("interval-description", view.model.interval_description);
    renderWarnings();
    const recent = history.slice(-30).map((point) => point.close);
    const low = Math.min(...recent), spread = Math.max(...recent) - low || 1;
    $("metric-spark-path").setAttribute("d", recent.map((close, index) => `${index ? "L" : "M"}${2 + index / Math.max(recent.length - 1, 1) * 86},${28 - (close - low) / spread * 24}`).join(" "));
    renderForecast();
    renderChart();
    renderOvernight();
  }

  function formatInstant(value) {
    const instant = typeof value === "string" ? new Date(value) : null;
    return instant && Number.isFinite(instant.getTime()) ? new Intl.DateTimeFormat(I18n.getLanguage(), {
      year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
      hourCycle: "h23", timeZone: "Asia/Taipei",
    }).format(instant) : "—";
  }

  function renderOvernight() {
    const context = analysis.market_context;
    const panel = $("overnight-panel");
    const cards = $("overnight-factors");
    const rows = $("overnight-backtest-rows");
    cards.replaceChildren();
    rows.replaceChildren();
    cards.hidden = true;
    $("overnight-forecast").hidden = true;
    $("overnight-backtest").hidden = true;
    $("overnight-correlation-period").hidden = true;
    for (const id of ["overnight-status", "overnight-data-source", "overnight-required-session", "overnight-available-after", "overnight-target", "overnight-factor-close", "overnight-ar-close", "overnight-factor-change", "overnight-correlation-period", "overnight-backtest-period", "overnight-backtest-verdict"]) text(id, "");
    changeClass($("overnight-factor-change"), null);
    $("overnight-required-session").hidden = true;
    $("overnight-available-after").hidden = true;
    panel.hidden = !context;
    if (!context) return;
    const profile = returnedProfile(context);
    const names = profileNames(profile);
    text("overnight-title", t("overnight.title", { symbol: analysis.symbol }));
    text("overnight-intro", t(profile?.kind === "broad_market" ? "overnight.introMarket" : "overnight.intro"));
    const status = ["ready", "waiting"].includes(context.status) ? context.status : "unavailable";
    const usingFactors = status === "ready";
    const reasonKeys = ["data_unavailable", "waiting_for_us_close", "missing_sessions", "insufficient_history", "stale_history", "us_session_not_closed", "missing_us_sessions", "insufficient_aligned_history", "missing_factors", "invalid_factor_data", "incomplete_history", "us_rate_limited", "us_access_denied", "us_connection_failed", "us_invalid_data", "us_unavailable", "us_busy"];
    const reason = reasonKeys.includes(context.reason) ? ` ${t(`overnight.reason.${context.reason}`)}` : "";
    text("overnight-status", `${t(`overnight.status.${status}`)}${reason}`);
    $("overnight-status").dataset.status = status;
    text("overnight-data-source", t(usingFactors ? context.data_source === "csv" ? "overnight.dataSourceCsv" : "overnight.dataSourceYahoo" : "overnight.noDataUsed"));
    const requiredSession = typeof context.required_us_session_date === "string" && /^\d{4}-\d{2}-\d{2}$/.test(context.required_us_session_date) ? context.required_us_session_date : null;
    text("overnight-required-session", requiredSession ? t("overnight.requiredSession", { date: requiredSession }) : "");
    $("overnight-required-session").hidden = !requiredSession;
    const availableAfter = formatInstant(context.available_after);
    text("overnight-available-after", availableAfter !== "—" ? t("overnight.availableAfter", { time: availableAfter }) : "");
    $("overnight-available-after").hidden = availableAfter === "—";
    const retrySeconds = Number.isFinite(context.retry_after_seconds) && context.retry_after_seconds > 0 ? Math.ceil(context.retry_after_seconds) : null;
    text("overnight-retry-help", retrySeconds ? t("overnight.retryHelp", { seconds: retrySeconds }) : "");
    $("overnight-retry-help").hidden = !retrySeconds;
    $("overnight-csv-switch").hidden = context.data_source === "csv" || status !== "unavailable" || !["data_unavailable", "us_rate_limited", "us_access_denied", "us_connection_failed", "us_invalid_data", "us_unavailable", "us_busy"].includes(context.reason);
    const estimate = context.forecast;
    const originalEstimate = analysis.forecast?.[0]?.close;
    const ready = status === "ready" && Number.isFinite(estimate?.close) && Number.isFinite(originalEstimate);
    $("overnight-forecast").hidden = !ready;
    if (ready) {
      text("overnight-target", t("overnight.target", { date: estimate.date || context.target_date || "—" }));
      text("overnight-factor-close", format(estimate.close));
      text("overnight-ar-close", format(originalEstimate));
      text("overnight-factor-change", t("overnight.change", { change: percent(estimate.change_pct, true) }));
      changeClass($("overnight-factor-change"), estimate.change_pct);
    }
    const factors = usingFactors && Array.isArray(context.factors) ? context.factors : [];
    cards.hidden = !usingFactors || !profile;
    for (const [index, symbolName] of (usingFactors ? profile?.symbols || [] : []).entries()) {
      const factor = factors.find((item) => item?.symbol === symbolName) || {};
      const card = document.createElement("article");
      card.className = "overnight-factor";
      const heading = document.createElement("h4");
      heading.textContent = names[index] || symbolName;
      const sessions = document.createElement("p");
      sessions.textContent = t("overnight.sessions", { first: factor.first_session || "—", last: factor.last_session || "—" });
      const change = document.createElement("strong");
      change.textContent = t("overnight.return", { value: percent(factor.return_pct, true) });
      changeClass(change, factor.return_pct);
      const correlation = document.createElement("p");
      const coefficient = Number.isFinite(factor.correlation) && Math.abs(factor.correlation) <= 1 ? format(factor.correlation) : "—";
      correlation.textContent = t("overnight.correlation", { value: coefficient, count: Number.isInteger(factor.samples) && factor.samples >= 0 ? factor.samples : "—" });
      const available = document.createElement("small");
      available.textContent = t("overnight.available", { time: formatInstant(factor.available_at) });
      card.append(heading, sessions, change, correlation, available);
      cards.append(card);
    }
    const correlationWindow = usingFactors ? context.correlations_window : null;
    $("overnight-correlation-period").hidden = !correlationWindow;
    text("overnight-correlation-period", correlationWindow ? t("overnight.correlationPeriod", {
      start: correlationWindow.start || "—", end: correlationWindow.end || "—", count: Number.isInteger(correlationWindow.samples) ? correlationWindow.samples : "—",
    }) : "");
    const backtest = usingFactors ? context.backtest : null;
    $("overnight-backtest").hidden = !backtest;
    if (!backtest) return;
    text("overnight-backtest-period", t("overnight.backtestPeriod", {
      start: backtest.start || "—", end: backtest.end || "—", count: Number.isInteger(backtest.observations) ? backtest.observations : "—",
    }));
    for (const [key, mae, direction] of [
      ["overnight.factorModel", backtest.factor_mae, backtest.factor_direction_accuracy_pct],
      ["overnight.arModel", backtest.ar_mae, backtest.ar_direction_accuracy_pct],
      ["overnight.baselineModel", backtest.baseline_mae, backtest.baseline_direction_accuracy_pct],
    ]) {
      const row = document.createElement("tr");
      const label = document.createElement("th");
      label.scope = "row";
      label.textContent = t(key);
      const error = document.createElement("td");
      error.textContent = format(mae);
      const accuracy = document.createElement("td");
      accuracy.textContent = percent(direction);
      row.append(label, error, accuracy);
      rows.append(row);
    }
    const improved = Number.isFinite(backtest.improvement_pct) && backtest.improvement_pct > 0;
    text("overnight-backtest-verdict", improved ? t("overnight.improved", { value: percent(backtest.improvement_pct) }) : t("overnight.notImproved"));
  }

  function renderWarnings() {
    const container = $("warnings");
    container.replaceChildren();
    const warnings = presentation().warnings || [];
    if (!warnings.length) return;
    const notice = document.createElement("div");
    notice.className = "notice";
    const lead = document.createElement("p");
    lead.textContent = warnings[0];
    notice.append(lead);
    if (warnings.length > 1) {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = t("result.limitations", { count: warnings.length - 1 });
      details.append(summary);
      const list = document.createElement("ul");
      for (const warning of warnings.slice(1)) {
        const item = document.createElement("li");
        item.textContent = warning;
        list.append(item);
      }
      details.append(list);
      notice.append(details);
    }
    container.append(notice);
  }

  function renderForecast() {
    const rows = $("forecast-rows");
    rows.replaceChildren();
    for (const point of analysis.forecast) {
      const row = document.createElement("tr");
      const dateCell = document.createElement("td");
      dateCell.append(document.createTextNode(point.date));
      const day = document.createElement("span");
      day.className = "table-date-day";
      day.textContent = weekday.format(parsedDate(point.date));
      dateCell.append(day);
      row.append(dateCell);
      const price = document.createElement("td");
      price.textContent = format(point.close);
      row.append(price);
      const delta = (point.close / analysis.summary.last_close - 1) * 100;
      const change = document.createElement("td");
      change.textContent = percent(delta, true);
      changeClass(change, delta);
      row.append(change);
      for (const key of ["lower", "upper"]) {
        const cell = document.createElement("td");
        cell.textContent = format(point[key]);
        row.append(cell);
      }
      rows.append(row);
    }
  }

  function svgElement(tag, attrs = {}, content) {
    const el = document.createElementNS(ns, tag);
    for (const [name, value] of Object.entries(attrs)) el.setAttribute(name, String(value));
    if (content !== undefined) el.textContent = String(content);
    return el;
  }

  function renderChart() {
    if (!analysis) return;
    const svg = $("price-chart");
    svg.replaceChildren();
    $("chart-tooltip").hidden = true;
    const history = analysis.history.slice(-range);
    const forecast = analysis.forecast;
    chartPoints = [...history.map((p) => ({ ...p, predicted: false })), ...forecast.map((p) => ({ ...p, predicted: true }))];
    const compact = $("chart-container").clientWidth < 480;
    const width = 940, height = compact ? 520 : 370;
    const left = compact ? 106 : 65, right = 25, top = compact ? 32 : 24, bottom = compact ? 54 : 39;
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.style.setProperty("--chart-text-size", compact ? "22px" : "11px");
    svg.style.setProperty("--chart-small-text-size", compact ? "20px" : "10px");
    const chartWidth = width - left - right, chartHeight = height - top - bottom;
    const values = [...history.map((p) => p.close), ...forecast.flatMap((p) => [p.lower, p.upper])];
    const low = Math.min(...values), high = Math.max(...values);
    const padding = Math.max((high - low) * .14, high * .015, .01);
    const min = Math.max(0, low - padding), max = high + padding;
    const x = (index) => left + index / Math.max(chartPoints.length - 1, 1) * chartWidth;
    const y = (price) => top + (max - price) / (max - min) * chartHeight;
    chartGeometry = { x, y, left, top, chartWidth, chartHeight, width, height };
    chartIndex = history.length - 1;
    const defs = svgElement("defs");
    const gradient = svgElement("linearGradient", { id: "history-gradient", x1: 0, x2: 0, y1: 0, y2: 1 });
    gradient.append(svgElement("stop", { offset: "0%", "stop-color": "#6094d9", "stop-opacity": ".12" }));
    gradient.append(svgElement("stop", { offset: "100%", "stop-color": "#6094d9", "stop-opacity": ".01" }));
    defs.append(gradient);
    svg.append(defs);
    for (let i = 0; i <= 4; i++) {
      const value = max - (max - min) * i / 4;
      const py = top + chartHeight * i / 4;
      svg.append(svgElement("line", { x1: left, y1: py, x2: width - right, y2: py, class: "grid" }));
      svg.append(svgElement("text", { x: left - 12, y: py + 4, "text-anchor": "end" }, shortNumber.format(value)));
    }
    const historyPath = history.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p.close)}`).join(" ");
    const fillPath = `${historyPath} L${x(history.length - 1)},${top + chartHeight} L${left},${top + chartHeight} Z`;
    svg.append(svgElement("path", { d: fillPath, class: "area" }));
    const start = history.length - 1;
    const initial = history.at(-1);
    const forward = [{ ...initial, lower: initial.close, upper: initial.close }, ...forecast];
    const bandTop = forward.map((p, i) => `${i ? "L" : "M"}${x(start + i)},${y(p.upper)}`).join(" ");
    const bandBottom = [...forward].reverse().map((p, i) => `L${x(start + forward.length - 1 - i)},${y(p.lower)}`).join(" ");
    svg.append(svgElement("path", { d: `${bandTop} ${bandBottom} Z`, class: "band" }));
    svg.append(svgElement("line", { x1: x(start), y1: top, x2: x(start), y2: top + chartHeight, class: "boundary" }));
    svg.append(svgElement("text", { x: Math.min(x(start) + 9, width - 100), y: top + 13, class: "chart-date-label" }, t("chart.boundary")));
    svg.append(svgElement("path", { d: historyPath, class: "history-path" }));
    svg.append(svgElement("path", { d: forward.map((p, i) => `${i ? "L" : "M"}${x(start + i)},${y(p.close)}`).join(" "), class: "forecast-path" }));
    svg.append(svgElement("circle", { cx: x(start), cy: y(initial.close), r: 3.5, fill: "#3973c8", stroke: "white", "stroke-width": 2 }));
    const labelIndexes = new Set([0, Math.round((chartPoints.length - 1) * .25), Math.round((chartPoints.length - 1) * .5), Math.round((chartPoints.length - 1) * .75), chartPoints.length - 1]);
    for (const index of labelIndexes) svg.append(svgElement("text", { x: x(index), y: height - 13, "text-anchor": index === 0 ? "start" : index === chartPoints.length - 1 ? "end" : "middle" }, dateLabel.format(parsedDate(chartPoints[index].date))));
    svg.append(svgElement("line", { id: "chart-crosshair", class: "crosshair", x1: 0, x2: 0, y1: top, y2: top + chartHeight, visibility: "hidden" }));
    svg.append(svgElement("circle", { id: "chart-hover-dot", r: 4.5, fill: "#17293d", stroke: "#fff", "stroke-width": 2, visibility: "hidden" }));
    svg.removeAttribute("data-i18n-aria-label");
    svg.setAttribute("aria-label", t("chart.aria", { name: presentation().name || analysis.symbol,
      history: history.length, forecast: forecast.length, close: format(initial.close),
      forecastClose: format(forecast.at(-1).close) }));
    text("chart-point-count", t("chart.pointCount", { history: history.length, forecast: forecast.length }));
  }

  function showChartPoint(index) {
    if (!chartGeometry || !chartPoints.length) return;
    chartIndex = Math.max(0, Math.min(index, chartPoints.length - 1));
    const point = chartPoints[chartIndex], { x, y, width } = chartGeometry;
    const crosshair = $("chart-crosshair"), dot = $("chart-hover-dot"), tooltip = $("chart-tooltip");
    crosshair.setAttribute("x1", x(chartIndex)); crosshair.setAttribute("x2", x(chartIndex)); crosshair.setAttribute("visibility", "visible");
    dot.setAttribute("cx", x(chartIndex)); dot.setAttribute("cy", y(point.close)); dot.setAttribute("visibility", "visible");
    tooltip.replaceChildren();
    const date = document.createElement("small"); date.textContent = `${point.date} · ${t(point.predicted ? "chart.predictedPoint" : "chart.historical")}`;
    const price = document.createElement("strong"); price.textContent = `${format(point.close)} ${analysis.currency || ""}`;
    tooltip.append(date, price);
    if (point.predicted) { const band = document.createElement("small"); band.textContent = t("chart.scenario", { lower: format(point.lower), upper: format(point.upper) }); tooltip.append(band); }
    tooltip.hidden = false;
    const rect = $("price-chart").getBoundingClientRect();
    const px = x(chartIndex) / width * rect.width;
    const containerWidth = $("chart-container").clientWidth;
    const tooltipWidth = tooltip.offsetWidth;
    tooltip.style.left = `${Math.max(0, Math.min(px + 12, containerWidth - tooltipWidth - 5))}px`;
    tooltip.style.top = "12px";
  }

  function hideTooltip() {
    $("chart-tooltip").hidden = true;
    $("chart-crosshair")?.setAttribute("visibility", "hidden");
    $("chart-hover-dot")?.setAttribute("visibility", "hidden");
  }

  form.addEventListener("submit", (event) => { event.preventDefault(); runAnalysis(); });
  source.addEventListener("change", updateSourceUi);
  symbol.addEventListener("input", updateSourceUi);
  overnightControl.addEventListener("change", updateFactorFilesUi);
  factorSource.addEventListener("change", updateFactorFilesUi);
  $("umc-csv-file").addEventListener("change", (event) => readFactorFile(0, event));
  $("soxx-csv-file").addEventListener("change", (event) => readFactorFile(1, event));
  $("overnight-csv-switch").addEventListener("click", () => {
    if (!analysis || !profileForSymbol(analysis.symbol)) return;
    symbol.value = analysis.symbol;
    source.value = ["twse", "yahoo"].includes(analysis.source) ? analysis.source : "twse";
    overnightControl.checked = true;
    factorSource.value = "csv";
    updateSourceUi();
    factorSource.scrollIntoView({ behavior: "smooth", block: "center" });
    $("umc-csv-file").focus({ preventScroll: true });
  });
  $("twse-retry").addEventListener("click", () => {
    if (!twseRetry) return;
    symbol.value = twseRetry.symbol;
    horizon.value = twseRetry.horizon;
    source.value = "twse";
    updateSourceUi();
    runAnalysis();
  });
  document.querySelectorAll("[data-symbol]").forEach((button) => button.addEventListener("click", () => {
    symbol.value = button.dataset.symbol;
    if (button.dataset.source) source.value = button.dataset.source;
    else if (source.value === "csv") source.value = "demo";
    else if (source.value === "twse" && !/^\d{4,6}\.TW$/.test(button.dataset.symbol)) source.value = "yahoo";
    updateSourceUi();
    runAnalysis();
  }));
  document.querySelectorAll("[data-range]").forEach((button) => button.addEventListener("click", () => {
    range = Number(button.dataset.range);
    document.querySelectorAll("[data-range]").forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
    renderChart();
  }));
  $("csv-file").addEventListener("change", async (event) => {
    csvText = null;
    const file = event.target.files[0];
    if (!file) return;
    if (file.size > 2_000_000) { showError({ key: "error.csvTooLarge" }); return; }
    try {
      csvText = await file.text();
      if (!csvText.trim()) { csvText = null; showError({ key: "error.csvEmpty" }); return; }
      source.value = "csv";
      updateSourceUi();
      runAnalysis();
    } catch { showError({ key: "error.csvRead" }); }
  });
  $("export-button").addEventListener("click", () => {
    if (!analysis) return;
    const csvCell = (value) => {
      const cell = String(value);
      return /[",\r\n]/.test(cell) ? `"${cell.replace(/"/g, '""')}"` : cell;
    };
    const rows = ["Date,ForecastClose,LowerScenario,UpperScenario,Source,Symbol,SourceLabel", ...analysis.forecast.map((p) => [p.date, p.close, p.lower, p.upper, analysis.source, analysis.symbol, presentation().source_label].map(csvCell).join(","))];
    const url = URL.createObjectURL(new Blob([rows.join("\r\n")], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url;
    link.download = `StockPredict-${analysis.symbol.replace(/[^\w.-]/g, "_")}-${analysis.source}-${analysis.as_of}.csv`;
    document.body.append(link); link.click(); link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  $("price-chart").addEventListener("pointermove", (event) => {
    if (!chartGeometry) return;
    const rect = $("price-chart").getBoundingClientRect();
    const svgX = (event.clientX - rect.left) / rect.width * chartGeometry.width;
    showChartPoint(Math.round((svgX - chartGeometry.left) / chartGeometry.chartWidth * (chartPoints.length - 1)));
  });
  $("price-chart").addEventListener("pointerleave", hideTooltip);
  $("price-chart").addEventListener("blur", hideTooltip);
  $("price-chart").addEventListener("keydown", (event) => {
    if (event.key === "ArrowRight" || event.key === "ArrowLeft") { event.preventDefault(); showChartPoint(chartIndex + (event.key === "ArrowRight" ? 1 : -1)); }
    if (event.key === "Escape") hideTooltip();
  });
  let resizeTimer;
  window.addEventListener("resize", () => { window.clearTimeout(resizeTimer); resizeTimer = window.setTimeout(renderChart, 100); });
  const initial = new URLSearchParams(window.location.search);
  const initialSymbol = initial.get("symbol")?.trim().toUpperCase();
  if (initialSymbol && /^[A-Z0-9^][A-Z0-9.^=\-]{0,19}$/.test(initialSymbol)) symbol.value = initialSymbol;
  if (["demo", "yahoo", "twse"].includes(initial.get("source"))) source.value = initial.get("source");
  if (["5", "10", "20"].includes(initial.get("horizon"))) horizon.value = initial.get("horizon");
  I18n.subscribe(() => {
    updateFormatters();
    updateFactorFilesUi();
    if (analysis) renderResults();
    if (errorState) renderError();
    setLoading(loading, loadingSource);
  });
  async function initialize() {
    updateSourceUi();
    await loadReferenceCatalog();
    if (requestId === 0 && initial.get("market_context") === "us_overnight" && supportsOvernight()) overnightControl.checked = true;
    updateSourceUi();
    if (requestId === 0) runAnalysis();
  }
  initialize();
})();
