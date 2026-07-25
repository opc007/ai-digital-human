/**
 * 素材中心：配置 → 角色 → 造型 → 生成待机 → 预览/删除
 */
const $ = (id) => document.getElementById(id);
const state = {
  token: localStorage.getItem("token") || "dev-token",
  assets: null,
  characters: [],
  characterId: localStorage.getItem("dh_character_id") || "demo",
  lookId: localStorage.getItem("dh_look_id") || "default",
  i2vReady: false,
  idleUrl: "",
  creating: false,
  wizPage: 1,
  prevWizPage: 1,
};

const WIZ_HINTS = {
  1: "填好三项并保存，再进入创建角色",
  2: "新建或点选角色后，点下一步上传照片",
  3: "上传造型照片后，点下一步生成待机",
  4: "生成预览，满意后去开播台",
  more: "声音与其它工具（非必做）",
};

function toast(msg, isErr = false) {
  const el = $("toast");
  if (!el) return;
  el.textContent = msg;
  el.classList.toggle("err", !!isErr);
  el.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.add("hidden"), 3200);
}

function escapeAttr(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;");
}

function persistSelection() {
  localStorage.setItem("dh_character_id", state.characterId || "demo");
  localStorage.setItem("dh_look_id", state.lookId || "default");
}

async function api(path, opts = {}) {
  const headers = {
    Authorization: `Bearer ${state.token}`,
    ...(opts.headers || {}),
  };
  if (opts.json) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.json);
    delete opts.json;
  }
  const res = await fetch(path, { ...opts, headers });
  const text = await res.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    data = { raw: text };
  }
  if (!res.ok) {
    const msg = data.detail || data.message || text || res.statusText;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

function setStatus(elId, text, tone) {
  const el = $(elId);
  if (!el) return;
  el.textContent = text;
  el.classList.remove("ok", "warn", "muted");
  if (tone) el.classList.add(tone);
}

function stepDone(n) {
  const hasChar = !!(state.characters || []).length && !!state.characterId;
  const hasSource = !!(state.assets && state.assets.source_url);
  if (n === 1) return !!state.i2vReady;
  if (n === 2) return hasChar;
  if (n === 3) return hasSource;
  if (n === 4) return !!state.idleUrl;
  return false;
}

function canEnterPage(page) {
  if (page === "more") return true;
  const n = Number(page);
  if (!n || n < 1 || n > 4) return false;
  for (let i = 1; i < n; i++) {
    if (!stepDone(i)) return false;
  }
  return true;
}

function suggestedStartPage() {
  if (!stepDone(1)) return 1;
  if (!stepDone(2)) return 2;
  if (!stepDone(3)) return 3;
  return 4;
}

function updateFlowSteps() {
  const page = state.wizPage;
  document.querySelectorAll(".flow-step").forEach((li) => {
    const n = Number(li.dataset.step);
    li.classList.toggle("done", stepDone(n));
    li.classList.toggle("current", page !== "more" && n === Number(page));
  });
  const sub = $("wizSub");
  if (sub) {
    sub.textContent = page === "more" ? "声音 / 其它" : `第 ${page} / 4 步`;
  }
  const back = $("btnWizBack");
  const next = $("btnWizNext");
  const hint = $("wizFootHint");
  if (hint) hint.textContent = WIZ_HINTS[page] || "";
  if (back) {
    back.disabled = page === 1 || (page === "more" && state.prevWizPage === 1);
    back.textContent = page === "more" ? "返回流程" : "上一步";
  }
  if (next) {
    if (page === "more") {
      next.classList.add("hidden");
    } else {
      next.classList.remove("hidden");
      next.disabled = page === 4;
      next.textContent = page === 4 ? "已是最后一步" : "下一步";
    }
  }
}

function goPage(page, { force = false } = {}) {
  if (page !== "more") {
    const n = Number(page);
    if (!n || n < 1 || n > 4) return;
    if (!force && !canEnterPage(n)) {
      const need = suggestedStartPage();
      toast(`请先完成第 ${need} 步`, true);
      page = need;
    } else {
      page = n;
    }
  }
  if (state.wizPage !== "more") state.prevWizPage = state.wizPage;
  state.wizPage = page;
  document.querySelectorAll(".wiz-page").forEach((sec) => {
    const p = sec.dataset.page;
    const active = String(p) === String(page);
    sec.classList.toggle("active", active);
  });
  updateFlowSteps();
  if (page === "more") {
    refreshComfy?.();
    refreshJobs?.();
    refreshVoice?.();
  }
  if (page === 2) $("newCharName")?.focus();
  if (page === 3) $("sourceFile")?.focus();
}

function goNext() {
  const page = state.wizPage;
  if (page === "more" || page >= 4) return;
  const next = Number(page) + 1;
  if (!stepDone(page)) {
    if (page === 1) toast("请先保存视频模型配置", true);
    else if (page === 2) toast("请先新建或选择一个角色", true);
    else if (page === 3) toast("请先上传造型照片", true);
    return;
  }
  goPage(next, { force: true });
}

function goBack() {
  if (state.wizPage === "more") {
    goPage(state.prevWizPage || suggestedStartPage(), { force: true });
    return;
  }
  const page = Number(state.wizPage);
  if (page > 1) goPage(page - 1, { force: true });
}

$("btnWizNext")?.addEventListener("click", goNext);
$("btnWizBack")?.addEventListener("click", goBack);
$("btnMoreTools")?.addEventListener("click", () => goPage("more", { force: true }));
document.querySelectorAll(".flow-hit").forEach((btn) => {
  btn.addEventListener("click", () => {
    const n = Number(btn.dataset.goto);
    if (n) goPage(n);
  });
});

// —— 1. 内联 I2V 配置 ——
async function loadI2vInline() {
  const data = await api("/api/v1/settings");
  const byKey = Object.fromEntries((data.fields || []).map((f) => [f.key, f]));
  const set = (id, key) => {
    const el = $(id);
    if (!el) return;
    el.value = (byKey[key] && byKey[key].value) || "";
  };
  set("i2vBaseUrl", "VIDEO_I2V_BASE_URL");
  set("i2vApiKey", "VIDEO_I2V_API_KEY");
  set("i2vModel", "VIDEO_I2V_MODEL");
  const keyOk = !!(byKey.VIDEO_I2V_API_KEY && String(byKey.VIDEO_I2V_API_KEY.value || "").trim());
  const urlOk = !!(byKey.VIDEO_I2V_BASE_URL && String(byKey.VIDEO_I2V_BASE_URL.value || "").trim());
  const modelOk = !!(byKey.VIDEO_I2V_MODEL && String(byKey.VIDEO_I2V_MODEL.value || "").trim());
  state.i2vReady = keyOk && urlOk && modelOk;
  setStatus("cfgStatus", state.i2vReady ? "已就绪" : "请填写并保存", state.i2vReady ? "ok" : "warn");
  updateFlowSteps();
}

$("btnToggleI2vKey")?.addEventListener("click", () => {
  const input = $("i2vApiKey");
  const btn = $("btnToggleI2vKey");
  if (!input || !btn) return;
  input.type = input.type === "password" ? "text" : "password";
  btn.textContent = input.type === "password" ? "显示" : "隐藏";
});

$("btnSaveI2v")?.addEventListener("click", async () => {
  const btn = $("btnSaveI2v");
  const values = {
    VIDEO_I2V_BASE_URL: ($("i2vBaseUrl")?.value || "").trim(),
    VIDEO_I2V_API_KEY: ($("i2vApiKey")?.value || "").trim(),
    VIDEO_I2V_MODEL: ($("i2vModel")?.value || "").trim(),
  };
  if (!values.VIDEO_I2V_API_KEY) {
    toast("请填写 API Key", true);
    $("i2vApiKey")?.focus();
    return;
  }
  if (!values.VIDEO_I2V_BASE_URL) values.VIDEO_I2V_BASE_URL = "";
  if (!values.VIDEO_I2V_MODEL) values.VIDEO_I2V_MODEL = "doubao-seedance-1-5-pro_720p";
  btn.disabled = true;
  try {
    await api("/api/v1/settings", { method: "PUT", json: { values } });
    toast("视频模型配置已保存");
    await loadI2vInline();
    goPage(2, { force: true });
    $("newCharName")?.focus();
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
  }
});

// —— 2. 角色 ——
function currentCharacter() {
  return (state.characters || []).find((c) => c.id === state.characterId) || null;
}

async function loadCharacters() {
  const data = await api("/api/v1/characters");
  state.characters = data.items || [];
  if (!state.characters.find((c) => c.id === state.characterId) && state.characters[0]) {
    state.characterId = state.characters[0].id;
    state.lookId = state.characters[0].default_look || "default";
  }
  persistSelection();
  renderCharacters();
  renderLooks();
  const c = currentCharacter();
  setStatus("charStatus", c ? `当前：${c.name}` : "选一个或新建", c ? "ok" : "muted");
  const empty = $("charEmpty");
  if (empty) empty.classList.toggle("hidden", state.characters.length > 0);
  updateFlowSteps();
}

function renderCharacters() {
  const box = $("charList");
  if (!box) return;
  box.innerHTML = "";
  (state.characters || []).forEach((c) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "char-card" + (c.id === state.characterId ? " selected" : "");
    const thumb = c.source_url || c.idle_url || "";
    card.innerHTML = `
      <div class="thumb" style="${thumb ? `background-image:url(${escapeAttr(thumb)}?t=${Date.now()})` : ""}"></div>
      <div class="name">${escapeAttr(c.name || c.id)}</div>
      <div class="meta">${c.ready ? "可开播" : "待完善"} · ${(c.looks || []).length} 造型</div>
    `;
    card.onclick = async () => {
      state.characterId = c.id;
      state.lookId = c.default_look || (c.looks && c.looks[0] && c.looks[0].id) || "default";
      persistSelection();
      renderCharacters();
      renderLooks();
      await loadAssets();
      setStatus("charStatus", `当前：${c.name}`, "ok");
      goPage(3, { force: true });
    };
    box.appendChild(card);
  });
}

