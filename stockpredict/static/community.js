"use strict";

(() => {
  const i18n = window.StockPredictI18n;
  const $ = (id) => document.getElementById(id);
  if (!i18n || !$("community-section") || !$("community-form")) return;

  i18n.register({
    "zh-TW": {
      "community.kicker": "COMMUNITY & FEEDBACK",
      "community.title": "一起讓 StockPredict 更好用",
      "community.intro": "留下使用建議、功能想法，或告訴我遇到的問題。",
      "community.pageViews": "瀏覽次數",
      "community.uniqueBrowsers": "不重複瀏覽器",
      "community.privacy": "以匿名瀏覽器 Cookie 估算，不等同實際人數；切換語言或執行分析不會增加瀏覽次數。",
      "community.name": "稱呼（選填）",
      "community.namePlaceholder": "希望如何稱呼你？",
      "community.category": "建議類型",
      "community.suggestion": "功能與使用建議",
      "community.bug": "回報問題",
      "community.other": "其他",
      "community.body": "留言內容",
      "community.bodyPlaceholder": "例如：希望增加的功能，或遇到問題時的操作步驟。",
      "community.submit": "送出建議",
      "community.submitting": "正在送出…",
      "community.recent": "近期公開留言",
      "community.loadMore": "載入更多",
      "community.loadingMore": "正在載入…",
      "community.loading": "正在讀取瀏覽統計與留言功能…",
      "community.ready": "歡迎提出建議，協助改善這個 Side Project。",
      "community.notConfigured": "瀏覽統計與留言功能尚未啟用。",
      "community.unavailable": "瀏覽統計與留言功能暫時無法使用，請稍後重試。",
      "community.visitUnavailable": "這次瀏覽未能確認計入；目前顯示最近取得的統計，仍可留下建議。",
      "community.cookieUnavailable": "目前無法建立匿名瀏覽識別碼；顯示最近取得的統計。",
      "community.retry": "重新讀取",
      "community.privateNote": "留言只會提供給網站擁有者查看，不會公開顯示。",
      "community.reviewNote": "留言會先由網站擁有者審核，通過後才公開顯示。",
      "community.publicNote": "送出後會公開顯示你的稱呼與留言內容。",
      "community.sentPrivate": "建議已送出，只有網站擁有者能查看。謝謝你的回饋！",
      "community.sentReview": "留言已送出，審核通過後會公開顯示。謝謝你的回饋！",
      "community.sentPublic": "留言已公開送出。謝謝你的回饋！",
      "community.commentsLoading": "正在讀取留言…",
      "community.commentsEmpty": "目前還沒有公開留言。",
      "community.commentsUnavailable": "暫時無法讀取公開留言，請稍後重試。",
      "community.guest": "訪客",
      "community.characterCount": "{count} / 2,000",
      "community.invalidBody": "請填寫 1–2,000 字的留言內容。",
      "community.invalidName": "稱呼不可超過 80 字。",
      "community.error.not_configured": "留言功能尚未啟用，請稍後再試。",
      "community.error.community_unavailable": "留言服務暫時無法使用，請稍後重試。",
      "community.error.rate_limited": "留言過於頻繁，請稍候再送出。",
      "community.error.forbidden_origin": "無法送出這個請求，請從網站本身開啟後再試。",
      "community.error.unauthorized": "這個操作需要授權。",
      "community.error.not_found": "找不到這筆留言，請重新讀取。",
      "community.error.validation_error": "請確認留言欄位、內容長度與建議類型。",
      "community.error.network_error": "無法連線至留言服務，請檢查網路後重試。",
      "community.error.timeout": "留言服務回應逾時，請稍候再試。",
      "community.error.bad_response": "留言服務回傳資料不完整，請稍後重試。"
    },
    en: {
      "community.kicker": "COMMUNITY & FEEDBACK",
      "community.title": "Help make StockPredict better",
      "community.intro": "Share a suggestion, a feature idea, or a problem you encountered.",
      "community.pageViews": "Page views",
      "community.uniqueBrowsers": "Unique browsers",
      "community.privacy": "Estimated using an anonymous browser cookie, not a count of actual people. Language changes and analyses do not add page views.",
      "community.name": "Name (optional)",
      "community.namePlaceholder": "What would you like to be called?",
      "community.category": "Feedback type",
      "community.suggestion": "Feature or usability suggestion",
      "community.bug": "Report a problem",
      "community.other": "Other",
      "community.body": "Your feedback",
      "community.bodyPlaceholder": "For example, a feature you would like or the steps that led to a problem.",
      "community.submit": "Send feedback",
      "community.submitting": "Sending…",
      "community.recent": "Recent public comments",
      "community.loadMore": "Load more",
      "community.loadingMore": "Loading…",
      "community.loading": "Loading visitor statistics and feedback…",
      "community.ready": "Your suggestions help improve this side project.",
      "community.notConfigured": "Visitor statistics and feedback are not enabled yet.",
      "community.unavailable": "Visitor statistics and feedback are temporarily unavailable. Please try again later.",
      "community.visitUnavailable": "This visit could not be confirmed. The latest retrieved counts are shown; you can still send feedback.",
      "community.cookieUnavailable": "An anonymous browser identifier could not be created. The latest retrieved counts are shown.",
      "community.retry": "Try loading again",
      "community.privateNote": "Only the website owner can read your feedback. It will not be displayed publicly.",
      "community.reviewNote": "The website owner reviews comments before they appear publicly.",
      "community.publicNote": "Your name and message will be displayed publicly after submission.",
      "community.sentPrivate": "Your feedback was sent to the website owner and is not public. Thank you!",
      "community.sentReview": "Your comment was sent and will appear after approval. Thank you!",
      "community.sentPublic": "Your comment has been published. Thank you!",
      "community.commentsLoading": "Loading comments…",
      "community.commentsEmpty": "There are no public comments yet.",
      "community.commentsUnavailable": "Public comments could not be loaded. Please try again later.",
      "community.guest": "Guest",
      "community.characterCount": "{count} / 2,000",
      "community.invalidBody": "Enter a message of 1–2,000 characters.",
      "community.invalidName": "Your name must be 80 characters or fewer.",
      "community.error.not_configured": "Feedback is not enabled yet. Please try again later.",
      "community.error.community_unavailable": "Feedback is temporarily unavailable. Please try again later.",
      "community.error.rate_limited": "You are sending feedback too quickly. Please wait before trying again.",
      "community.error.forbidden_origin": "This request could not be sent. Open the website itself and try again.",
      "community.error.unauthorized": "This action requires authorization.",
      "community.error.not_found": "This comment could not be found. Try loading again.",
      "community.error.validation_error": "Check the feedback fields, message length, and feedback type.",
      "community.error.network_error": "Could not connect to the feedback service. Check your connection and try again.",
      "community.error.timeout": "The feedback service took too long to respond. Please try again later.",
      "community.error.bad_response": "The feedback service returned incomplete data. Please try again later."
    }
  });

  const t = (key, values) => i18n.t(key, values);
  const form = $("community-form");
  const fields = $("community-fields");
  const nameInput = $("feedback-name");
  const bodyInput = $("feedback-body");
  const categoryInput = $("feedback-category");
  const state = {
    phase: "loading",
    enabled: false,
    stats: null,
    moderation: "private",
    visitNotice: null,
    initializing: false,
    visitRecorded: false,
    submitting: false,
    message: null,
    comments: [],
    commentsState: "idle",
    nextCursor: null,
    loadingMore: false
  };
  const knownErrorCodes = new Set([
    "not_configured", "community_unavailable", "rate_limited", "forbidden_origin",
    "unauthorized", "not_found", "validation_error", "network_error", "timeout", "bad_response"
  ]);

  class CommunityError extends Error {
    constructor(code) {
      super(code);
      this.code = knownErrorCodes.has(code) ? code : "community_unavailable";
    }
  }

  function createPageId() {
    try {
      if (window.crypto?.randomUUID) return window.crypto.randomUUID();
      if (!window.crypto?.getRandomValues) return null;
      const bytes = window.crypto.getRandomValues(new Uint8Array(16));
      bytes[6] = (bytes[6] & 15) | 64;
      bytes[8] = (bytes[8] & 63) | 128;
      const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
      return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
    } catch {
      return null;
    }
  }

  const pageId = createPageId();

  async function request(path, options = {}) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(`/api/community${path}`, {
        ...options,
        credentials: "same-origin",
        cache: "no-store",
        headers: { ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers },
        signal: controller.signal
      });
      let payload;
      try {
        payload = await response.json();
      } catch {
        throw new CommunityError("bad_response");
      }
      if (!response.ok) {
        const defaults = { 401: "unauthorized", 403: "forbidden_origin", 404: "not_found", 422: "validation_error", 429: "rate_limited" };
        throw new CommunityError(payload?.detail?.code || defaults[response.status] || "community_unavailable");
      }
      if (!payload || typeof payload !== "object" || Array.isArray(payload)) throw new CommunityError("bad_response");
      return payload;
    } catch (error) {
      if (error instanceof CommunityError) throw error;
      throw new CommunityError(error.name === "AbortError" ? "timeout" : "network_error");
    } finally {
      window.clearTimeout(timeout);
    }
  }

  function applyStats(payload) {
    if (typeof payload.enabled !== "boolean") throw new CommunityError("bad_response");
    const modes = ["review", "public", "private"];
    state.enabled = payload.enabled;
    state.moderation = modes.includes(payload.moderation) ? payload.moderation : "private";
    state.stats = payload.enabled ? payload : null;
  }

  function formatCount(value) {
    return Number.isSafeInteger(value) && value >= 0
      ? new Intl.NumberFormat(i18n.getLanguage()).format(value)
      : "—";
  }

  function render() {
    $("page-views").textContent = formatCount(state.stats?.page_views);
    $("unique-visitors").textContent = formatCount(state.stats?.unique_visitors);
    const status = $("community-status");
    const statusKey = state.phase === "loading" ? "community.loading"
      : state.phase === "disabled" ? "community.notConfigured"
        : state.phase === "unavailable" ? "community.unavailable"
          : state.visitNotice || "community.ready";
    status.replaceChildren(document.createTextNode(t(statusKey)));
    if (state.phase === "unavailable" || state.visitNotice === "community.visitUnavailable") {
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "community-retry";
      retry.textContent = t("community.retry");
      retry.disabled = state.initializing;
      retry.addEventListener("click", initialize);
      status.append(document.createTextNode(" "), retry);
    }
    fields.disabled = !state.enabled || state.phase !== "ready" || state.submitting;
    $("feedback-submit-label").textContent = t(state.submitting ? "community.submitting" : "community.submit");
    $("feedback-submit").disabled = fields.disabled;
    $("moderation-note").textContent = t(`community.${state.moderation}Note`);
    const message = $("feedback-message");
    message.hidden = !state.message;
    message.textContent = state.message ? t(state.message.key) : "";
    message.classList.toggle("feedback-error", state.message?.kind === "error");
    message.classList.toggle("feedback-success", state.message?.kind === "success");
    $("feedback-count").textContent = t("community.characterCount", {
      count: new Intl.NumberFormat(i18n.getLanguage()).format(bodyInput.value.length)
    });
    renderComments();
  }

  function renderComments() {
    const area = $("comments-area");
    area.hidden = !state.enabled || state.moderation === "private";
    if (area.hidden) return;
    const list = $("comments-list");
    list.replaceChildren();
    for (const comment of state.comments) {
      const article = document.createElement("article");
      article.className = "feedback-entry";
      const heading = document.createElement("div");
      heading.className = "feedback-entry-heading";
      const name = document.createElement("strong");
      name.textContent = comment.name || t("community.guest");
      const category = document.createElement("span");
      category.className = "feedback-category";
      category.textContent = t(`community.${comment.category}`);
      heading.append(name, category);
      const date = new Date(comment.created_at);
      if (Number.isFinite(date.valueOf())) {
        const timestamp = document.createElement("time");
        timestamp.className = "feedback-date";
        timestamp.dateTime = comment.created_at;
        timestamp.textContent = new Intl.DateTimeFormat(i18n.getLanguage(), {
          dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Taipei"
        }).format(date);
        heading.append(timestamp);
      }
      const body = document.createElement("p");
      body.className = "feedback-body";
      body.style.whiteSpace = "pre-wrap";
      body.textContent = comment.body;
      article.append(heading, body);
      list.append(article);
    }
    const empty = $("comments-empty");
    empty.hidden = state.comments.length > 0 && state.commentsState !== "error";
    empty.textContent = t(state.commentsState === "loading" ? "community.commentsLoading"
      : state.commentsState === "error" ? "community.commentsUnavailable" : "community.commentsEmpty");
    const more = $("comments-more");
    more.hidden = !state.nextCursor;
    more.disabled = state.loadingMore;
    more.textContent = t(state.loadingMore ? "community.loadingMore" : "community.loadMore");
  }

  function validateComment(comment) {
    if (!comment || !Number.isSafeInteger(comment.id) || comment.id < 1
      || typeof comment.body !== "string" || typeof comment.created_at !== "string"
      || (comment.name !== null && comment.name !== undefined && typeof comment.name !== "string")) {
      throw new CommunityError("bad_response");
    }
    return {
      id: comment.id,
      name: comment.name || "",
      body: comment.body,
      category: ["suggestion", "bug", "other"].includes(comment.category) ? comment.category : "other",
      created_at: comment.created_at
    };
  }

  async function loadComments(append = false) {
    if (!state.enabled || state.moderation === "private" || state.loadingMore) return;
    const cursor = append ? state.nextCursor : null;
    if (append && !cursor) return;
    state.loadingMore = true;
    state.commentsState = append ? state.commentsState : "loading";
    renderComments();
    try {
      const query = new URLSearchParams({ limit: "10" });
      if (cursor) query.set("before", String(cursor));
      const payload = await request(`/comments?${query}`);
      if (!Array.isArray(payload.items)) throw new CommunityError("bad_response");
      if (payload.moderation === "private") {
        state.moderation = "private";
        state.comments = [];
        state.nextCursor = null;
        return;
      }
      const incoming = payload.items.map(validateComment);
      const merged = new Map((append ? state.comments : []).map((item) => [item.id, item]));
      for (const item of incoming) merged.set(item.id, item);
      state.comments = [...merged.values()].sort((a, b) => b.id - a.id);
      state.nextCursor = Number.isSafeInteger(payload.next_cursor) && payload.next_cursor > 0
        ? payload.next_cursor : null;
      state.commentsState = "ready";
    } catch {
      state.commentsState = "error";
    } finally {
      state.loadingMore = false;
      renderComments();
    }
  }

  async function initialize() {
    if (state.initializing) return;
    state.initializing = true;
    state.phase = "loading";
    state.visitNotice = null;
    render();
    try {
      applyStats(await request("/stats"));
      if (!state.enabled) {
        state.phase = "disabled";
        return;
      }
      if (!pageId) {
        state.visitNotice = "community.cookieUnavailable";
      } else if (!state.visitRecorded) {
        try {
          applyStats(await request("/visits", { method: "POST", body: JSON.stringify({ page_id: pageId }) }));
          state.visitRecorded = true;
        } catch {
          state.visitNotice = "community.visitUnavailable";
          try { applyStats(await request("/stats")); } catch { /* Keep the last known counts. */ }
        }
      }
      state.phase = state.enabled ? "ready" : "disabled";
    } catch {
      state.phase = "unavailable";
      state.enabled = false;
      state.stats = null;
    } finally {
      state.initializing = false;
      render();
      if (state.enabled && state.moderation !== "private") loadComments();
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (state.submitting || !state.enabled || state.phase !== "ready") return;
    const name = nameInput.value.trim();
    const body = bodyInput.value.trim();
    if (!body || body.length > 2000) {
      state.message = { key: "community.invalidBody", kind: "error" };
      render();
      bodyInput.focus();
      return;
    }
    if (name.length > 80) {
      state.message = { key: "community.invalidName", kind: "error" };
      render();
      nameInput.focus();
      return;
    }
    state.submitting = true;
    state.message = null;
    render();
    try {
      const payload = await request("/comments", {
        method: "POST", body: JSON.stringify({ name, body, category: categoryInput.value })
      });
      if (!payload.comment || !["pending", "published", "hidden"].includes(payload.comment.status)) {
        throw new CommunityError("bad_response");
      }
      bodyInput.value = "";
      const messageKey = state.moderation === "private" ? "community.sentPrivate"
        : state.moderation === "public" && payload.comment.status === "published"
          ? "community.sentPublic" : "community.sentReview";
      state.message = { key: messageKey, kind: "success" };
      if (state.moderation === "public" && payload.comment.status === "published") await loadComments();
    } catch (error) {
      state.message = { key: `community.error.${error.code || "community_unavailable"}`, kind: "error" };
      if (error.code === "not_configured") {
        state.enabled = false;
        state.phase = "disabled";
        state.stats = null;
      }
    } finally {
      state.submitting = false;
      render();
    }
  });

  bodyInput.addEventListener("input", () => {
    if (state.message) state.message = null;
    render();
  });
  $("comments-more").addEventListener("click", () => loadComments(true));
  i18n.subscribe(render);
  render();
  initialize();
})();
