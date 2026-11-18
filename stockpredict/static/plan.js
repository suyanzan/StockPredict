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
  let token = "";
  let data = null;
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
    const response = await fetch(`/api/plan/0050?${params}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const code = body?.detail?.code;
      if (code === "unauthorized") throw new Error("管理金鑰無效，請重新輸入。");
      if (code === "admin_not_configured") throw new Error("管理功能尚未設定，請先在 Render 設定管理金鑰。");
      throw new Error(body?.detail?.message || "回測暫時無法使用，請稍後再試。");
    }
    data = body;
    show("");
  }

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
    const price = data ? data.latest.close : null;
    for (let k = 0; k < state.months; k += 1) {
      const d = new Date(year, month - 1 + k, 1);
      const label = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
      row(body, [label, money(monthly), price ? `${Math.floor(monthly / (price * (1 + BUY_FEE))).toLocaleString("zh-TW")} 股` : "—"]);
    }
  }

  function renderHoldings() {
    const body = $("holding-body");
    body.replaceChildren();
    let shares = Number(state.held) || 0;
    let cost = shares * (Number(state.heldCost) || 0);
    state.buys.forEach((b) => {
      shares += b.shares;
      cost += b.shares * b.price * (1 + BUY_FEE);
    });
    const avg = shares ? cost / shares : 0;
    row(body, ["總股數", `${shares.toLocaleString("zh-TW")} 股（${num(shares / 1000, 3)} 張）`]);
    row(body, ["平均成本（含手續費）", avg ? `${num(avg)} 元` : "—"]);
    row(body, ["總投入成本", money(cost)]);
    if (data && shares) {
      const price = data.latest.close;
      const value = shares * price;
      const net = value * (1 - 0.001425 - 0.001);
      row(body, [`市值（${data.latest.date} 收盤 ${num(price)}）`, money(value)]);
      row(body, ["若現在全部賣出，扣費後損益", signed(cost ? (net / cost - 1) * 100 : 0)], "plan-strong");
      row(body, ["回本價（扣賣出成本）", avg ? `${num(avg / (1 - 0.001425 - 0.001))} 元` : "—"]);
    }
    const list = $("buy-list");
    list.replaceChildren();
    state.buys.forEach((b, index) => {
      const li = document.createElement("li");
      const text = document.createElement("span");
      text.textContent = `${b.date}　${b.shares.toLocaleString("zh-TW")} 股 @ ${num(b.price)}`;
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
  }

  function bind(id, key, parse = Number) {
    const el = $(id);
    el.value = state[key];
    el.addEventListener("change", async () => {
      state[key] = parse(el.value);
      save();
      if (key === "months" && token) {
        try { await fetchPlan(); } catch (error) { show(error.message, true); }
      }
      renderAll();
    });
  }

  $("plan-login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    token = $("plan-key").value.trim();
    try {
      await fetchPlan();
      $("plan-key").value = "";
      $("plan-auth").hidden = true;
      $("plan-app").hidden = false;
      renderAll();
    } catch (error) {
      token = "";
      show(error.message, true);
    }
  });
  $("sim-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await fetchPlan();
      renderAll();
    } catch (error) {
      show(error.message, true);
    }
  });
  $("buy-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const shares = Number($("buy-shares").value);
    const price = Number($("buy-price").value);
    if (!(shares > 0 && price > 0) || !$("buy-date").value) return;
    state.buys.push({ date: $("buy-date").value, shares, price });
    state.buys.sort((a, b) => a.date.localeCompare(b.date));
    save();
    event.target.reset();
    renderHoldings();
  });
  $("plan-logout").addEventListener("click", () => {
    token = "";
    data = null;
    $("plan-app").hidden = true;
    $("plan-auth").hidden = false;
  });

  bind("in-total", "total");
  bind("in-keep", "keep");
  bind("in-sat", "sat");
  bind("in-rate", "rate");
  bind("in-start", "start", String);
  bind("in-months", "months", (v) => Math.min(24, Math.max(1, Math.round(Number(v) || 1))));
  bind("in-held", "held");
  bind("in-held-cost", "heldCost");
})();