async function createCharacter() {
  if (state.creating) return;
  if (!state.i2vReady) {
    toast("请先保存第 1 步的视频模型配置", true);
    goPage(1, { force: true });
    return;
  }
  const name = ($("newCharName")?.value || "").trim();
  if (!name) {
    toast("请先填写角色名字", true);
    $("newCharName")?.focus();
    return;
  }
  const btn = $("btnCreateChar");
  state.creating = true;
  if (btn) {
    btn.disabled = true;
    btn.textContent = "创建中…";
  }
  try {
    const c = await api("/api/v1/characters", { method: "POST", json: { name } });
    state.characterId = c.id;
    state.lookId = "default";
    persistSelection();
    if ($("newCharName")) $("newCharName").value = "";
    toast(`已创建「${c.name}」，接着上传造型照片`);
    await loadCharacters();
    await loadAssets();
    goPage(3, { force: true });
    $("sourceFile")?.focus();
  } catch (e) {
    toast(e.message, true);
  } finally {
    state.creating = false;
    if (btn) {
      btn.disabled = false;
      btn.textContent = "新建角色";
    }
  }
}

$("btnCreateChar")?.addEventListener("click", createCharacter);
$("newCharName")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    createCharacter();
  }
});

$("btnDeleteChar")?.addEventListener("click", async () => {
  const c = currentCharacter();
  if (!c) return;
  if (c.id === "demo") {
    toast("演示角色不能删除", true);
    return;
  }
  if (!confirm(`确定删除角色「${c.name}」？素材会一并删除。`)) return;
  try {
    await api(`/api/v1/characters/${encodeURIComponent(c.id)}`, { method: "DELETE" });
    toast(`已删除「${c.name}」`);
    state.characterId = "demo";
    state.lookId = "default";
    persistSelection();
    await loadCharacters();
    await loadAssets();
  } catch (e) {
    toast(e.message, true);
  }
});

