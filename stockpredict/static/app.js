"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const form = $("analysis-form");
  const source = $("source");
  const symbol = $("symbol");
  const horizon = $("horizon");
  const number = new Intl.NumberFormat("zh-TW", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const shortNumber = new Intl.NumberFormat("zh-TW", { maximumFractionDigits: 1 });
  const dateLabel = new Intl.DateTimeFormat("zh-TW", { month: "2-digit", day: "2-digit", timeZone: "UTC" });
  const weekday = new Intl.DateTimeFormat("zh-TW", { weekday: "short", timeZone: "UTC" });
  const ns = "http://www.w3.org/2000/svg";
  const sourceNames = { demo: "示範資料", yahoo: "Yahoo 每日行情", twse: "證交所每日行情", csv: "CSV 匯入" };
  let analysis = null;
  let csvText = null;
  let range = 126;
  let request = null;
  let requestId = 0;
  let chartPoints = [];
  let chartGeometry = null;
  let chartIndex = -1;
  let twseRetry = null;

  const format = (value) => Number.isFinite(value) ? number.format(value) : "—";
  const percent = (value, signed = false) => Number.isFinite(value) ? `${signed && value > 0 ? "+" : ""}${format(value)}%` : "—";
  const parsedDate = (value) => new Date(`${value}T00:00:00Z`);
  const changeClass = (element, value) => {
    element.classList.remove("positive", "negative");
    if (Number.isFinite(value) && value !== 0) element.classList.add(value > 0 ? "positive" : "negative");
  };
  const text = (id, value) => { $(id).textContent = value; };

  function showError(message, retry = null) {
    text("error-text", `${message}${analysis ? ` 畫面保留上次成功的 ${analysis.symbol}（${analysis.source_label}）分析結果。` : ""}`);
    twseRetry = retry;
    $("twse-retry").hidden = !retry;
    $("error-message").hidden = false;
  }

  function updateSourceUi() {
    $("csv-area").hidden = source.value !== "csv";
    $("source-help").hidden = source.value !== "twse";
  }

  function setLoading(loading, requestedSource = source.value) {
    $("loading-message").hidden = !loading;
    text("loading-text", requestedSource === "twse" ? "正在取得證交所歷史資料並執行回測；首次讀取可能需要 20–60 秒，請稍候…" : "正在讀取資料並執行歷史回測…");
    $("analyze-button").disabled = loading;
    $("analyze-button").querySelector("span").textContent = loading ? "分析中…" : "開始分析";
    $("results").setAttribute("aria-busy", String(loading));
    document.querySelectorAll("[data-symbol]").forEach((button) => { button.disabled = loading; });
  }

  function errorDetail(body) {
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map((item) => item.msg).filter(Boolean).join("；");
    return "分析未成功，請檢查資料與設定後重試。";
  }

  async function runAnalysis() {
    const requestedSymbol = symbol.value.trim().toUpperCase();
    if (!requestedSymbol) { showError("請輸入股票代碼，例如 2330.TW 或 AAPL。"); symbol.focus(); return; }
    if (source.value === "csv" && csvText === null) { showError("請先選擇包含 Date、Close 欄位的 CSV 檔案。"); $("csv-file").focus(); return; }
    symbol.value = requestedSymbol;
    const requestedSource = source.value;
    const requestedHorizon = horizon.value;
    if (request) request.abort();
    const controller = new AbortController();
    request = controller;
    const currentRequest = ++requestId;
    $("error-message").hidden = true;
    $("twse-retry").hidden = true;
    twseRetry = null;
    $("empty-state").hidden = true;
    setLoading(true, requestedSource);
    const timeout = window.setTimeout(() => controller.abort(), requestedSource === "twse" ? 60000 : 35000);
    try {
      const fromCsv = requestedSource === "csv";
      const endpoint = fromCsv ? "/api/analysis/csv" : `/api/analysis?${new URLSearchParams({ symbol: requestedSymbol, source: requestedSource, horizon: requestedHorizon })}`;
      const response = await fetch(endpoint, fromCsv ? {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: requestedSymbol, horizon: Number(requestedHorizon), csv: csvText }),
        signal: controller.signal,
      } : { signal: controller.signal });
      let body;
      try { body = await response.json(); } catch { throw new Error("伺服器未回傳有效資料，請稍後重試。"); }
      if (!response.ok) throw new Error(errorDetail(body));
      if (currentRequest !== requestId) return;
      analysis = body;
      renderResults();
    } catch (error) {
      if (currentRequest !== requestId) return;
      const retry = requestedSource === "yahoo" && /^\d{4,6}(?:\.TW)?$/.test(requestedSymbol) ? { symbol: requestedSymbol, horizon: requestedHorizon } : null;
      const message = error.name === "AbortError" ? "資料讀取逾時，請重試或使用示範資料與 CSV 匯入。" : error.message || "無法連線至服務，請稍後重試。";
      showError(`${requestedSymbol}（${sourceNames[requestedSource]}）：${message}`, retry);
      $("empty-state").hidden = Boolean(analysis);
    } finally {
      window.clearTimeout(timeout);
      if (currentRequest === requestId) setLoading(false);
    }
  }

  function renderResults() {
    const { summary, backtest, forecast, history } = analysis;
    $("results").hidden = false;
    text("security-name", analysis.name || analysis.symbol);
    text("security-initial", (analysis.name || analysis.symbol).slice(0, 1));
    text("result-symbol", analysis.symbol);
    text("result-date", `資料截至 ${analysis.as_of} · ${history.length} 筆歷史收盤`);
    text("source-badge", analysis.source_label);
    $("source-badge").classList.toggle("real", analysis.source !== "demo");
    text("currency-label", analysis.currency || "價格");
    text("last-close", format(summary.last_close));
    text("day-change", `${percent(summary.day_change_pct, true)} 較前一筆收盤`);
    changeClass($("day-change"), summary.day_change_pct);
    text("forecast-change", percent(summary.forecast_change_pct, true));
    changeClass($("forecast-change"), summary.forecast_change_pct);
    text("forecast-caption", `${forecast.length} 個平日後 · 預估 ${format(forecast.at(-1).close)}`);
    text("volatility", percent(summary.annualized_volatility_pct));
    text("mae", format(backtest.mae));
    text("mae-caption", `模型一天預測 · ${analysis.currency || "價格單位"}`);
    text("model-mae", format(backtest.mae));
    text("baseline-mae", format(backtest.baseline_mae));
    text("backtest-description", `保留最後 ${backtest.observations} 筆，逐日向前驗證`);
    text("direction-accuracy", percent(backtest.direction_accuracy_pct));
    text("rmse", format(backtest.rmse));
    text("mape", percent(backtest.mape_pct));
    text("observations", `${backtest.observations} 筆`);
    const maxError = Math.max(backtest.mae, backtest.baseline_mae, Number.EPSILON);
    $("model-bar").style.width = `${Math.max(0, backtest.mae / maxError * 100)}%`;
    $("baseline-bar").style.width = `${Math.max(0, backtest.baseline_mae / maxError * 100)}%`;
    $("baseline-comparison").classList.toggle("underperform", !backtest.model_beats_baseline);
    text("baseline-comparison", backtest.model_beats_baseline ? "此次回測：模型誤差低於前日收盤基準。" : "此次回測：模型未優於前日收盤基準。解讀預測時請留意。 ");
    text("model-description", analysis.model.description);
    text("interval-description", analysis.model.interval_description);
    renderWarnings();
    const recent = history.slice(-30).map((point) => point.close);
    const low = Math.min(...recent), spread = Math.max(...recent) - low || 1;
    $("metric-spark-path").setAttribute("d", recent.map((close, index) => `${index ? "L" : "M"}${2 + index / Math.max(recent.length - 1, 1) * 86},${28 - (close - low) / spread * 24}`).join(" "));
    renderForecast();
    renderChart();
  }

  function renderWarnings() {
    const container = $("warnings");
    container.replaceChildren();
    const warnings = analysis.warnings || [];
    if (!warnings.length) return;
    const notice = document.createElement("div");
    notice.className = "notice";
    const lead = document.createElement("p");
    lead.textContent = warnings[0];
    notice.append(lead);
    if (warnings.length > 1) {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = `資料與模型限制（${warnings.length - 1} 項）`;
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
    svg.append(svgElement("text", { x: Math.min(x(start) + 9, width - 100), y: top + 13, class: "chart-date-label" }, "預測開始"));
    svg.append(svgElement("path", { d: historyPath, class: "history-path" }));
    svg.append(svgElement("path", { d: forward.map((p, i) => `${i ? "L" : "M"}${x(start + i)},${y(p.close)}`).join(" "), class: "forecast-path" }));
    svg.append(svgElement("circle", { cx: x(start), cy: y(initial.close), r: 3.5, fill: "#3973c8", stroke: "white", "stroke-width": 2 }));
    const labelIndexes = new Set([0, Math.round((chartPoints.length - 1) * .25), Math.round((chartPoints.length - 1) * .5), Math.round((chartPoints.length - 1) * .75), chartPoints.length - 1]);
    for (const index of labelIndexes) svg.append(svgElement("text", { x: x(index), y: height - 13, "text-anchor": index === 0 ? "start" : index === chartPoints.length - 1 ? "end" : "middle" }, dateLabel.format(parsedDate(chartPoints[index].date))));
    svg.append(svgElement("line", { id: "chart-crosshair", class: "crosshair", x1: 0, x2: 0, y1: top, y2: top + chartHeight, visibility: "hidden" }));
    svg.append(svgElement("circle", { id: "chart-hover-dot", r: 4.5, fill: "#17293d", stroke: "#fff", "stroke-width": 2, visibility: "hidden" }));
    svg.setAttribute("aria-label", `${analysis.name || analysis.symbol}：${history.length} 筆歷史收盤與 ${forecast.length} 個平日預測。最新收盤 ${format(initial.close)}，期末預估 ${format(forecast.at(-1).close)}。使用左右方向鍵查看各日期價格。`);
    text("chart-point-count", `顯示 ${history.length} 筆歷史 · ${forecast.length} 筆預測`);
  }

  function showChartPoint(index) {
    if (!chartGeometry || !chartPoints.length) return;
    chartIndex = Math.max(0, Math.min(index, chartPoints.length - 1));
    const point = chartPoints[chartIndex], { x, y, width } = chartGeometry;
    const crosshair = $("chart-crosshair"), dot = $("chart-hover-dot"), tooltip = $("chart-tooltip");
    crosshair.setAttribute("x1", x(chartIndex)); crosshair.setAttribute("x2", x(chartIndex)); crosshair.setAttribute("visibility", "visible");
    dot.setAttribute("cx", x(chartIndex)); dot.setAttribute("cy", y(point.close)); dot.setAttribute("visibility", "visible");
    tooltip.replaceChildren();
    const date = document.createElement("small"); date.textContent = `${point.date} · ${point.predicted ? "模型預測" : "歷史收盤"}`;
    const price = document.createElement("strong"); price.textContent = `${format(point.close)} ${analysis.currency || ""}`;
    tooltip.append(date, price);
    if (point.predicted) { const band = document.createElement("small"); band.textContent = `情境 ${format(point.lower)} – ${format(point.upper)}`; tooltip.append(band); }
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
    if (file.size > 2_000_000) { showError("CSV 檔案超過 2 MB，請縮小檔案後重試。"); return; }
    try {
      csvText = await file.text();
      if (!csvText.trim()) { csvText = null; showError("CSV 檔案沒有內容，請選擇包含歷史股價的檔案。"); return; }
      source.value = "csv";
      runAnalysis();
    } catch { showError("無法讀取 CSV 檔案，請重新選擇。"); }
  });
  $("export-button").addEventListener("click", () => {
    if (!analysis) return;
    const csvCell = (value) => {
      const cell = String(value);
      return /[",\r\n]/.test(cell) ? `"${cell.replace(/"/g, '""')}"` : cell;
    };
    const rows = ["Date,ForecastClose,LowerScenario,UpperScenario,Source,Symbol,SourceLabel", ...analysis.forecast.map((p) => [p.date, p.close, p.lower, p.upper, analysis.source, analysis.symbol, analysis.source_label].map(csvCell).join(","))];
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
  updateSourceUi();
  runAnalysis();
})();
