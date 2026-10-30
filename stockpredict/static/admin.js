"use strict";

(() => {
  const I18n = window.StockPredictI18n;
  const $ = (id) => document.getElementById(id);
  I18n.register({
    "zh-TW": {
      "admin.title": "私人留言與建議", "admin.intro": "只有持有管理金鑰的站主可以查看；訪客留言不會公開。",
      "admin.back": "返回網站", "admin.language": "語言", "admin.key": "管理金鑰",
      "admin.keyNote": "輸入你在 Render 設定的管理金鑰。此頁不會保存金鑰；重新整理後需再次輸入。",
      "admin.login": "查看留言", "admin.filter": "狀態", "admin.new": "未處理", "admin.handled": "已處理",
      "admin.refresh": "重新讀取", "admin.logout": "登出", "admin.more": "載入更多", "admin.empty": "這個分類目前沒有留言。",
      "admin.loading": "正在讀取私人留言…", "admin.done": "留言已更新。", "admin.guest": "匿名訪客",
      "admin.mark": "標記已處理", "admin.delete": "刪除", "admin.confirmDelete": "確定永久刪除這筆留言？",
      "admin.suggestion": "功能建議", "admin.bug": "問題回報", "admin.other": "其他",
      "admin.error.unauthorized": "管理金鑰無效，請重新輸入。",
      "admin.error.admin_not_configured": "管理功能尚未設定。請先在 Render 設定管理金鑰。",
      "admin.error.not_configured": "留言儲存尚未設定。請先依部署說明設定資料庫連線。",
      "admin.error.community_unavailable": "留言服務暫時無法使用，請稍後重試。",
      "admin.error.forbidden_origin": "請從網站本身的管理頁操作。",
      "admin.error.not_found": "留言已不存在，請重新讀取。",
      "admin.error.validation_error": "請檢查管理金鑰與操作內容。"
    },
    en: {
      "admin.title": "Private feedback", "admin.intro": "Only the owner with the administration key can read these messages. Feedback is not public.",
      "admin.back": "Back to site", "admin.language": "Language", "admin.key": "Administration key",
      "admin.keyNote": "Enter the owner key configured in Render. This page does not save it; enter it again after a reload.",
      "admin.login": "View feedback", "admin.filter": "Status", "admin.new": "New", "admin.handled": "Handled",
      "admin.refresh": "Refresh", "admin.logout": "Sign out", "admin.more": "Load more", "admin.empty": "There is no feedback in this category.",
      "admin.loading": "Loading private feedback…", "admin.done": "Feedback updated.", "admin.guest": "Anonymous visitor",
      "admin.mark": "Mark as handled", "admin.delete": "Delete", "admin.confirmDelete": "Permanently delete this feedback?",
      "admin.suggestion": "Suggestion", "admin.bug": "Problem report", "admin.other": "Other",
      "admin.error.unauthorized": "The administration key is invalid. Please enter it again.",
      "admin.error.admin_not_configured": "Administration is not configured. Set the owner key in Render first.",
      "admin.error.not_configured": "Feedback storage is not configured. Follow the deployment guide to connect the database.",
      "admin.error.community_unavailable": "The feedback service is temporarily unavailable. Please try again later.",
      "admin.error.forbidden_origin": "Use the administration page on this website.",
      "admin.error.not_found": "This feedback no longer exists. Please refresh.",
      "admin.error.validation_error": "Check the administration key and request."
    }
  });
  const t = I18n.t;
  let token = "";
  let authenticated = false;
  let busy = false;
  let items = [];
  let cursor = null;
  let notice = null;
  let generation = 0;
  let activeController = null;
  const knownErrors = new Set(["unauthorized", "admin_not_configured", "not_configured", "community_unavailable", "forbidden_origin", "not_found", "validation_error"]);

  function render() {
    document.title = `${t("admin.title")} · StockPredict`;
    $("admin-auth").hidden = authenticated;
    $("admin-dashboard").hidden = !authenticated;
    $("admin-login").disabled = busy;
    $("admin-filter").disabled = busy;
    $("admin-refresh").disabled = busy;
    $("admin-more").hidden = !cursor;
    $("admin-more").disabled = busy;
    $("admin-message").hidden = !notice;
    $("admin-message").textContent = notice ? t(notice.key) : "";
    $("admin-message").classList.toggle("admin-error", Boolean(notice?.error));
    $("admin-empty").hidden = !authenticated || busy || items.length > 0;
    const list = $("admin-list");
    list.replaceChildren();
    if (!authenticated) return;
    for (const item of items) {
      const article = document.createElement("article");
      article.className = "panel admin-entry";
      article.dataset.commentId = item.id;
      const heading = document.createElement("div");
      heading.className = "admin-entry-heading";
      const name = document.createElement("strong");
      name.textContent = item.name || t("admin.guest");
      const category = document.createElement("span");
      category.textContent = t(`admin.${["suggestion", "bug", "other"].includes(item.category) ? item.category : "other"}`);
      const time = document.createElement("time");
      const date = new Date(item.created_at);
      time.textContent = Number.isFinite(date.valueOf()) ? new Intl.DateTimeFormat(I18n.getLanguage(), { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Taipei" }).format(date) : "—";
      heading.append(name, category, time);
      const body = document.createElement("p");
      body.className = "admin-entry-body";
      body.textContent = item.body;
      const actions = document.createElement("div");
      actions.className = "admin-actions";
      if (item.status === "pending") {
        const handled = document.createElement("button");
        handled.type = "button"; handled.className = "button button-secondary";
        handled.textContent = t("admin.mark"); handled.disabled = busy;
        handled.addEventListener("click", () => change(item.id, false));
        actions.append(handled);
      }
      const remove = document.createElement("button");
      remove.type = "button"; remove.className = "button button-secondary admin-delete";
      remove.textContent = t("admin.delete"); remove.disabled = busy;
      remove.addEventListener("click", () => change(item.id, true));
      actions.append(remove);
      article.append(heading, body, actions); list.append(article);
    }
  }

  function forget() {
    generation += 1;
    activeController?.abort(); activeController = null;
    busy = false;
    token = ""; authenticated = false; items = []; cursor = null;
    $("admin-key").value = "";
  }

  async function request(path, options = {}) {
    const controller = new AbortController();
    activeController = controller;
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(`/api/community/admin/comments${path}`, {
        ...options, cache: "no-store", signal: controller.signal,
        headers: { "Authorization": `Bearer ${token}`, ...(options.body ? { "Content-Type": "application/json" } : {}) }
      });
      let data = null;
      if (response.status !== 204) data = await response.json();
      if (!response.ok) {
        const code = data?.detail?.code || (response.status === 422 ? "validation_error" : "community_unavailable");
        throw new Error(knownErrors.has(code) ? code : "community_unavailable");
      }
      return data;
    } catch (error) {
      throw new Error(knownErrors.has(error.message) ? error.message : "community_unavailable");
    } finally {
      window.clearTimeout(timeout);
      if (activeController === controller) activeController = null;
    }
  }

  async function load(append = false) {
    if (busy || !token) return;
    const current = generation;
    busy = true; notice = { key: "admin.loading" }; render();
    try {
      const query = new URLSearchParams({ status: $("admin-filter").value, limit: "20" });
      if (append && cursor) query.set("before", cursor);
      const data = await request(`?${query}`);
      if (current !== generation) return;
      if (!Array.isArray(data?.items)) throw new Error("community_unavailable");
      const merged = new Map((append ? items : []).map((item) => [item.id, item]));
      for (const item of data.items) merged.set(item.id, item);
      items = [...merged.values()]; cursor = data.next_cursor;
      authenticated = true; $("admin-key").value = ""; notice = null;
    } catch (error) {
      if (current !== generation) return;
      if (!authenticated || error.message === "unauthorized") forget();
      notice = { key: `admin.error.${error.message}`, error: true };
      render();
    } finally { if (current === generation) { busy = false; render(); } }
  }

  async function change(id, remove) {
    if (busy || (remove && !window.confirm(t("admin.confirmDelete")))) return;
    const current = generation;
    busy = true; notice = { key: "admin.loading" }; render();
    try {
      await request(`/${id}`, remove ? { method: "DELETE" } : { method: "PATCH", body: JSON.stringify({ status: "hidden" }) });
      if (current !== generation) return;
      items = items.filter((item) => item.id !== id);
      notice = { key: "admin.done" };
    } catch (error) {
      if (current !== generation) return;
      if (error.message === "unauthorized") forget();
      notice = { key: `admin.error.${error.message}`, error: true }; render();
    }
    finally { if (current === generation) { busy = false; render(); } }
  }

  $("admin-login-form").addEventListener("submit", (event) => {
    event.preventDefault();
    token = $("admin-key").value.trim();
    if (token.length < 32) { notice = { key: "admin.error.validation_error", error: true }; render(); return; }
    load();
  });
  $("admin-filter").addEventListener("change", () => load());
  $("admin-refresh").addEventListener("click", () => load());
  $("admin-more").addEventListener("click", () => load(true));
  $("admin-logout").addEventListener("click", () => { forget(); notice = null; render(); });
  I18n.subscribe(render);
  render();
})();