// —— 3. 造型 ——
function renderLooks() {
  const box = $("lookList");
  const hint = $("lookHint");
  if (!box) return;
  const c = currentCharacter();
  box.innerHTML = "";
  if (!c) {
    if (hint) hint.textContent = "请先新建或选择一个角色。";
    return;
  }
  if (hint) {
    hint.textContent = `当前角色「${c.name}」· 推荐半身胸像。可添加多套造型。`;
  }
  (c.looks || []).forEach((lk) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "look-card" + (lk.id === state.lookId ? " selected" : "");
    const thumb = lk.source_url || lk.idle_url || "";
    card.innerHTML = `
      <div class="thumb" style="${thumb ? `background-image:url(${escapeAttr(thumb)}?t=${Date.now()})` : ""}"></div>
      <div class="name">${escapeAttr(lk.name || lk.id)}</div>
      <div class="meta">${lk.ready ? "已有待机" : "待生成"}</div>
    `;
    card.onclick = async () => {
      state.lookId = lk.id;
      persistSelection();
      renderLooks();
      await loadAssets();
    };
    box.appendChild(card);
  });
}

$("btnAddLook")?.addEventListener("click", async () => {
  if (!state.characterId) {
    toast("请先选择角色", true);
    return;
  }
  const name = ($("newLookName")?.value || "").trim() || "新造型";
  try {
    const r = await api(`/api/v1/characters/${encodeURIComponent(state.characterId)}/looks`, {
      method: "POST",
      json: { name },
    });
    state.lookId = r.look_id;
    persistSelection();
    toast(`已添加造型「${r.look_name}」`);
    if ($("newLookName")) $("newLookName").value = "";
    await loadCharacters();
    await loadAssets();
  } catch (e) {
    toast(e.message, true);
  }
});

