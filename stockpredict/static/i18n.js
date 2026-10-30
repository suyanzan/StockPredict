"use strict";

(() => {
  const messages = {
    "zh-TW": {
      "meta.title": "StockPredict · 股價分析與趨勢預測",
      "brand.home": "StockPredict 首頁",
      "nav.label": "主導覽",
      "nav.analysis": "分析工作台",
      "nav.method": "模型說明",
      "nav.feedback": "留言建議",
      "header.tag": "研究與學習工具",
      "language.label": "語言 / Language",
      "intro.eyebrow": "市場研究工作台",
      "intro.title": "從歷史數據，探索未來走勢",
      "intro.period": "。",
      "intro.copy": "股價圖表、趨勢估計與歷史回測，在同一個工作台。",
      "intro.note": "看見預測，也看見誤差",
      "intro.noteStrong": "每一次估計，都附上回測結果",
      "controls.label": "分析設定",
      "controls.symbol": "股票代碼",
      "controls.source": "資料來源",
      "controls.horizon": "預測期間",
      "controls.analyze": "開始分析",
      "controls.analyzing": "分析中…",
      "source.demo": "示範資料（合成）",
      "source.demoShort": "示範資料",
      "source.twse": "證交所（上市）",
      "source.twseShort": "證交所每日行情",
      "source.yahoo": "Yahoo 每日行情",
      "source.csv": "匯入 CSV",
      "horizon.5": "未來 5 個平日",
      "horizon.10": "未來 10 個平日",
      "horizon.20": "未來 20 個平日",
      "controls.quick": "快速選擇",
      "security.tsmc": "台積電",
      "security.umc": "聯電",
      "security.yuanta": "元大台灣 50",
      "controls.formatHelp": "台股格式：2330.TW · 美股格式：AAPL",
      "controls.twseHelp": "證交所提供數字代碼的台灣上市股票與 ETF 未還原權息收盤價，不含上櫃股票。可輸入 2303 或 2303.TW；首次取得資料可能需要 20–60 秒。",
      "csv.choose": "選擇歷史股價 CSV",
      "csv.requirements": "包含 Date、Close 欄位，至少 60 筆 · 最大 2 MB",
      "csv.formatHelp": "格式說明",
      "error.retryTwse": "改用證交所資料",
      "loading.analysis": "正在讀取資料並執行歷史回測…",
      "loading.twse": "正在取得證交所歷史資料並執行回測；首次讀取可能需要 20–60 秒，請稍候…",
      "empty.title": "準備好開始分析",
      "empty.copy": "選擇股票與資料來源，點擊「開始分析」。示範模式無需連網即可使用。",
      "metrics.label": "主要指標",
      "metrics.close": "最新收盤價",
      "metrics.forecast": "期末預估變動",
      "metrics.volatility": "年化歷史波動率",
      "metrics.volatilityNote": "依歷史每日報酬估算",
      "metrics.mae": "回測平均絕對誤差",
      "chart.title": "價格走勢與預測",
      "chart.copy": "以歷史收盤價為基礎的模型估計",
      "chart.rangeLabel": "圖表顯示期間",
      "chart.historical": "歷史收盤",
      "chart.forecast": "預測路徑",
      "chart.band": "波動情境區間",
      "chart.ariaInitial": "歷史股價與預測圖表；使用左右方向鍵查看各日期價格。",
      "chart.bandNote": "情境區間不代表已校準的信賴區間",
      "chart.boundary": "預測開始",
      "chart.pointCount": "顯示 {history} 筆歷史 · {forecast} 筆預測",
      "chart.aria": "{name}：{history} 筆歷史收盤與 {forecast} 個平日預測。最新收盤 {close}，期末預估 {forecastClose}。使用左右方向鍵查看各日期價格。",
      "chart.predictedPoint": "模型預測",
      "chart.scenario": "情境 {lower} – {upper}",
      "backtest.kicker": "模型表現檢查",
      "backtest.title": "用回測檢視模型",
      "backtest.modelMae": "模型 MAE",
      "backtest.baselineMae": "前日收盤基準 MAE",
      "backtest.direction": "模型方向準確率",
      "backtest.rmse": "均方根誤差 RMSE",
      "backtest.mape": "平均絕對百分比誤差",
      "backtest.sample": "回測樣本數",
      "backtest.note": "回測每次僅使用當時可取得的歷史資料。基準模型以最新收盤價預估下一日；回測表現不保證未來結果。",
      "backtest.description": "保留最後 {count} 筆，逐日向前驗證",
      "backtest.better": "此次回測：模型誤差低於前日收盤基準。",
      "backtest.worse": "此次回測：模型未優於前日收盤基準。解讀預測時請留意。",
      "backtest.count": "{count} 筆",
      "forecast.title": "未來價格估計",
      "forecast.copy": "按平日排列；未排除市場休市日",
      "forecast.export": "匯出 CSV",
      "forecast.date": "日期",
      "forecast.close": "預估收盤價",
      "forecast.relative": "相對最新收盤",
      "forecast.lower": "情境下緣",
      "forecast.upper": "情境上緣",
      "method.kicker": "理解模型",
      "method.title": "模型透明，判斷留給你。",
      "method.defaultDescription": "使用歷史每日報酬建立迴歸模型，估計接下來的價格路徑。先從示範資料開始，也能匯入自己的歷史收盤價。",
      "method.tagBacktest": "時間序列回測",
      "method.tagBaseline": "與簡單基準比較",
      "method.tagNoKey": "無需 API 金鑰",
      "method.sourceTitle": "先確認資料來源",
      "method.sourceCopy": "示範資料為合成序列。證交所提供數字代碼的上市台股收盤價；Yahoo 支援其他每日行情，可能延遲或暫時無法取得。",
      "method.bandTitle": "理解區間與限制",
      "method.defaultInterval": "依歷史波動估計情境上下緣，僅供探索。模型未考慮新聞、財報與市場事件。",
      "method.csvTitle": "帶入自己的資料",
      "method.csvCopy": "CSV 首列使用 Date,Close，例如 2026-01-05,105.5。日期採 YYYY-MM-DD，價格須為正數，至少 60 筆。",
      "footer.description": "開源股價研究工作台",
      "footer.note": "預測僅供研究與學習，不構成投資建議。",
      "result.date": "資料截至 {date} · {count} 筆歷史收盤",
      "result.price": "價格",
      "result.priceUnit": "價格單位",
      "result.dayChange": "{change} 較前一筆收盤",
      "result.forecastCaption": "{count} 個平日後 · 預估 {price}",
      "result.maeCaption": "模型一天預測 · {currency}",
      "result.limitations": "資料與模型限制（{count} 項）",
      "error.preserved": "畫面保留上次成功的 {symbol}（{source}）分析結果。",
      "error.symbol": "請輸入股票代碼，例如 2330.TW 或 AAPL。",
      "error.csvRequired": "請先選擇包含 Date、Close 欄位的 CSV 檔案。",
      "error.csvTooLarge": "CSV 檔案超過 2 MB，請縮小檔案後重試。",
      "error.csvEmpty": "CSV 檔案沒有內容，請選擇包含歷史股價的檔案。",
      "error.csvRead": "無法讀取 CSV 檔案，請重新選擇。",
      "error.response": "伺服器未回傳有效資料，請稍後重試。",
      "error.generic": "分析未成功，請檢查資料與設定後重試。",
      "error.timeout": "資料讀取逾時，請重試或使用示範資料與 CSV 匯入。",
      "error.connection": "無法連線至服務，請稍後重試。",
      "error.validation": "請檢查股票代碼、資料來源與預測期間。"
    },
    en: {
      "meta.title": "StockPredict · Stock Analysis & Forecasts",
      "brand.home": "StockPredict home",
      "nav.label": "Main navigation",
      "nav.analysis": "Analysis",
      "nav.method": "The model",
      "nav.feedback": "Feedback",
      "header.tag": "Research & learning",
      "language.label": "語言 / Language",
      "intro.eyebrow": "MARKET RESEARCH WORKSPACE",
      "intro.title": "Explore what follows the historical data",
      "intro.period": ".",
      "intro.copy": "Price charts, forecasts, and historical backtests in one workspace.",
      "intro.note": "See the forecast. See the error.",
      "intro.noteStrong": "Every estimate comes with a backtest",
      "controls.label": "Analysis settings",
      "controls.symbol": "Stock symbol",
      "controls.source": "Data source",
      "controls.horizon": "Forecast horizon",
      "controls.analyze": "Run analysis",
      "controls.analyzing": "Analyzing…",
      "source.demo": "Synthetic demo data",
      "source.demoShort": "Demo data",
      "source.twse": "TWSE (listed)",
      "source.twseShort": "TWSE daily prices",
      "source.yahoo": "Yahoo daily prices",
      "source.csv": "Import CSV",
      "horizon.5": "Next 5 weekdays",
      "horizon.10": "Next 10 weekdays",
      "horizon.20": "Next 20 weekdays",
      "controls.quick": "Quick picks",
      "security.tsmc": "TSMC",
      "security.umc": "UMC",
      "security.yuanta": "Yuanta Taiwan 50",
      "controls.formatHelp": "Taiwan: 2330.TW · US: AAPL",
      "controls.twseHelp": "TWSE provides unadjusted closes for Taiwan-listed stocks and ETFs with numeric symbols, excluding OTC stocks. Enter 2303 or 2303.TW. The first download may take 20–60 seconds.",
      "csv.choose": "Choose a historical-price CSV",
      "csv.requirements": "Date and Close columns · At least 60 rows · Up to 2 MB",
      "csv.formatHelp": "CSV format",
      "error.retryTwse": "Try TWSE data",
      "loading.analysis": "Loading prices and running the historical backtest…",
      "loading.twse": "Loading TWSE history and running the backtest. The first download may take 20–60 seconds…",
      "empty.title": "Ready to explore",
      "empty.copy": "Choose a stock and data source, then run analysis. Demo data works without an external connection.",
      "metrics.label": "Key metrics",
      "metrics.close": "Latest close",
      "metrics.forecast": "Estimated final change",
      "metrics.volatility": "Annualized volatility",
      "metrics.volatilityNote": "Based on historical daily returns",
      "metrics.mae": "Backtest mean absolute error",
      "chart.title": "Price history & forecast",
      "chart.copy": "Model estimates based on historical closes",
      "chart.rangeLabel": "Chart history range",
      "chart.historical": "Historical close",
      "chart.forecast": "Forecast path",
      "chart.band": "Volatility scenario band",
      "chart.ariaInitial": "Historical prices and forecasts. Use the left and right arrow keys to inspect prices by date.",
      "chart.bandNote": "Scenario bands are not calibrated confidence intervals",
      "chart.boundary": "Forecast starts",
      "chart.pointCount": "Showing {history} historical · {forecast} forecast points",
      "chart.aria": "{name}: {history} historical closes and a {forecast}-weekday forecast. Latest close {close}; final estimate {forecastClose}. Use left and right arrow keys to inspect prices by date.",
      "chart.predictedPoint": "Model forecast",
      "chart.scenario": "Scenario {lower} – {upper}",
      "backtest.kicker": "PERFORMANCE CHECK",
      "backtest.title": "Check the model against history",
      "backtest.modelMae": "Model MAE",
      "backtest.baselineMae": "Previous-close baseline MAE",
      "backtest.direction": "Direction accuracy",
      "backtest.rmse": "Root mean squared error",
      "backtest.mape": "Mean absolute percentage error",
      "backtest.sample": "Backtest observations",
      "backtest.note": "Each backtest fit uses only the history available before its target date. The baseline predicts the previous close. Historical results do not guarantee future performance.",
      "backtest.description": "Walk-forward validation on the final {count} observations",
      "backtest.better": "This backtest: the model's error was lower than the previous-close baseline.",
      "backtest.worse": "This backtest: the model did not beat the previous-close baseline. Interpret its forecasts with care.",
      "backtest.count": "{count}",
      "forecast.title": "Future price estimates",
      "forecast.copy": "Weekdays only; market holidays are not excluded",
      "forecast.export": "Export CSV",
      "forecast.date": "Date",
      "forecast.close": "Estimated close",
      "forecast.relative": "Vs. latest close",
      "forecast.lower": "Lower scenario",
      "forecast.upper": "Upper scenario",
      "method.kicker": "UNDER THE MODEL",
      "method.title": "A transparent model. Your judgment.",
      "method.defaultDescription": "A regression model uses historical daily returns to estimate the next price path. Start with synthetic demo data or import your own historical closes.",
      "method.tagBacktest": "Time-series backtest",
      "method.tagBaseline": "Simple baseline comparison",
      "method.tagNoKey": "No API key required",
      "method.sourceTitle": "Know your data source",
      "method.sourceCopy": "Demo data is synthetic. TWSE provides closes for Taiwan-listed securities with numeric symbols. Yahoo supports other daily prices, which may be delayed or temporarily unavailable.",
      "method.bandTitle": "Understand the limits",
      "method.defaultInterval": "Historical volatility provides exploratory upper and lower scenarios. The model does not account for news, financial reports, or market events.",
      "method.csvTitle": "Bring your own history",
      "method.csvCopy": "Use Date,Close as CSV headers, for example 2026-01-05,105.5. Dates must be YYYY-MM-DD and prices must be positive. At least 60 observations are required.",
      "footer.description": "Open-source stock research workspace",
      "footer.note": "Forecasts are for research and learning, not investment advice.",
      "result.date": "As of {date} · {count} historical closes",
      "result.price": "Price",
      "result.priceUnit": "price units",
      "result.dayChange": "{change} vs. previous close",
      "result.forecastCaption": "In {count} weekdays · Estimate {price}",
      "result.maeCaption": "One-step model forecast · {currency}",
      "result.limitations": "Data and model limitations ({count})",
      "error.preserved": "The previous successful analysis for {symbol} ({source}) remains displayed.",
      "error.symbol": "Enter a stock symbol, such as 2330.TW or AAPL.",
      "error.csvRequired": "Choose a CSV with Date and Close columns first.",
      "error.csvTooLarge": "The CSV exceeds 2 MB. Choose a smaller file.",
      "error.csvEmpty": "The CSV is empty. Choose a file with historical prices.",
      "error.csvRead": "The CSV could not be read. Choose the file again.",
      "error.response": "The server returned invalid data. Please try again later.",
      "error.generic": "Analysis failed. Check the data and settings, then try again.",
      "error.timeout": "The request timed out. Try again, use demo data, or import a CSV.",
      "error.connection": "The service could not be reached. Please try again later.",
      "error.validation": "Check the symbol, data source, and forecast horizon."
    }
  };
  const supported = ["zh-TW", "en"];
  const subscribers = new Set();
  const storageKey = "stockpredict.language";
  let language = "zh-TW";
  try {
    const stored = window.localStorage.getItem(storageKey);
    if (supported.includes(stored)) language = stored;
  } catch { /* A privacy setting may disable local storage. */ }
  const queryLanguage = new URLSearchParams(window.location.search).get("lang");
  if (supported.includes(queryLanguage)) language = queryLanguage;

  function t(key, variables = {}) {
    const template = messages[language][key] ?? messages["zh-TW"][key] ?? key;
    return template.replace(/\{(\w+)\}/g, (match, name) => Object.hasOwn(variables, name) ? String(variables[name]) : match);
  }

  function apply() {
    document.documentElement.lang = language === "en" ? "en" : "zh-Hant";
    document.title = t("meta.title");
    document.querySelectorAll("[data-i18n]").forEach((element) => {
      element.textContent = t(element.dataset.i18n);
    });
    for (const attribute of ["aria-label", "placeholder", "title"]) {
      document.querySelectorAll(`[data-i18n-${attribute}]`).forEach((element) => {
        element.setAttribute(attribute, t(element.getAttribute(`data-i18n-${attribute}`)));
      });
    }
    const select = document.getElementById("language-select");
    if (select) select.value = language;
  }

  function setLanguage(value) {
    if (!supported.includes(value) || value === language) return;
    language = value;
    try { window.localStorage.setItem(storageKey, language); } catch { /* Preference is optional. */ }
    apply();
    subscribers.forEach((callback) => callback(language));
  }

  function register(translations) {
    for (const key of supported) Object.assign(messages[key], translations[key] || {});
    apply();
  }

  window.StockPredictI18n = {
    t,
    getLanguage: () => language,
    setLanguage,
    subscribe: (callback) => {
      subscribers.add(callback);
      return () => subscribers.delete(callback);
    },
    register
  };
  apply();
  document.getElementById("language-select")?.addEventListener("change", (event) => setLanguage(event.target.value));
})();
