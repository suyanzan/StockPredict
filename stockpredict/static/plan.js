"use strict";

// Private 0050 plan. Amounts and holdings stay in this browser (localStorage);
// the server only returns 0050 history statistics as percentages.
(() => {
  const $ = (id) => document.getElementById(id);
  const STORE = "stockpredict.plan.v1";
  const BUY_FEE = 0.001425;
  const DEFAULTS = {
    total: 2000000, keep: 20, sat: 10, rate: 0, start: "2027-01", months: 12,
    held: 3000, heldCost: 0, buys: [],
  };
  let data = null;
  let paper = null;
  let state = load();

  function load() {
    try {
      return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(STORE) || "{}") };
    } catch {
      return { ...DEFAULTS };
    }
  }
  function save() {
    try { localStorage.setItem(STORE, JSON.stringify(state)); } catch { /* storage unavailable */ }
  }
  const money = (v) => Math.round(v).toLocaleString("zh-TW") + " 元";
  const num = (v, d = 2) => Number(v).toLocaleString("zh-TW", { maximumFractionDigits: d, minimumFractionDigits: d });
  const pct = (v) => (v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${num(v, 1)}%`);

  function show(message, error = false) {
    const el = $("plan-message");
    el.textContent = message;
    el.hidden = !message;
    el.classList.toggle("notice-error", error);
  }
  function row(body, cells, cls) {
    const tr = document.createElement("tr");
    if (cls) tr.className = cls;
    cells.forEach((cell) => {
      const td = document.createElement("td");
      if (cell && typeof cell === "object") {
        td.textContent = cell.text;
        if (cell.cls) td.className = cell.cls;
      } else {
        td.textContent = cell;
      }
      tr.append(td);
    });
    body.append(tr);
  }
  const signed = (v) => ({ text: pct(v), cls: v < 0 ? "plan-neg" : "plan-pos" });

  async function fetchPlan() {
    const params = new URLSearchParams({
      months: String(state.months),
      horizon_months: $("sim-horizon").value,
      up_pct: $("sim-up").value,
      down_pct: $("sim-down").value,
      sell_fraction_pct: $("sim-fraction").value,
    });
    show("正在讀取 0050 歷史價格並回測…");
    const response = await fetch(`/api/plan/0050?${params}`, { credentials: "same-origin" });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const code = body?.detail?.code;
      if (code === "unauthorized") {
        signedOut("登入已過期，請重新輸入管理金鑰。");
        throw new Error("登入已過期，請重新輸入管理金鑰。");
      }
      if (code === "admin_not_configured") throw new Error("管理功能尚未設定，請先在 Render 設定管理金鑰。");
      const message = body?.detail?.message || "回測暫時無法使用，請稍後再試。";
      const source = body?.detail?.source_code;
      throw new Error(typeof source === "string" ? `${message}（來源代碼：${source}）` : message);
    }
    data = body;
    show("");
  }

  async function fetchPaper() {
    const paperParams = new URLSearchParams({
      months: String(state.months),
      satellite_pct: String(Math.min(50, Math.max(0, state.sat))),
      up_pct: $("sim-up").value,
      down_pct: $("sim-down").value,
      sell_fraction_pct: $("sim-fraction").value,
    });
    try {
      const paperResponse = await fetch(`/api/plan/paper?${paperParams}`, { credentials: "same-origin" });
      paper = paperResponse.ok ? await paperResponse.json() : null;
    } catch {
      paper = null;
    }
  }

  const latestQuote = () => data?.latest || (paper?.status === "running" ? paper.latest : null);

  function renderAllocation() {
    const body = $("alloc-body");
    body.replaceChildren();
    const keep = state.total * state.keep / 100;
    const invest = state.total - keep;
    const sat = invest * state.sat / 100;
    const core = invest - sat;
    const dd = data ? data.max_drawdown.pct / 100 : null;
    row(body, ["保留定存／現金", money(keep)]);
    row(body, ["0050 核心（分批、長期持有）", money(core)]);
    row(body, ["0050 衛星（套利規則）", money(sat)]);
    if (state.rate > 0) row(body, ["定存一年利息（估）", money(keep * state.rate / 100)]);
    if (dd !== null) {
      row(body, ["若遇到歷史最大跌幅，股票部分最多帳面虧損", { text: money(invest * dd), cls: "plan-neg" }], "plan-strong");
      row(body, ["屆時總資產約剩", money(state.total + invest * dd)], "plan-strong");
      const m = data.max_drawdown;
      const recovery = m.recovery_date
        ? `直到 ${m.recovery_date} 才回到前高（約 ${m.recovery_trading_days} 個交易日）`
        : "至今尚未回到前高";
      $("alloc-note").textContent = `0050 在資料期間（${data.history.start} 起）的最大跌幅是 ${pct(m.pct)}：從 ${m.peak_date} 高點跌到 ${m.trough_date}，${recovery}。保留的定存在這段期間不受影響。`;
    }
  }

  function renderSchedule() {
    const body = $("schedule-body");
    body.replaceChildren();
    const invest = state.total * (1 - state.keep / 100);
    const monthly = invest * (1 - state.sat / 100) / state.months;
    const [year, month] = (state.start || "2027-01").split("-").map(Number);
    const price = latestQuote()?.close ?? null;
    for (let k = 0; k < state.months; k += 1) {
      const d = new Date(year, month - 1 + k, 1);
      const label = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
      row(body, [label, money(monthly), price ? `${Math.floor(monthly / (price * (1 + BUY_FEE))).toLocaleString("zh-TW")} 股` : "—"]);
    }
  }

  const SELL_COST = 0.001425 + 0.001;
  const TYPE_LABEL = { buy: "買入", sell: "賣出", dividend: "配息" };

  // Average-cost ledger: existing holding first, then records in date order.
  function ledger(records) {
    let shares = Number(state.held) || 0;
    let cost = shares * (Number(state.heldCost) || 0);
    let invested = cost;
    let realized = 0;
    let dividends = 0;
    for (const r of records) {
      const type = r.type || "buy";
      if (type === "buy") {
        shares += r.shares;
        cost += r.shares * r.price * (1 + BUY_FEE);
        invested += r.shares * r.price * (1 + BUY_FEE);
      } else if (type === "sell") {
        if (r.shares > shares) return { error: `${r.date} 賣出 ${r.shares} 股超過當時持有的 ${shares} 股。` };
        const basis = shares ? cost / shares * r.shares : 0;
        realized += r.shares * r.price * (1 - SELL_COST) - basis;
        cost -= basis;
        shares -= r.shares;
      } else {
        dividends += r.shares * r.price;
      }
    }
    return { shares, cost, invested, realized, dividends };
  }

  function renderHoldings() {
    const body = $("holding-body");
    body.replaceChildren();
    const result = ledger(state.buys);
    if (result.error) {
      row(body, ["紀錄有誤", { text: result.error, cls: "plan-neg" }]);
      return;
    }
    const { shares, cost, invested, realized, dividends } = result;
    const avg = shares ? cost / shares : 0;
    row(body, ["持有股數", `${shares.toLocaleString("zh-TW")} 股（${num(shares / 1000, 3)} 張）`]);
    row(body, ["平均成本（含手續費）", avg ? `${num(avg)} 元` : "—"]);
    row(body, ["持股成本", money(cost)]);
    row(body, ["累計投入", money(invested)]);
    row(body, ["已實現損益（賣出）", { text: money(realized), cls: realized < 0 ? "plan-neg" : "plan-pos" }]);
    row(body, ["累計配息", money(dividends)]);
    const quote = latestQuote();
    if (quote) {
      const price = quote.close;
      const unrealized = shares * price * (1 - SELL_COST) - cost;
      const total = unrealized + realized + dividends;
      row(body, [`市值（${quote.date} 收盤 ${num(price)}）`, money(shares * price)]);
      row(body, ["未實現損益（扣賣出成本）", { text: money(unrealized), cls: unrealized < 0 ? "plan-neg" : "plan-pos" }]);
      row(body, ["總損益（含已實現與配息）", { text: money(total), cls: total < 0 ? "plan-neg" : "plan-pos" }], "plan-strong");
      row(body, ["總報酬率（÷ 累計投入）", signed(invested ? total / invested * 100 : 0)], "plan-strong");
      if (avg) row(body, ["持股回本價（扣賣出成本）", `${num(avg / (1 - SELL_COST))} 元`]);
    }
    const list = $("buy-list");
    list.replaceChildren();
    state.buys.forEach((b, index) => {
      const li = document.createElement("li");
      const text = document.createElement("span");
      const type = b.type || "buy";
      text.textContent = type === "dividend"
        ? `${b.date}　配息 ${b.shares.toLocaleString("zh-TW")} 股 × ${num(b.price, 4)} = ${money(b.shares * b.price)}`
        : `${b.date}　${TYPE_LABEL[type]} ${b.shares.toLocaleString("zh-TW")} 股 @ ${num(b.price)}`;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "刪除";
      remove.addEventListener("click", () => {
        state.buys.splice(index, 1);
        save();
        renderHoldings();
      });
      li.append(text, remove);
      list.append(li);
    });
  }

  const ACCOUNT_LABEL = { plan: "分批＋衛星", baseline: "純分批（對照）" };
  const REASON_LABEL = { monthly: "每月分批", satellite_start: "衛星建倉", take_profit: "衛星獲利了結", buy_back: "衛星買回" };

  function renderPaper() {
    const status = $("paper-status");
    const body = $("paper-body");
    const tradesBody = $("paper-trades");
    const chart = $("paper-chart");
    body.replaceChildren();
    tradesBody.replaceChildren();
    chart.replaceChildren();
    if (!paper) {
      status.textContent = "模擬交易資料暫時無法讀取。";
      return;
    }
    if (paper.status === "waiting") {
      status.textContent = `模擬將從 ${paper.start} 起的第一個收盤價開始（台股收盤資料約下午 3 點後可取得）。`;
      return;
    }
    status.textContent = `首個交易日 ${paper.first_trading_day}，最新 ${paper.latest.date} 收盤 ${num(paper.latest.close)}。`;
    for (const [name, a] of Object.entries(paper.accounts)) {
      row(body, [ACCOUNT_LABEL[name], money(a.value), signed(a.return_pct), money(a.cash), a.shares.toLocaleString("zh-TW"), `${a.installments_done}/${a.installments_total}`]);
    }
    drawChart(chart, paper.series);
    [...paper.trades].reverse().forEach((t) => {
      row(tradesBody, [t.date, ACCOUNT_LABEL[t.account], REASON_LABEL[t.reason] || t.side, t.shares.toLocaleString("zh-TW"), num(t.price), money(t.amount)]);
    });
  }

  function drawChart(svg, series) {
    if (series.length < 2) return;
    const ns = "http://www.w3.org/2000/svg";
    const values = series.flatMap((p) => [p.plan, p.baseline]);
    const lo = Math.min(...values);
    const hi = Math.max(...values);
    const span = hi - lo || 1;
    const x = (i) => 10 + (i / (series.length - 1)) * 580;
    const y = (v) => 165 - ((v - lo) / span) * 145;
    [["plan", "#138b7d"], ["baseline", "#8a96a3"]].forEach(([key, color]) => {
      const line = document.createElementNS(ns, "polyline");
      line.setAttribute("points", series.map((p, i) => `${x(i).toFixed(1)},${y(p[key]).toFixed(1)}`).join(" "));
      line.setAttribute("fill", "none");
      line.setAttribute("stroke", color);
      line.setAttribute("stroke-width", "2");
      svg.append(line);
    });
    [["分批＋衛星", "#138b7d", 10], ["純分批", "#8a96a3", 110]].forEach(([label, color, left]) => {
      const text = document.createElementNS(ns, "text");
      text.setAttribute("x", String(left));
      text.setAttribute("y", "14");
      text.setAttribute("fill", color);
      text.setAttribute("class", "plan-legend");
      text.textContent = `— ${label}`;
      svg.append(text);
    });
  }

  function renderSimulation() {
    if (!data) return;
    const s = data.simulation;
    $("sim-meta").textContent = `資料 ${data.history.start} 至 ${data.history.end}，每 5 個交易日取一個起點，共 ${s.samples} 個起點；分批 = ${state.months} 個月平均買入。`;
    const lump = $("lump-body");
    lump.replaceChildren();
    [["一次投入", s.lump_sum], [`分 ${state.months} 個月買入`, s.monthly]].forEach(([name, r]) => {
      row(lump, [name, signed(r.median), signed(r.p5), signed(r.worst), signed(r.best), `${num(r.loss_rate, 1)}%`]);
    });
    $("lump-note").textContent = `歷史上分批買入在 ${num(s.monthly_beats_lump_pct, 1)}% 的起點勝過一次投入。一次投入在觀察期內最糟的帳面跌幅曾達 ${pct(s.lump_sum.worst_paper_loss)}。`;
    const sat = $("sat-body");
    sat.replaceChildren();
    s.satellite.forEach((r) => {
      row(sat, [`${r.share_pct}%`, signed(r.median), signed(r.p5), signed(r.worst), String(r.median_trades), r.beats_monthly_pct === null ? "基準" : `${num(r.beats_monthly_pct, 1)}%`],
        r.share_pct === state.sat ? "plan-strong" : "");
    });
  }

  function renderAll() {
    renderAllocation();
    renderSchedule();
    renderHoldings();
    renderSimulation();
    renderPaper();
  }

  function bind(id, key, parse = Number) {
    const el = $(id);
    el.value = state[key];
    el.addEventListener("change", async () => {
      state[key] = parse(el.value);
      save();
      if (key === "months" || key === "sat") {
        const [plan] = await Promise.allSettled([fetchPlan(), fetchPaper()]);
        if (plan.status === "rejected") show(plan.reason.message, true);
      }
      renderAll();
    });
  }

  function signedOut(message) {
    data = null;
    $("plan-app").hidden = true;
    $("plan-auth").hidden = false;
    if (message) show(message, true);
  }

  function setExpiry(expiresAt) {
    const when = new Date(expiresAt);
    $("plan-expiry").textContent = Number.isNaN(when.getTime())
      ? ""
      : `已登入，這台裝置的登入會保留到 ${when.toLocaleString("zh-TW", { hour12: false })}。`;
  }

  async function openApp() {
    $("plan-auth").hidden = true;
    $("plan-app").hidden = false;
    const [plan] = await Promise.allSettled([fetchPlan(), fetchPaper()]);
    renderAll();
    if (plan.status === "rejected") show(plan.reason.message, true);
  }

  $("plan-login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const key = $("plan-key").value.trim();
    try {
      const response = await fetch("/api/plan/session", {
        method: "POST",
        credentials: "same-origin",
        headers: { Authorization: `Bearer ${key}` },
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        const code = body?.detail?.code;
        if (code === "admin_not_configured") throw new Error("管理功能尚未設定，請先在 Render 設定管理金鑰。");
        throw new Error("管理金鑰無效，請重新輸入。");
      }
      $("plan-key").value = "";
      setExpiry(body.expires_at);
      await openApp();
    } catch (error) {
      show(error.message, true);
    }
  });
  $("sim-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const [plan] = await Promise.allSettled([fetchPlan(), fetchPaper()]);
    renderAll();
    if (plan.status === "rejected") show(plan.reason.message, true);
  });
  $("buy-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const shares = Math.round(Number($("buy-shares").value));
    const price = Number($("buy-price").value);
    const type = $("buy-type").value;
    if (!(shares > 0 && price > 0) || !$("buy-date").value) return;
    const records = [...state.buys, { type, date: $("buy-date").value, shares, price }]
      .sort((a, b) => a.date.localeCompare(b.date));
    const check = ledger(records);
    if (check.error) {
      show(check.error, true);
      return;
    }
    show("");
    state.buys = records;
    save();
    event.target.reset();
    updateFormLabels();
    renderHoldings();
  });
  function updateFormLabels() {
    const dividend = $("buy-type").value === "dividend";
    $("buy-shares-label").firstChild.textContent = dividend ? "參與配息股數" : "股數";
    $("buy-price-label").firstChild.textContent = dividend ? "每股配息（元）" : "成交價";
  }
  $("buy-type").addEventListener("change", updateFormLabels);

  $("plan-logout").addEventListener("click", async () => {
    await fetch("/api/plan/session", { method: "DELETE", credentials: "same-origin" }).catch(() => {});
    signedOut("");
    show("已登出這台裝置。");
  });

  bind("in-total", "total");
  bind("in-keep", "keep");
  bind("in-sat", "sat");
  bind("in-rate", "rate");
  bind("in-start", "start", String);
  bind("in-months", "months", (v) => Math.min(24, Math.max(1, Math.round(Number(v) || 1))));
  bind("in-held", "held");
  bind("in-held-cost", "heldCost");

  // Resume a remembered session without asking for the key again.
  (async () => {
    try {
      const response = await fetch("/api/plan/session", { credentials: "same-origin" });
      if (!response.ok) {
        $("plan-auth").hidden = false;
        return;
      }
      setExpiry((await response.json()).expires_at);
      await openApp();
    } catch (error) {
      if ($("plan-app").hidden) $("plan-auth").hidden = false;
      show(error.message, true);
    }
  })();
})();