$("btnDeleteLook")?.addEventListener("click", async () => {
  if ((state.lookId || "default") === "default") {
    toast("默认造型不能删，可删整个角色或换照片", true);
    return;
  }
  const c = currentCharacter();
  const lk = (c?.looks || []).find((x) => x.id === state.lookId);
  if (!confirm(`确定删除造型「${lk?.name || state.lookId}」？`)) return;
  try {
    await api(
      `/api/v1/characters/${encodeURIComponent(state.characterId)}/looks/${encodeURIComponent(state.lookId)}`,
      { method: "DELETE" }
    );
    toast("造型已删除");
    state.lookId = "default";
    persistSelection();
    await loadCharacters();
    await loadAssets();
  } catch (e) {
    toast(e.message, true);
  }
});

$("btnUploadSource")?.addEventListener("click", async () => {
  const file = $("sourceFile")?.files?.[0];
  if (!file) {
    toast("请先选择一张照片", true);
    $("sourceFile")?.click();
    return;
  }
  if (!state.i2vReady) {
    toast("请先保存视频模型配置", true);
    goPage(1, { force: true });
    return;
  }
  const btn = $("btnUploadSource");
  btn.disabled = true;
  btn.textContent = "上传中…";
  const fd = new FormData();
  fd.append("file", file);
  fd.append("avatar_id", state.characterId || "demo");
  fd.append("look_id", state.lookId || "default");
  try {
    const res = await fetch("/api/v1/assets/source", {
      method: "POST",
      headers: { Authorization: `Bearer ${state.token}` },
      body: fd,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "上传失败");
    toast("照片已上传，可以生成待机了");
    await loadAssets();
    await loadCharacters();
    goPage(4, { force: true });
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "上传 / 更换照片";
  }
});

$("sourceFile")?.addEventListener("change", () => {
  const file = $("sourceFile")?.files?.[0];
  if (!file) return;
  const url = URL.createObjectURL(file);
  const box = $("sourcePreview");
  if (box) {
    box.style.backgroundImage = `url(${url})`;
    box.textContent = "";
  }
});

// —— assets / idle preview ——
function setIdlePreview(url) {
  state.idleUrl = url || "";
  const video = $("idlePreviewVideo");
  const empty = $("idlePreviewEmpty");
  const hit = $("btnIdlePreview");
  const badge = $("idlePlayBadge");
  const del = $("btnDeleteIdle");
  const st = $("idleStatus");
  if (url) {
    if (video) {
      video.src = url + (url.includes("?") ? "&" : "?") + "t=" + Date.now();
      video.classList.remove("hidden");
      video.play().catch(() => {});
    }
    if (empty) empty.classList.add("hidden");
    if (hit) hit.disabled = false;
    if (badge) badge.classList.remove("hidden");
    if (del) del.disabled = false;
    setStatus("idleStatus", "已生成 · 可预览", "ok");
    if ($("presetGenStatus")) {
      $("presetGenStatus").textContent = "点击左侧画面可放大预览；不满意可删除后重新生成。";
    }
  } else {
    if (video) {
      try {
        video.pause();
        video.removeAttribute("src");
        video.load();
      } catch {}
    }
    if (empty) empty.classList.remove("hidden");
    if (hit) hit.disabled = true;
    if (badge) badge.classList.add("hidden");
    if (del) del.disabled = true;
    setStatus("idleStatus", "未生成", "muted");
  }
  updateFlowSteps();
}

async function loadAssets() {
  const q = new URLSearchParams({
    avatar_id: state.characterId || "demo",
    look_id: state.lookId || "default",
  });
  const data = await api(`/api/v1/assets?${q}`);
  state.assets = data;
  const box = $("sourcePreview");
  if (box) {
    if (data.source_url) {
      box.style.backgroundImage = `url(${data.source_url}?t=${Date.now()})`;
      box.textContent = "";
      setStatus("lookStatus", "已有照片", "ok");
    } else {
      box.style.backgroundImage = "";
      box.textContent = "点击右侧选择照片";
      setStatus("lookStatus", "待上传", "muted");
    }
  }
  const idle = (data.actions || []).find((a) => a.name === "idle" && a.exists && a.url);
  setIdlePreview(idle ? idle.url : "");

  const list = $("actionList");
  if (list) {
    list.innerHTML = "";
    (data.actions || []).forEach((a) => {
      const card = document.createElement("div");
      card.className = "action-card" + (a.exists ? " ok" : "");
      card.innerHTML = `
        <div class="title">${escapeAttr(a.label || a.name)}</div>
        <div class="meta">${escapeAttr(a.name)} · ${a.exists ? (a.duration_ms / 1000).toFixed(1) + "s" : "未上传"}</div>
        ${a.exists && a.url ? `<video src="${escapeAttr(a.url)}?t=${Date.now()}" muted playsinline></video>` : `<div class="meta">可手动上传 mp4</div>`}
        <div class="btns">
          <button type="button" class="btn primary btn-up">上传</button>
          ${a.exists ? `<button type="button" class="btn ghost btn-prev">预览</button><button type="button" class="btn ghost btn-del">删除</button>` : ""}
          <button type="button" class="btn ghost btn-gen">Comfy生成</button>
        </div>
      `;
      card.querySelector(".btn-up").onclick = () => openUpload(a.name, a.label);
      const prev = card.querySelector(".btn-prev");
      if (prev) prev.onclick = () => openLightbox(a.url, a.label || a.name);
      const del = card.querySelector(".btn-del");
      if (del) {
        del.onclick = async () => {
          if (!confirm(`删除动作「${a.label || a.name}」？`)) return;
          try {
            await api(
              `/api/v1/assets/actions/${encodeURIComponent(a.name)}?avatar_id=${encodeURIComponent(state.characterId)}&look_id=${encodeURIComponent(state.lookId || "default")}`,
              { method: "DELETE" }
            );
            toast("已删除");
            await loadAssets();
            await loadCharacters();
          } catch (e) {
            toast(e.message, true);
          }
        };
      }
      card.querySelector(".btn-gen").onclick = () => generateOne(a.name);
      const v = card.querySelector("video");
      if (v) {
        v.onclick = () => openLightbox(a.url, a.label || a.name);
        v.style.cursor = "pointer";
      }
      list.appendChild(card);
    });
  }

  const gen = $("genList");
  if (gen) {
    gen.innerHTML = (data.actions || [])
      .map(
        (a) => `
      <div class="gen-row">
        <span>${escapeAttr(a.label || a.name)} <span class="badge-sm ${a.exists ? "ok" : ""}">${a.exists ? "已有" : "缺失"}</span></span>
        <button type="button" class="btn ghost sm" data-act="${escapeAttr(a.name)}">生成</button>
      </div>`
      )
      .join("");
    gen.querySelectorAll("button[data-act]").forEach((b) => {
      b.onclick = () => generateOne(b.dataset.act);
    });
  }
  updateFlowSteps();
}

function openLightbox(url, title) {
  if (!url) return;
  const overlay = $("videoLightbox");
  const video = $("lightboxVideo");
  if (!overlay || !video) return;
  const head = overlay.querySelector("h2");
  if (head) head.textContent = title || "视频预览";
  video.src = url + (url.includes("?") ? "&" : "?") + "t=" + Date.now();
  video.muted = true;
  overlay.classList.remove("hidden");
  overlay.setAttribute("aria-hidden", "false");
  video.play().catch(() => {});
}

function closeLightbox() {
  const overlay = $("videoLightbox");
  const video = $("lightboxVideo");
  if (video) {
    try {
      video.pause();
      video.removeAttribute("src");
      video.load();
    } catch {}
  }
  if (overlay) {
    overlay.classList.add("hidden");
    overlay.setAttribute("aria-hidden", "true");
  }
}

$("btnIdlePreview")?.addEventListener("click", () => {
  if (!state.idleUrl) return;
  openLightbox(state.idleUrl, "呼吸待机预览");
});
$("btnCloseLightbox")?.addEventListener("click", closeLightbox);
$("btnCloseLightbox2")?.addEventListener("click", closeLightbox);
$("videoLightbox")?.addEventListener("click", (e) => {
  if (e.target === $("videoLightbox")) closeLightbox();
});
$("btnLightboxMute")?.addEventListener("click", () => {
  const v = $("lightboxVideo");
  if (!v) return;
  v.muted = !v.muted;
  if (!v.muted) v.volume = 1;
});

async function deleteIdle() {
  if (!state.idleUrl) return;
  if (!confirm("删除当前待机视频？删除后可重新生成。")) return;
  try {
    await api(
      `/api/v1/assets/actions/idle?avatar_id=${encodeURIComponent(state.characterId)}&look_id=${encodeURIComponent(state.lookId || "default")}`,
      { method: "DELETE" }
    );
    toast("待机视频已删除");
    closeLightbox();
    await loadAssets();
    await loadCharacters();
    if ($("presetGenStatus")) $("presetGenStatus").textContent = "已删除。可重新点「生成呼吸待机」。";
  } catch (e) {
    toast(e.message, true);
  }
}
$("btnDeleteIdle")?.addEventListener("click", deleteIdle);
$("btnLightboxDelete")?.addEventListener("click", deleteIdle);

// —— 生成 ——
$("btnGenPreset")?.addEventListener("click", async () => {
  if (!state.i2vReady) {
    toast("请先保存第 1 步视频模型配置", true);
    goPage(1, { force: true });
    return;
  }
  if (!state.assets?.source_url) {
    toast("请先上传造型照片", true);
    goPage(3, { force: true });
    return;
  }
  const btn = $("btnGenPreset");
  const st = $("presetGenStatus");
  btn.disabled = true;
  const old = btn.textContent;
  btn.textContent = "提交中…";
  if (st) st.textContent = "正在提交生成任务…";
  try {
    const data = await api("/api/v1/assets/generate-preset", {
      method: "POST",
      json: {
        avatar_id: state.characterId || "demo",
        look_id: state.lookId || "default",
        force: true,
        orientation: localStorage.getItem("dh_orientation") || "portrait",
      },
    });
    if (data.async && data.job_id) {
      if (st) st.textContent = data.message || "生成中，请稍候…";
      btn.textContent = "生成中…";
      await pollI2vJob(data.job_id, st);
      if (state.idleUrl) openLightbox(state.idleUrl, "新生成的待机视频");
    } else {
      toast(data.message || "完成");
      await loadAssets();
      await loadCharacters();
    }
  } catch (e) {
    toast(e.message, true);
    if (st) st.textContent = "失败：" + e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
});

async function pollI2vJob(jobId, st) {
  const started = Date.now();
  while (Date.now() - started < 15 * 60 * 1000) {
    await new Promise((r) => setTimeout(r, 2500));
    const job = await api(`/api/v1/assets/jobs/${encodeURIComponent(jobId)}`);
    const status = job.status || "";
    const msg = job.message || status;
    if (st) {
      const prog = job.progress != null ? ` ${job.progress}%` : "";
      st.textContent = `${msg}${prog}`;
    }
    if (status === "done" || status === "completed") {
      toast(job.message || "待机视频已生成");
      await loadAssets();
      await loadCharacters();
      return job;
    }
    if (status === "error" || status === "failed") {
      throw new Error(job.message || "生成失败");
    }
  }
  throw new Error("等待超时，请稍后重试");
}

function openUpload(action, label) {
  $("dlgAction").value = action;
  $("dlgTitle").textContent = `上传动作：${label || action}`;
  $("dlgFile").value = "";
  $("uploadDlg").showModal();
}

$("dlgOk")?.addEventListener("click", async () => {
  const action = $("dlgAction").value;
  const file = $("dlgFile").files[0];
  if (!file) {
    toast("请选择视频文件", true);
    return;
  }
  const fd = new FormData();
  fd.append("file", file);
  fd.append("action", action);
  fd.append("avatar_id", state.characterId || "demo");
  fd.append("look_id", state.lookId || "default");
  try {
    const res = await fetch("/api/v1/assets/actions/upload", {
      method: "POST",
      headers: { Authorization: `Bearer ${state.token}` },
      body: fd,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "上传失败");
    toast(`已上传 ${action}`);
    $("uploadDlg").close();
    await loadAssets();
    await loadCharacters();
  } catch (e) {
    toast(e.message, true);
  }
});

// —— Comfy / voice / settings（保留） ——
async function refreshComfy() {
  try {
    const st = await api("/api/v1/settings");
    const f = (st.fields || []).find((x) => x.key === "COMFYUI_BASE_URL");
    if (f && $("comfyUrl")) $("comfyUrl").value = f.value || "http://127.0.0.1:8000";
    const s = await api("/api/v1/comfyui/status");
    $("comfyStatus").innerHTML = `
      <div>连接：${s.ok ? '<span class="ok">在线</span>' : '<span class="no">离线</span>'} — ${s.message || ""}</div>
      <div>地址：${s.base_url || ""}</div>
      <div>工作流：${s.workflow_ready ? '<span class="ok">已找到</span>' : '<span class="no">未放置</span>'}</div>
    `;
  } catch (e) {
    if ($("comfyStatus")) $("comfyStatus").textContent = e.message;
  }
}

$("btnSaveComfy") &&
  ($("btnSaveComfy").onclick = async () => {
    try {
      await api("/api/v1/settings", {
        method: "PUT",
        json: { values: { COMFYUI_BASE_URL: $("comfyUrl").value.trim() } },
      });
      toast("已保存");
      await refreshComfy();
    } catch (e) {
      toast(e.message, true);
    }
  });
$("btnTestComfy") &&
  ($("btnTestComfy").onclick = async () => {
    try {
      await api("/api/v1/settings", {
        method: "PUT",
        json: { values: { COMFYUI_BASE_URL: $("comfyUrl").value.trim() } },
      });
      await refreshComfy();
      toast("已刷新连接状态");
    } catch (e) {
      toast(e.message, true);
    }
  });

async function generateOne(action) {
  try {
    const data = await api("/api/v1/assets/generate", {
      method: "POST",
      json: { action, avatar_id: state.characterId || "demo" },
    });
    toast(`已排队：${action}`);
    await refreshJobs();
    pollJob(data.job?.id);
  } catch (e) {
    toast(e.message, true);
  }
}

$("btnGenMissing") &&
  ($("btnGenMissing").onclick = async () => {
    const actions = (state.assets?.actions || []).filter((a) => !a.exists);
    if (!actions.length) {
      toast("没有缺失动作");
      return;
    }
    for (const a of actions) {
      try {
        await generateOne(a.name);
      } catch {}
    }
  });

async function refreshJobs() {
  try {
    const data = await api("/api/v1/assets/jobs");
    const box = $("jobList");
    if (!box) return;
    const jobs = data.jobs || [];
    if (!jobs.length) {
      box.innerHTML = "<p class='hint'>暂无生成任务</p>";
      return;
    }
    box.innerHTML = jobs
      .map((j) => {
        const cls = j.status === "done" ? "ok" : j.status === "error" ? "err" : "run";
        return `<div class="job-row">
          <span><b>${escapeAttr(j.action || j.type)}</b> · ${escapeAttr(j.message || j.status)}</span>
          <span class="badge-sm ${cls}">${escapeAttr(j.status)}</span>
        </div>`;
      })
      .join("");
  } catch (e) {
    if ($("jobList")) $("jobList").textContent = e.message;
  }
}
$("btnRefreshJobs") && ($("btnRefreshJobs").onclick = refreshJobs);

function pollJob(id) {
  if (!id) return;
  let n = 0;
  const t = setInterval(async () => {
    n++;
    try {
      const j = await api(`/api/v1/assets/jobs/${id}`);
      if (j.status === "done" || j.status === "error") {
        clearInterval(t);
        await refreshJobs();
        await loadAssets();
        await loadCharacters();
        toast(j.status === "done" ? "生成完成" : j.message || "生成失败", j.status !== "done");
      } else if (n > 300) clearInterval(t);
      else refreshJobs();
    } catch {
      clearInterval(t);
    }
  }, 2000);
}

async function refreshVoice() {
  try {
    const data = await api("/api/v1/voice");
    const box = $("voiceSamples");
    if (!box) return;
    const samples = data.samples || [];
    box.innerHTML = samples.length
      ? samples
          .map(
            (s) =>
              `<div class="sample-row"><span>${escapeAttr(s.name)}</span><audio controls src="${escapeAttr(s.url)}"></audio></div>`
          )
          .join("")
      : "<p class='hint'>还没有上传参考音频</p>";
  } catch (e) {
    toast(e.message, true);
  }
}

$("btnTtsPreview") &&
  ($("btnTtsPreview").onclick = async () => {
    try {
      const data = await api("/api/v1/voice/preview", {
        method: "POST",
        json: { text: $("ttsText").value, mock: false },
      });
      $("ttsAudio").src = data.url + "?t=" + Date.now();
      $("ttsAudio").play().catch(() => {});
      toast("试听已生成");
    } catch (e) {
      toast(e.message, true);
    }
  });

$("btnUploadVoice") &&
  ($("btnUploadVoice").onclick = async () => {
    const file = $("voiceSample").files[0];
    if (!file) {
      toast("请选择音频", true);
      return;
    }
    const fd = new FormData();
    fd.append("file", file);
    try {
      const res = await fetch("/api/v1/voice/sample", {
        method: "POST",
        headers: { Authorization: `Bearer ${state.token}` },
        body: fd,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "上传失败");
      toast("样本已上传");
      await refreshVoice();
    } catch (e) {
      toast(e.message, true);
    }
  });

function openSettings() {
  $("settingsOverlay")?.classList.remove("hidden");
  $("settingsOverlay")?.setAttribute("aria-hidden", "false");
  loadSettingsForm();
}
function closeSettings() {
  $("settingsOverlay")?.classList.add("hidden");
  $("settingsOverlay")?.setAttribute("aria-hidden", "true");
}

async function loadSettingsForm() {
  const body = $("settingsBody");
  if (!body) return;
  body.innerHTML = "<p class='hint'>加载中…</p>";
  try {
    const data = await api("/api/v1/settings");
    body.innerHTML = (data.groups || [])
      .map((g, idx) => {
        const fields = (g.fields || [])
          .map((f) => {
            const val = f.value || "";
            const badge = f.configured ? '<span class="configured">已填</span>' : "";
            if (f.secret) {
              return `<label>${f.label}${badge}
                <div class="pw-row">
                  <input type="password" data-key="${f.key}" value="${escapeAttr(val)}" placeholder="${escapeAttr(f.placeholder || "")}" />
                  <button type="button" class="btn ghost sm toggle-pw">显示</button>
                </div>
                <div class="field-help">${f.help || ""}</div>
              </label>`;
            }
            return `<label>${f.label}${badge}
              <input type="text" data-key="${f.key}" value="${escapeAttr(val)}" placeholder="${escapeAttr(f.placeholder || "")}" />
              <div class="field-help">${f.help || ""}</div>
            </label>`;
          })
          .join("");
        const pri = idx === 0 || g.id === "video_i2v" ? " settings-group-priority" : "";
        return `<section class="settings-group${pri}"><h3>${g.label}</h3>${fields}</section>`;
      })
      .join("");
    body.querySelectorAll(".toggle-pw").forEach((btn) => {
      btn.onclick = () => {
        const input = btn.parentElement.querySelector("input");
        input.type = input.type === "password" ? "text" : "password";
        btn.textContent = input.type === "password" ? "显示" : "隐藏";
      };
    });
  } catch (e) {
    body.innerHTML = `<p class="hint">${escapeAttr(e.message)}</p>`;
  }
}

function collectSettingsValues() {
  const values = {};
  $("settingsBody")
    ?.querySelectorAll("input[data-key]")
    .forEach((el) => {
      values[el.dataset.key] = el.value;
    });
  return values;
}

$("btnOpenSettings")?.addEventListener("click", openSettings);
$("btnOpenSettings2")?.addEventListener("click", openSettings);
$("btnCloseSettings")?.addEventListener("click", closeSettings);
$("settingsOverlay")?.addEventListener("click", (e) => {
  if (e.target === $("settingsOverlay")) closeSettings();
});
$("btnSaveSettings")?.addEventListener("click", async () => {
  try {
    await api("/api/v1/settings", {
      method: "PUT",
      json: { values: collectSettingsValues() },
    });
    toast("配置已保存");
    await loadI2vInline();
    closeSettings();
  } catch (e) {
    toast(e.message, true);
  }
});

(async () => {
  try {
    const login = await api("/api/v1/auth/login", {
      method: "POST",
      json: { username: "admin", password: "admin" },
    });
    state.token = login.token;
    localStorage.setItem("token", state.token);
  } catch {}
  try {
    await loadI2vInline();
    await loadCharacters();
    await loadAssets();
    goPage(suggestedStartPage(), { force: true });
  } catch (e) {
    toast("加载失败：" + e.message, true);
  }
})();
