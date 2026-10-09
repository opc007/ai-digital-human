/**
 * 数字人直播工作台 — 打开即用：左侧画面 + 右侧开播 + 底部互动
 */
const $ = (id) => document.getElementById(id);

const state = {
  token: localStorage.getItem("token") || "dev-token",
  roomId: "demo",
  platforms: [],
  runtimes: [],
  keys: {},
  platformId: "preview",
  runtimeId: "cloud",
  personaId: 1,
  ws: null,
  live: false,
  /** 待机用：正脸图（优先）或动作视频第一帧定格，禁止循环播 */
  stillImageUrl: "",
  idleVideoUrl: "",
  lastVideoUrl: "",
  /** 舞台模式：still | speaking | synthesizing */
  stageMode: "still",
  playingReply: false,
  soundUnlocked: false,
  starting: false,
  // 画面：portrait 竖屏 | landscape 横屏 | square；fit contain=完整人物
  orientation: localStorage.getItem("dh_orientation") || "portrait",
  fit: localStorage.getItem("dh_fit") || "contain",
  activeTab: localStorage.getItem("dh_tab") || "go",
  characterId: localStorage.getItem("dh_character_id") || "demo",
  lookId: localStorage.getItem("dh_look_id") || "default",
  characters: [],
  // 声音
  voiceGender: "all",
  voiceId: "",
  voiceCatalog: null,
};

const TAB_ORDER = ["go", "chat", "voice", "frame", "persona"];

/** 侧栏功能页签：一屏内翻页，避免整页滚动 */
function switchTab(name, { persist = true } = {}) {
  const id = TAB_ORDER.includes(name) ? name : "go";
  state.activeTab = id;
  if (persist) localStorage.setItem("dh_tab", id);
  document.querySelectorAll(".tab").forEach((t) => {
    const on = t.dataset.tab === id;
    t.classList.toggle("active", on);
    t.setAttribute("aria-selected", on ? "true" : "false");
  });
  document.querySelectorAll(".tab-page").forEach((p) => {
    p.classList.toggle("active", p.id === `tab-${id}`);
  });
}

const RTMP_KEYS_LS = "dh_rtmp_keys_v1";
const PLATFORM_HOTKEYS = {
  preview: { key: "0", label: "Alt+0" },
  douyin: { key: "1", label: "Alt+1" },
  kuaishou: { key: "2", label: "Alt+2" },
  wechat: { key: "3", label: "Alt+3" },
  xiaohongshu: { key: "4", label: "Alt+4" },
  tiktok: { key: "5", label: "Alt+5" },
};

// —— 工具 ——
function toast(msg, isErr = false) {
  const el = $("toast");
  if (!el) return;
  el.textContent = msg;
  el.classList.toggle("err", !!isErr);
  el.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.add("hidden"), 3600);
}

function logEvent(obj) {
  const box = $("events");
  if (!box) return;
  const div = document.createElement("div");
  div.textContent = `${new Date().toLocaleTimeString()}  ${JSON.stringify(obj)}`;
  box.prepend(div);
}

async function api(path, opts = {}) {
  const headers = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${state.token}`,
    ...(opts.headers || {}),
  };
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

function currentPlatform() {
  return state.platforms.find((p) => p.id === state.platformId) || null;
}
function currentRuntime() {
  return state.runtimes.find((r) => r.id === state.runtimeId) || null;
}
function isPreviewPlatform(p) {
  const x = p || currentPlatform();
  return !x || x.id === "preview" || !!x.dry_run;
}

function loadRtmpKeys() {
  try {
    return JSON.parse(localStorage.getItem(RTMP_KEYS_LS) || "{}") || {};
  } catch {
    return {};
  }
}
function saveRtmpKey(platformId, key) {
  const map = loadRtmpKeys();
  const k = (key || "").trim();
  if (k) map[platformId] = k;
  else delete map[platformId];
  localStorage.setItem(RTMP_KEYS_LS, JSON.stringify(map));
}
function getRtmpKey(platformId) {
  const typed = ($("rtmpKey")?.value || "").trim();
  if (typed && state.platformId === platformId) return typed;
  return (loadRtmpKeys()[platformId] || "").trim();
}

// —— 画面舞台（直播友好）——
//   待机 = 循环动作视频「前几秒」（静音微动，不定格、不盖遮罩）
//   合成中 = 继续播待机，不显示「生成中」大遮罩（直播难看）
//   说话  = 有声口型成片播一次 → 回待机循环

/** 待机循环：默认跟完整呼吸片走；可用 dh_idle_loop_sec 覆盖 */
const IDLE_LOOP_SEC = Number(localStorage.getItem("dh_idle_loop_sec") || 0);
/** 循环接缝交叉淡化（秒）。默认 0：乒乓无缝片用原生 loop 最顺；旧片可设 dh_idle_xfade_sec=0.3 */
const IDLE_XFADE_SEC = Number(localStorage.getItem("dh_idle_xfade_sec") || 0);

let _idleXfadeRaf = 0;
let _idleXfadeArmed = false;

function setStageOverlay(show, text) {
  const overlay = $("stageOverlay");
  const overlayText = $("stageOverlayText");
  if (!overlay) return;
  if (show && state.live && text && !String(text).includes("失败") && !String(text).includes("上传")) {
    show = false;
  }
  overlay.classList.toggle("hidden", !show);
  if (text && overlayText) overlayText.textContent = text;
}

function setStageBadge(text, tone) {
  const el = $("stageBadge");
  if (!el) return;
  el.textContent = text;
  el.dataset.tone = tone || "idle";
  if (tone === "busy" && state.live) {
    el.textContent = "直播中";
    el.dataset.tone = "idle";
  }
}

function unlockSound() {
  state.soundUnlocked = true;
  const video = $("previewVideo");
  if (video && state.stageMode === "speaking") {
    video.muted = false;
    video.volume = 1;
    video.play().catch(() => {});
  }
  $("btnUnmute")?.classList.add("hidden");
}

function clearVideoHandlers(video) {
  if (!video) return;
  video.onloadedmetadata = null;
  video.onseeked = null;
  video.onloadeddata = null;
  video.onended = null;
  video.onerror = null;
  video.ontimeupdate = null;
  video.onplay = null;
  video.onpause = null;
}

function stopIdleXfade() {
  cancelAnimationFrame(_idleXfadeRaf);
  _idleXfadeRaf = 0;
  _idleXfadeArmed = false;
  const b = $("previewVideoIdleB");
  if (!b) return;
  try {
    b.pause();
    b.removeAttribute("src");
    b.load();
  } catch {}
  b.classList.remove("is-on");
  b.classList.add("hidden");
}

/**
 * 待机：静音循环微动。接近片尾时用第二层短交叉淡化回片头，减轻「跳一下」。
 * （生成侧会再做正放+倒放，首尾同帧；淡化是双保险。）
 */
function showIdleLoop() {
  const video = $("previewVideo");
  const videoB = $("previewVideoIdleB");
  const img = $("stillImage");
  const url = state.idleVideoUrl;
  state.stageMode = "idle";
  state.playingReply = false;
  setStageOverlay(false);

  if (!url) {
    stopIdleXfade();
    if (img && state.stillImageUrl) {
      if (video) {
        clearVideoHandlers(video);
        try {
          video.pause();
          video.removeAttribute("src");
          video.load();
        } catch {}
        video.classList.add("hidden");
      }
      img.src = state.stillImageUrl;
      img.classList.remove("hidden");
      setStageBadge("待机", "idle");
      return;
    }
    setStageOverlay(true, "请到「素材」上传角色图并生成待机微动视频");
    return;
  }

  if (img) img.classList.add("hidden");
  if (!video) return;

  const same =
    video.dataset.idleLoop === "1" &&
    video.src &&
    video.src.includes(url.split("?")[0]) &&
    !video.classList.contains("hidden");
  if (same) {
    video.muted = true;
    video.classList.add("stage-soft");
    if (video.paused) video.play().catch(() => {});
    setStageBadge(state.live ? "待机" : "预览待机", "idle");
    if ($("phaseValue") && !state.live) $("phaseValue").textContent = "待机 · 小幅微动";
    return;
  }

  stopIdleXfade();
  clearVideoHandlers(video);
  video.classList.remove("hidden", "stage-cut-in", "stage-cut-in-on");
  video.classList.add("stage-soft");
  video.style.opacity = "";
  const useNativeLoop = !(IDLE_LOOP_SEC > 0);
  const useXfade = !!(videoB && IDLE_XFADE_SEC > 0);
  // 乒乓无缝片：原生 loop；需要交叉淡化时关掉 loop 由我们接缝
  video.loop = useNativeLoop && !useXfade;
  video.muted = true;
  video.dataset.idleLoop = "1";
  video.playsInline = true;

  const bust = url + (url.includes("?") ? "&" : "?") + "t=" + Date.now();

  const rewindIdle = () => {
    if (useNativeLoop && !useXfade) return;
    if (state.stageMode !== "idle" && state.stageMode !== "synthesizing") return;
    if (video.dataset.idleLoop !== "1") return;
    const dur = Number(video.duration) || 0;
    const lim =
      IDLE_LOOP_SEC > 0
        ? Math.min(IDLE_LOOP_SEC, dur > 0 ? dur - 0.05 : IDLE_LOOP_SEC)
        : dur > 0
          ? dur - 0.05
          : 5;
    if (video.currentTime >= lim - 0.04) {
      try {
        video.currentTime = 0.02;
      } catch {}
    }
  };

  const armIdleXfade = () => {
    if (!useXfade) return;
    if (state.stageMode !== "idle" && state.stageMode !== "synthesizing") return;
    if (video.dataset.idleLoop !== "1") return;
    const dur = Number(video.duration) || 0;
    if (!(dur > 0.6)) return;
    const left = dur - video.currentTime;
    if (left > IDLE_XFADE_SEC + 0.05) return;
    if (_idleXfadeArmed) return;
    _idleXfadeArmed = true;

    // B 从 0 起播，淡入盖住 A 的末尾 → 跳回片头
    const bSrc = video.currentSrc || video.src;
    if (!bSrc) {
      _idleXfadeArmed = false;
      return;
    }
    if (!videoB.src || !videoB.src.includes(url.split("?")[0])) {
      videoB.src = bSrc;
    }
    videoB.classList.remove("hidden");
    videoB.classList.remove("is-on");
    videoB.muted = true;
    videoB.loop = false;
    try {
      videoB.currentTime = 0.02;
    } catch {}
    videoB.play().catch(() => {});
    requestAnimationFrame(() => {
      videoB.classList.add("is-on");
      // 淡化结束后把 A 接到 B 的时间点，再藏起 B
      window.setTimeout(() => {
        if (video.dataset.idleLoop !== "1") return;
        if (state.stageMode !== "idle" && state.stageMode !== "synthesizing") return;
        try {
          const t = Math.min(videoB.currentTime || 0.05, (Number(video.duration) || 1) - 0.05);
          video.currentTime = Math.max(0.02, t);
          video.play().catch(() => {});
        } catch {}
        videoB.classList.remove("is-on");
        window.setTimeout(() => {
          try {
            videoB.pause();
          } catch {}
          _idleXfadeArmed = false;
        }, 340);
      }, Math.round(IDLE_XFADE_SEC * 1000));
    });
  };

  video.onloadeddata = () => {
    setStageOverlay(false);
    try {
      video.currentTime = 0.02;
    } catch {}
    video.play().catch(() => {});
  };
  video.ontimeupdate = () => {
    if (!useNativeLoop && !useXfade) rewindIdle();
    armIdleXfade();
  };
  let raf = 0;
  const tick = () => {
    if (!useNativeLoop && !useXfade) rewindIdle();
    armIdleXfade();
    if (video.dataset.idleLoop === "1" && (state.stageMode === "idle" || state.stageMode === "synthesizing")) {
      raf = requestAnimationFrame(tick);
    }
  };
  video.onplay = () => {
    cancelAnimationFrame(raf);
    if (!useNativeLoop || useXfade) raf = requestAnimationFrame(tick);
  };
  video.onpause = () => cancelAnimationFrame(raf);
  video.onended = () => {
    if (state.stageMode === "idle" || state.stageMode === "synthesizing") {
      if (!_idleXfadeArmed) {
        try {
          video.currentTime = 0.02;
          video.play().catch(() => {});
        } catch {}
      }
    }
  };
  video.onerror = () => {
    cancelAnimationFrame(raf);
    stopIdleXfade();
    if (state.stillImageUrl && img) {
      video.classList.add("hidden");
      img.src = state.stillImageUrl;
      img.classList.remove("hidden");
    }
  };

  if (useXfade && videoB) {
    videoB.src = bust;
    videoB.load();
    video.loop = false;
  }

  video.src = bust;
  video.load();
  setStageBadge(state.live ? "待机" : "预览待机", "idle");
  if ($("phaseValue") && !state.live) $("phaseValue").textContent = "待机 · 慢呼吸";
  if ($("phaseReply") && !state.live) {
    $("phaseReply").textContent = "慢而小的呼吸感待机；发文字后再切说话视频";
  }
}

/** @deprecated 兼容旧名：待机改用微动循环 */
function showStill() {
  showIdleLoop();
}

/**
 * 播放「说话」口型视频：有声、播一次，结束后柔和回到待机微动。
 */
function playSpeakVideo(url) {
  const video = $("previewVideo");
  const img = $("stillImage");
  if (!video || !url) {
    toast("没有生成说话视频", true);
    showIdleLoop();
    return;
  }

  state.stageMode = "speaking";
  state.playingReply = true;
  state.lastVideoUrl = url;
  setStageOverlay(false);
  setStageBadge("正在说话", "speak");
  if ($("phaseValue")) $("phaseValue").textContent = "数字人正在说";

  if (img) img.classList.add("hidden");
  clearVideoHandlers(video);
  stopIdleXfade();
  video.dataset.idleLoop = "";
  video.classList.remove("hidden");
  video.classList.remove("stage-soft");
  video.classList.add("stage-cut-in");
  video.loop = false;
  video.muted = !state.soundUnlocked;
  if (!state.soundUnlocked) $("btnUnmute")?.classList.remove("hidden");

  const bust = url + (url.includes("?") ? "&" : "?") + "t=" + Date.now();
  video.onended = () => {
    video.classList.remove("stage-cut-in");
    showIdleLoop();
    if ($("phaseValue") && state.live) $("phaseValue").textContent = "等待互动";
  };
  video.onerror = () => {
    video.classList.remove("stage-cut-in");
    showIdleLoop();
    toast("说话视频加载失败，已回待机", true);
  };
  video.onloadeddata = () => {
    setStageOverlay(false);
    // 短淡入，减少从微动切到说话的硬切感
    requestAnimationFrame(() => video.classList.add("stage-cut-in-on"));
    video.play().catch(() => {
      // 自动播放被拦：提示点开声，仍显示画面
      if ($("phaseReply")) $("phaseReply").textContent = "点击画面播放说话视频";
    });
  };
  video.src = bust;
  video.load();
}

/**
 * 合成等待：直播中绝对不能全屏「生成中」。
 * 继续播待机短循环，状态写在监视器外侧文案。
 */
function showSpeakingWait() {
  state.stageMode = "synthesizing";
  state.playingReply = false;
  setStageOverlay(false); // 关键：不遮挡人物
  // 继续微动待机，观众只看到正常出镜
  showIdleLoop();
  state.stageMode = "synthesizing"; // showIdleLoop 会改回 idle，再标回 synthesizing
  if ($("phaseValue")) $("phaseValue").textContent = "准备回复…";
  // 角标保持「待机/直播中」，不要「合成中」
  setStageBadge(state.live ? "直播中" : "准备中", "idle");
}

// —— 声音：男女声 + 音色列表 ——
async function loadVoiceCatalog() {
  try {
    const data = await api(`/api/v1/voice?runtime_mode=${encodeURIComponent(state.runtimeId || "cloud")}`);
    state.voiceCatalog = data;
    state.voiceId = data.voice_id || "";
    renderVoiceUI();
  } catch (e) {
    if ($("voiceList")) $("voiceList").innerHTML = `<p class="hint">音色加载失败：${e.message}</p>`;
  }
}

function renderVoiceUI() {
  const data = state.voiceCatalog;
  if (!data) return;
  const free = !!(data.free_tts || data.provider === "edge-free" || data.provider === "edge");
  state.freeTts = free;
  document.querySelectorAll("#ttsModeGroup .orient-btn").forEach((b) => {
    const on = b.dataset.free === "1";
    b.classList.toggle("active", free ? on : !on);
  });
  const modeHint = $("ttsModeHint");
  if (modeHint) {
    modeHint.textContent = free
      ? "当前：免费测试声音（微软），无需会员。之后有 MiniMax 再点右边切换。"
      : "当前：MiniMax 云端声音（需有效会员 Key）。想先免费用可切回「免费测试」。";
  }
  const cur = $("voiceCurrent");
  if (cur) {
    const g =
      data.voice_gender === "male" ? "男声" : data.voice_gender === "female" ? "女声" : "";
    const tag = free ? "（免费测试）" : data.has_minimax_key ? "" : "（未配 MiniMax Key）";
    cur.textContent = `已选：${data.voice_name || data.voice_id}${g ? " · " + g : ""}${tag}`;
  }
  const hint = $("voiceHint");
  if (hint && data.hint) hint.textContent = data.hint;
  document.querySelectorAll("#genderGroup .orient-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.gender === state.voiceGender);
  });
  const list = $("voiceList");
  if (!list) return;
  let voices = data.voices || [];
  if (state.voiceGender === "male" || state.voiceGender === "female") {
    voices = voices.filter((v) => v.gender === state.voiceGender);
  }
  if (!voices.length) {
    list.innerHTML = `<p class="hint">该分类下暂无音色</p>`;
    return;
  }
  list.innerHTML = voices
    .map((v) => {
      const selected = v.id === state.voiceId ? "selected" : "";
      const g = v.gender === "male" ? "男" : v.gender === "female" ? "女" : "";
      const tags = (v.tags || []).map((t) => `<span class="vc-tag">${t}</span>`).join("");
      return `<div class="voice-card ${selected}" data-voice-id="${escapeAttr(v.id)}">
        <div>
          <div class="vc-name">${escapeAttr(v.name)} ${g ? "· " + g : ""}</div>
          <div class="vc-meta">${escapeAttr(v.desc || v.id)}</div>
          <div class="vc-tags">${tags}</div>
        </div>
        <div class="vc-actions">
          <button type="button" class="btn primary sm vc-select" data-voice-id="${escapeAttr(v.id)}">选用</button>
          <button type="button" class="btn ghost sm vc-preview" data-voice-id="${escapeAttr(v.id)}">试听</button>
        </div>
      </div>`;
    })
    .join("");

  list.querySelectorAll(".voice-card").forEach((card) => {
    card.addEventListener("click", (e) => {
      if (e.target.closest("button")) return;
      selectVoice(card.dataset.voiceId);
    });
  });
  list.querySelectorAll(".vc-select").forEach((b) => {
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      selectVoice(b.dataset.voiceId);
    });
  });
  list.querySelectorAll(".vc-preview").forEach((b) => {
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      previewVoice(b.dataset.voiceId);
    });
  });
}

async function setFreeTts(on) {
  try {
    await api("/api/v1/settings", {
      method: "PUT",
      body: JSON.stringify({ values: { USE_FREE_TTS: on ? "1" : "0" } }),
    });
    state.freeTts = !!on;
    if (state.keys) state.keys.free_tts = !!on;
    toast(on ? "已开启免费测试声音" : "已切换为 MiniMax（需有效 Key）");
    renderKeyStatus();
    await loadVoiceCatalog();
  } catch (e) {
    toast(e.message, true);
  }
}

async function selectVoice(voiceId) {
  if (!voiceId) return;
  try {
    const res = await api("/api/v1/voice/select", {
      method: "POST",
      body: JSON.stringify({ voice_id: voiceId }),
    });
    state.voiceId = res.voice_id;
    if (state.voiceCatalog) {
      state.voiceCatalog.voice_id = res.voice_id;
      state.voiceCatalog.voice_name = res.voice_name;
      state.voiceCatalog.voice_gender = res.voice_gender;
    }
    renderVoiceUI();
    toast(res.message || "音色已保存");
  } catch (e) {
    toast(e.message, true);
  }
}

async function previewVoice(voiceId) {
  const text = ($("voicePreviewText")?.value || "").trim() || "大家好，欢迎来到直播间。";
  const audio = $("voicePreviewAudio");
  try {
    toast("正在合成试听…");
    const res = await api("/api/v1/voice/preview", {
      method: "POST",
      body: JSON.stringify({ text, voice_id: voiceId, mock: false }),
    });
    if (audio && res.url) {
      audio.classList.remove("hidden");
      audio.src = res.url + (res.url.includes("?") ? "&" : "?") + "t=" + Date.now();
      audio.play().catch(() => {});
    }
    toast(
      res.demo
        ? `试听 ${res.voice_name || voiceId}（演示音，请配 MiniMax Key）`
        : `试听：${res.voice_name || voiceId}`
    );
  } catch (e) {
    toast(e.message, true);
  }
}

// —— 横竖屏 / 完整显示 ——
function applyStageLayout() {
  const frame = $("stageFrame");
  if (!frame) return;
  const orient = state.orientation || "portrait";
  const fit = state.fit || "contain";
  frame.classList.remove("aspect-portrait", "aspect-landscape", "aspect-square", "fit-contain", "fit-cover");
  frame.classList.add(
    orient === "landscape" ? "aspect-landscape" : orient === "square" ? "aspect-square" : "aspect-portrait"
  );
  frame.classList.add(fit === "cover" ? "fit-cover" : "fit-contain");

  document.querySelectorAll("#orientGroup .orient-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.orient === orient);
  });
  document.querySelectorAll("#fitGroup .orient-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.fit === fit);
  });
  const labels = { portrait: "竖屏 9:16", landscape: "横屏 16:9", square: "方形 1:1" };
  const fitLabel = fit === "cover" ? "铺满裁剪" : "完整显示";
  if ($("orientHint")) $("orientHint").textContent = `${labels[orient] || orient} · ${fitLabel}`;
}

function setOrientation(orient) {
  state.orientation = orient || "portrait";
  localStorage.setItem("dh_orientation", state.orientation);
  applyStageLayout();
  toast(
    state.orientation === "portrait"
      ? "已切竖屏（抖音常用），人物完整显示"
      : state.orientation === "landscape"
        ? "已切横屏 16:9"
        : "已切方形 1:1"
  );
}

function setFit(fit) {
  state.fit = fit === "cover" ? "cover" : "contain";
  localStorage.setItem("dh_fit", state.fit);
  applyStageLayout();
  toast(state.fit === "contain" ? "完整显示人物（可有黑边）" : "铺满画面（可能裁切）");
}

// —— 就绪状态 ——
function renderReadyPills() {
  const box = $("readyPills");
  if (!box) return;
  const k = state.keys || {};
  const items = [
    { ok: !!k.avatar_ready, label: "形象" },
    { ok: !!k.ffmpeg, label: "FFmpeg" },
    { ok: !!k.deepseek, label: "对话" },
    { ok: !!k.minimax, label: "声音" },
  ];
  box.innerHTML = items
    .map(
      (i) =>
        `<span class="rpill ${i.ok ? "ok" : "no"}" title="${i.label}">${i.ok ? "✓" : "·"} ${i.label}</span>`
    )
    .join("");
}

async function loadIdlePreview() {
  try {
    const q = new URLSearchParams({
      avatar_id: state.characterId || "demo",
      look_id: state.lookId || "default",
    });
    let assets = await api(`/api/v1/assets?${q}`);
    // 仅预览显示可回退；不改用户选型，避免「看起来选了礼服却播默认」
    const hasMedia =
      assets.source_url ||
      (assets.actions || []).some((a) => a.exists);
    if (!hasMedia && state.lookId && state.lookId !== "default") {
      const q2 = new URLSearchParams({
        avatar_id: state.characterId || "demo",
        look_id: "default",
      });
      assets = await api(`/api/v1/assets?${q2}`);
    }
    if (assets.source_url) state.stillImageUrl = assets.source_url;
    else state.stillImageUrl = null;
    const idle = (assets.actions || []).find((a) => a.name === "idle" && a.exists);
    const url = idle?.url || assets.actions?.find((a) => a.exists)?.url;
    state.idleVideoUrl = url || null;

    const lk = currentLook();
    if (lk && !lk.ready) {
      setStageOverlay(true, `造型「${lk.name}」还没生成微动，请到「素材」生成后再开播`);
      if ($("phaseValue") && !state.live) $("phaseValue").textContent = "造型未就绪";
      if ($("phaseReply") && !state.live) {
        $("phaseReply").textContent = "可先看看默认图预览；开播必须用已生成的造型";
      }
      return;
    }

    if (state.idleVideoUrl || state.stillImageUrl) {
      if (!state.live) showIdleLoop();
      if ($("phaseValue") && !state.live) $("phaseValue").textContent = "待机 · 慢呼吸";
      if ($("phaseReply") && !state.live) {
        $("phaseReply").textContent =
          "慢而小的呼吸感待机；发文字后再切说话视频";
      }
    } else {
      setStageOverlay(true, "请到「素材」新建角色、上传造型图并生成微动");
    }
  } catch (e) {
    setStageOverlay(true, "加载素材失败：" + e.message);
  }
}

async function loadCharacters() {
  try {
    const data = await api("/api/v1/characters");
    state.characters = data.items || [];
    if (!state.characters.find((c) => c.id === state.characterId) && state.characters[0]) {
      state.characterId = state.characters[0].id;
      state.lookId = state.characters[0].default_look || "default";
      localStorage.setItem("dh_character_id", state.characterId);
      localStorage.setItem("dh_look_id", state.lookId);
    }
    // 当前造型若不存在，切到已就绪 / 默认造型；若用户明确停在未就绪造型则保留（开播时会拦）
    const cur = state.characters.find((c) => c.id === state.characterId);
    if (cur) {
      const looks = cur.looks || [];
      const picked = looks.find((l) => l.id === state.lookId);
      if (!picked) {
        const ready = looks.find((l) => l.ready) || looks.find((l) => l.id === "default") || looks[0];
        if (ready) {
          state.lookId = ready.id;
          localStorage.setItem("dh_look_id", state.lookId);
        }
      }
    }
    renderCharacterPick();
    renderLookPick();
  } catch (e) {
    console.warn("loadCharacters", e);
  }
}

function currentCharacter() {
  return (state.characters || []).find((c) => c.id === state.characterId) || null;
}

function currentLook() {
  const c = currentCharacter();
  if (!c) return null;
  return (c.looks || []).find((l) => l.id === state.lookId) || null;
}

function renderCharacterPick() {
  const grid = $("characterPick");
  const hint = $("characterHint");
  if (!grid) return;
  grid.innerHTML = "";
  (state.characters || []).forEach((c) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "runtime-chip" + (c.id === state.characterId ? " selected" : "");
    btn.textContent = `${c.ready ? "✓ " : ""}${c.name || c.id}`;
    btn.title = c.ready ? "可开播" : "请先到素材中心上传图并生成微动";
    btn.onclick = async () => {
      if (state.live) {
        toast("请先结束直播再切换角色", true);
        return;
      }
      state.characterId = c.id;
      const readyLook =
        (c.looks || []).find((l) => l.ready) ||
        (c.looks || []).find((l) => l.id === "default") ||
        (c.looks || [])[0];
      state.lookId = readyLook?.id || c.default_look || "default";
      localStorage.setItem("dh_character_id", state.characterId);
      localStorage.setItem("dh_look_id", state.lookId);
      renderCharacterPick();
      renderLookPick();
      await loadIdlePreview();
      toast(`已选用「${c.name}」`);
    };
    grid.appendChild(btn);
  });
  if (hint) {
    const cur = currentCharacter();
    hint.textContent = cur
      ? `当前：${cur.name}${cur.ready ? "（可开播）" : "（还需上传造型图并生成微动）"}`
      : "没有角色？去「素材」新建。";
  }
}

function renderLookPick() {
  const grid = $("lookPick");
  const hint = $("lookHint");
  if (!grid) return;
  grid.innerHTML = "";
  const cur = currentCharacter();
  const looks = cur?.looks || [{ id: "default", name: "默认造型", ready: false }];
  looks.forEach((lk) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "runtime-chip" + (lk.id === state.lookId ? " selected" : "");
    btn.textContent = `${lk.ready ? "✓ " : ""}${lk.name || lk.id}`;
    btn.title = lk.ready ? "可开播" : "请先到素材生成微动";
    btn.onclick = async () => {
      if (state.live) {
        toast("请先结束直播再切换造型", true);
        return;
      }
      state.lookId = lk.id;
      localStorage.setItem("dh_look_id", state.lookId);
      renderLookPick();
      await loadIdlePreview();
      toast(lk.ready ? `已选用造型「${lk.name}」` : `造型「${lk.name}」尚未生成，请去素材页`);
    };
    grid.appendChild(btn);
  });
  if (hint) {
    const lk = currentLook();
    hint.textContent = lk
      ? `造型：${lk.name}${lk.ready ? "（可开播）" : "（未生成微动）"}`
      : "请选择造型";
  }
}

// —— 平台 / 算力 UI ——
function selectPlatform(id, { silent } = {}) {
  state.platformId = id;
  renderPlatformPushGrid();
  renderPlatformGuide();
  refreshRtmpCard();
  updatePrimaryButton();
  if (!silent) {
    const p = currentPlatform();
    if (p) toast(`已选：${p.name}`);
  }
}

function renderPlatformPushGrid() {
  const grid = $("platformPushGrid");
  if (!grid) return;
  const keys = loadRtmpKeys();
  grid.innerHTML = "";
  (state.platforms || []).forEach((p) => {
    const hk = PLATFORM_HOTKEYS[p.id] || {};
    const preview = p.id === "preview" || p.dry_run;
    const saved = !!(keys[p.id] && String(keys[p.id]).trim());
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className =
      "push-card" +
      (preview ? " preview" : "") +
      (p.id === state.platformId ? " selected" : "");
    btn.innerHTML = `
      <div class="pc-top">
        <span class="pc-icon">${p.icon || "📺"}</span>
        <kbd class="pc-hk">${hk.label || ""}</kbd>
      </div>
      <div class="pc-name">${p.name}</div>
      <div class="pc-short">${
        preview ? "本机看画面" : saved ? "推流码已记" : "需推流码"
      }</div>
    `;
    btn.onclick = () => selectPlatform(p.id);
    grid.appendChild(btn);
  });
}

function renderPlatformGuide() {
  const p = currentPlatform();
  const box = $("platformGuide");
  if (!box) return;
  if (!p?.guide || isPreviewPlatform(p)) {
    box.classList.add("hidden");
    return;
  }
  const steps = (p.guide.steps || []).slice(0, 4).map((s) => `<li>${s}</li>`).join("");
  box.classList.remove("hidden");
  box.innerHTML = `<div class="guide-title">${p.guide.title || "如何拿推流码"}</div><ol>${steps}</ol>`;
}

function refreshRtmpCard() {
  const p = currentPlatform();
  const preview = isPreviewPlatform(p);
  const opt = $("rtmpOptional");
  if (opt) opt.textContent = preview ? "（预览可跳过）" : "（必填）";
  if ($("keyLabel")) $("keyLabel").textContent = p?.key_label || "推流码";
  if ($("rtmpUrl") && p?.rtmp_url) $("rtmpUrl").value = p.rtmp_url;
  if ($("rtmpKey") && !preview) {
    const saved = getRtmpKey(p.id);
    if (saved) $("rtmpKey").value = saved;
  }
  if ($("rtmpKey") && preview) {
    // keep value for other platforms in localStorage only
  }
  updateSavedKeyHint();
  $("rtmpCard")?.classList.toggle("dim", !!preview);
}

function updateSavedKeyHint() {
  const el = $("savedKeyHint");
  if (!el) return;
  const p = currentPlatform();
  if (isPreviewPlatform(p)) {
    el.textContent = "预览模式不推流，无需推流码。";
    return;
  }
  const saved = getRtmpKey(p.id);
  el.textContent = saved
    ? `已记住「${p.name}」推流码，可直接开播或按 ${PLATFORM_HOTKEYS[p.id]?.label || "Alt+S"}`
    : `从${p.name}直播伴侣复制推流码粘贴；开播后会自动记住。`;
}

function renderRuntimes() {
  const grid = $("runtimeGrid");
  if (!grid) return;
  grid.innerHTML = "";
  (state.runtimes || []).forEach((r) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "runtime-chip" + (r.id === state.runtimeId ? " selected" : "");
    btn.textContent = `${r.icon || ""} ${r.name}`.trim();
    btn.title = r.short || r.description || "";
    btn.onclick = () => {
      state.runtimeId = r.id;
      renderRuntimes();
      renderKeyStatus();
      updatePrimaryButton();
      loadVoiceCatalog();
    };
    grid.appendChild(btn);
  });
}

function renderKeyStatus() {
  const k = state.keys || {};
  const el = $("keyStatus");
  if (!el) return;
  const mode = state.runtimeId;
  const free = k.free_tts !== false; // 默认视为免费开
  const i2v = k.video_i2v ? "✓图生视频" : "⚠需配图生视频";
  let line = "";
  if (mode === "local") {
    line = `本地：Ollama ${k.ollama_online ? "在线" : "未检测"} · ${i2v}`;
  } else if (free) {
    line = `${i2v} · 对话 ${k.deepseek ? "✓" : "演示"} · 声音 免费测试`;
  } else {
    line = `${i2v} · 对话 ${k.deepseek ? "✓" : "演示"} · 声音 ${k.minimax ? "✓ MiniMax" : "需配 Key"}`;
  }
  el.innerHTML = `<div>${line}</div>`;
  const btn = $("btnOpenSettings");
  if (btn) {
    btn.classList.toggle("primary", !k.video_i2v);
    btn.classList.toggle("ghost", !!k.video_i2v);
    btn.textContent = k.video_i2v ? "配置" : "配置图生视频";
  }
}

// —— 开播前检查 ——
const PF_ICONS = { ok: "✅", warn: "⚠️", block: "❌" };

function renderPreflight(data) {
  const summary = $("preflightSummary");
  const list = $("preflightList");
  if (!summary || !list) return;
  const checks = Array.isArray(data?.checks) ? data.checks : [];
  const blocked = (data?.block_count ?? 0) > 0;
  const warned = (data?.warn_count ?? 0) > 0;
  summary.classList.remove("hidden", "ok", "warn", "block");
  summary.classList.add(blocked ? "block" : warned ? "warn" : "ok");
  summary.textContent = data?.summary || (blocked ? "请先处理阻断项" : "可以开播");
  list.innerHTML = "";
  checks.forEach((c) => {
    const level = PF_ICONS[c.level] ? c.level : c.ok ? "ok" : "block";
    const item = document.createElement("div");
    item.className = `pf-item ${level}`;
    const head = document.createElement("div");
    head.className = "pf-head";
    head.textContent = `${PF_ICONS[level] || "❔"} ${c.label || c.id || ""}`;
    item.appendChild(head);
    if (c.message) {
      const msg = document.createElement("div");
      msg.className = "pf-msg";
      msg.textContent = c.message;
      item.appendChild(msg);
    }
    if (c.fix) {
      const fix = document.createElement("div");
      fix.className = "pf-fix";
      fix.textContent =
        c.fix === "/materials"
          ? "👉 去「素材」页处理"
          : c.fix === "settings"
            ? "👉 去顶栏「配置」处理"
            : c.fix === "step2"
              ? "👉 在上方「推流码」处填写"
              : `👉 ${c.fix}`;
      item.appendChild(fix);
    }
    list.appendChild(item);
  });
}

async function runPreflight() {
  const btn = $("btnPreflight");
  const summary = $("preflightSummary");
  if (btn) btn.disabled = true;
  if (summary) {
    summary.classList.remove("hidden", "ok", "warn", "block");
    summary.textContent = "检查中…";
  }
  try {
    const platform = state.platformId || "preview";
    const preview = isPreviewPlatform();
    const data = await api("/api/v1/live/preflight", {
      method: "POST",
      body: JSON.stringify({
        platform,
        runtime_mode: state.runtimeId || "cloud",
        rtmp_key: preview ? null : ($("rtmpKey")?.value || "").trim() || getRtmpKey(platform) || null,
        avatar_id: state.characterId || "demo",
        look_id: state.lookId || "default",
      }),
    });
    renderPreflight(data);
    return data;
  } catch (e) {
    if (summary) summary.textContent = `检查失败：${e.message || e}`;
    toast(e.message || String(e), true);
    return null;
  } finally {
    if (btn) btn.disabled = false;
  }
}

function updatePrimaryButton() {
  const btn = $("btnPrimaryGo");
  const stop = $("btnStop");
  if (!btn) return;
  if (state.live) {
    btn.classList.add("hidden");
    stop?.classList.remove("hidden");
    $("chatPanel")?.classList.add("live");
    document.querySelector('.tab[data-tab="chat"]')?.classList.add("live-dot");
    return;
  }
  btn.classList.remove("hidden");
  stop?.classList.add("hidden");
  $("chatPanel")?.classList.remove("live");
  document.querySelector('.tab[data-tab="chat"]')?.classList.remove("live-dot");
  const p = currentPlatform();
  const preview = isPreviewPlatform(p);
  btn.textContent = preview
    ? "🚀 开始预览（本机看数字人）"
    : `📡 推流开播 · ${p?.name || ""}`;
  btn.disabled = !!state.starting;
  const hint = $("goHint");
  if (hint) {
    hint.textContent = preview
      ? "预览：画面 + 口型回复都在左侧。真播请选抖音等并填推流码。"
      : `将推到「${p?.name}」。请确认直播伴侣已开、推流码有效。`;
  }
}

// —— 开播 / 关播 ——
async function startLiveSession(opts = {}) {
  if (state.live) {
    toast("已在直播中，先结束再切换平台");
    return null;
  }
  if (state.starting) return null;
  state.starting = true;
  updatePrimaryButton();

  const platform = opts.platform || state.platformId || "preview";
  const runtime = opts.runtime || state.runtimeId || "cloud";
  const p = state.platforms.find((x) => x.id === platform) || { id: platform, name: platform };
  const preview = platform === "preview" || p.dry_run;

  let rtmp_key = opts.rtmp_key;
  if (rtmp_key === undefined) rtmp_key = getRtmpKey(platform);
  let rtmp_url = opts.rtmp_url;
  if (rtmp_url === undefined) {
    rtmp_url = ($("rtmpUrl")?.value || "").trim() || p.rtmp_url || null;
  }

  try {
    if (!preview && !(rtmp_key || "").trim()) {
      selectPlatform(platform, { silent: true });
      $("rtmpKey")?.focus();
      toast(`请先粘贴「${p.name || platform}」推流码`, true);
      return null;
    }

    const lk = currentLook();
    const char = currentCharacter();
    if (lk && !lk.ready) {
      toast(`造型「${lk.name || state.lookId}」还没生成微动，请先去「素材」生成`, true);
      switchTab("go");
      await runPreflight();
      return null;
    }
    if (char && !char.ready && !lk?.ready) {
      toast(`角色「${char.name}」还不能开播，请先到素材上传图并生成微动`, true);
      switchTab("go");
      await runPreflight();
      return null;
    }

    setStageOverlay(true, "准备开播…");
    try {
      await api("/api/v1/demo/ensure", { method: "POST", body: "{}" });
    } catch {}

    try {
      if (state.personaId) {
        await api(`/api/v1/personas/${state.personaId}`, {
          method: "PUT",
          body: JSON.stringify({
            name: $("personaName")?.value || "",
            greeting: $("personaGreeting")?.value || "",
            system_prompt: $("personaPrompt")?.value || "",
          }),
        });
      }
    } catch {}

    const data = await api("/api/v1/live/start", {
      method: "POST",
      body: JSON.stringify({
        room_id: state.roomId || "demo",
        mode: "interactive",
        platform,
        runtime_mode: runtime,
        rtmp_url: preview ? null : rtmp_url,
        rtmp_key: preview ? null : (rtmp_key || "").trim(),
        avatar_id: state.characterId || "demo",
        look_id: state.lookId || "default",
        // 与预览窗一致：竖屏/横屏 + 完整显示，成片同样 letterbox
        orientation: state.orientation || "portrait",
        fit: state.fit || "contain",
      }),
    });

    state.platformId = platform;
    state.runtimeId = runtime;
    state.live = true;
    if (!preview && (rtmp_key || "").trim()) {
      saveRtmpKey(platform, rtmp_key);
      if ($("rtmpKey")) $("rtmpKey").value = rtmp_key;
    }

    $("livePill").textContent = preview ? "预览中" : "直播中";
    $("livePill").classList.add("on");
    $("livePill").classList.remove("off");

    if (data.portrait_url) state.stillImageUrl = data.portrait_url;
    if (data.idle_video_url) state.idleVideoUrl = data.idle_video_url;
    // 开播后：微动待机循环；合成时不遮罩；有回复再切说话视频
    showIdleLoop();

    $("phaseValue").textContent = preview ? "预览中 · 待机" : `直播中 · ${p.name}`;
    $("phaseReply").textContent = preview
      ? "待机微动循环；发文字后开口说（合成时画面不打断）"
      : `已向「${p.name}」推流。待机微动，有话术再说话`;

    connectWs();
    updatePrimaryButton();
    renderPlatformPushGrid();
    // 开播后自动切到「互动」页，减少滚动与找入口
    switchTab("chat");
    toast(data.message || (preview ? "预览已开始：先静止，说话才动" : `已推流到${p.name}`));

    // 开场白由服务端队列触发；前端只等 ai_response 播说话视频，不再循环 idle
    return data;
  } catch (e) {
    setStageOverlay(false);
    toast(`${e.message || String(e)}（已打开「开播前检查」）`, true);
    // 开播失败多来自 preflight 阻断：自动展开检查面板，标出要处理的项目
    switchTab("go");
    runPreflight();
    throw e;
  } finally {
    state.starting = false;
    updatePrimaryButton();
  }
}

async function stopLiveSession() {
  try {
    await api(`/api/v1/live/stop?room_id=${encodeURIComponent(state.roomId || "demo")}`, {
      method: "POST",
    });
  } catch (e) {
    toast(e.message, true);
  }
  if (state.ws) {
    try {
      state.ws.close();
    } catch {}
    state.ws = null;
  }
  state.live = false;
  state.playingReply = false;
  $("livePill").textContent = "未开播";
  $("livePill").classList.remove("on");
  $("livePill").classList.add("off");
  $("phaseValue").textContent = "已结束";
  $("phaseReply").textContent = "可再次点「开始预览」或选择平台推流";
  updatePrimaryButton();
  showIdleLoop();
  switchTab("go");
  toast("已结束");
}

async function quickGoLive(platformId) {
  selectPlatform(platformId, { silent: true });
  try {
    await startLiveSession({
      platform: platformId,
      runtime: state.runtimeId,
      autoHello: platformId === "preview",
    });
  } catch {
    /* toast 已处理 */
  }
}

// —— WebSocket / 互动 ——
function connectWs() {
  if (state.ws) {
    try {
      state.ws.close();
    } catch {}
  }
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/live/${state.roomId}`);
  state.ws = ws;
  ws.onmessage = (ev) => {
    let data;
    try {
      data = JSON.parse(ev.data);
    } catch {
      return;
    }
    logEvent(data);
    if (data.portrait_url) state.stillImageUrl = data.portrait_url;
    if (data.idle_video_url) state.idleVideoUrl = data.idle_video_url;

    if (data.type === "status") {
      const labels = {
        idle: "待机中",
        reading: "收到文字",
        thinking: "准备回复…",
        speaking: "准备开口…",
        stopped: "未开播",
      };
      if ($("phaseValue") && !state.playingReply) {
        $("phaseValue").textContent = labels[data.phase] || data.phase || "—";
      }
      // 思考/合成：继续待机微动，不遮挡画面
      if (data.phase === "thinking" || data.phase === "reading" || data.phase === "speaking") {
        if (!state.playingReply) showSpeakingWait();
      }
      // 回到 idle：没在说话则回微动循环
      if (data.phase === "idle" && !state.playingReply) {
        showIdleLoop();
      }
    }
    if (data.type === "ai_response") {
      if ($("phaseReply")) $("phaseReply").textContent = data.text || "";
      const vurl = data.video_url || data.last_video_url;
      if (vurl) {
        unlockSound();
        playSpeakVideo(vurl);
      } else {
        toast("有文字但无口型视频，请检查 MiniMax/口型", true);
        showIdleLoop();
      }
    }
    if (data.type === "error") toast(data.message || "出错了", true);
  };
}

async function sendText(text, extra = {}) {
  if (!text) return;
  if (!state.live) {
    toast("请先点「开始预览」或推流开播", true);
    return;
  }
  unlockSound();
  showSpeakingWait();
  try {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(
        JSON.stringify({
          type: "text",
          content: text,
          user_key: "web",
          priority: extra.priority || 10,
          is_gift: !!extra.is_gift,
        })
      );
    } else {
      await api(`/api/v1/live/${state.roomId}/input`, {
        method: "POST",
        body: JSON.stringify({
          text,
          user_key: "web",
          priority: extra.priority || 10,
          is_gift: !!extra.is_gift,
        }),
      });
    }
  } catch (e) {
    toast(e.message, true);
    setStageOverlay(false);
  }
}

// —— 设置抽屉 ——
function openSettings() {
  $("settingsOverlay")?.classList.remove("hidden");
  loadSettingsForm();
}
function closeSettings() {
  $("settingsOverlay")?.classList.add("hidden");
}
function openHotkeyHelp() {
  $("hotkeyOverlay")?.classList.remove("hidden");
}
function closeHotkeyHelp() {
  $("hotkeyOverlay")?.classList.add("hidden");
}

function escapeAttr(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;");
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
        return `<section class="settings-group${pri}" data-group="${g.id || ""}"><h3>${g.label}</h3>${fields}</section>`;
      })
      .join("");
    body.querySelectorAll(".toggle-pw").forEach((btn) => {
      btn.onclick = () => {
        const input = btn.parentElement.querySelector("input");
        input.type = input.type === "password" ? "text" : "password";
        btn.textContent = input.type === "password" ? "显示" : "隐藏";
      };
    });
    body.querySelector(".settings-group-priority")?.scrollIntoView({ block: "nearest" });
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

async function testTarget(target) {
  try {
    await api("/api/v1/settings", {
      method: "PUT",
      body: JSON.stringify({ values: collectSettingsValues() }),
    });
    const res = await api("/api/v1/settings/test", {
      method: "POST",
      body: JSON.stringify({ target }),
    });
    toast(res.message || "通过");
    await loadBootstrap();
  } catch (e) {
    toast(e.message, true);
  }
}

function pfRow(level, head, msg) {
  const item = document.createElement("div");
  item.className = `pf-item ${level}`;
  const h = document.createElement("div");
  h.className = "pf-head";
  h.textContent = `${PF_ICONS[level] || "❔"} ${head}`;
  item.appendChild(h);
  if (msg) {
    const m = document.createElement("div");
    m.className = "pf-msg";
    m.textContent = msg;
    item.appendChild(m);
  }
  return item;
}

function renderPromoPanel(promo) {
  const block = $("promoBlock");
  if (!block) return;
  if (!promo || !promo.available) {
    block.classList.add("hidden");
    return;
  }
  block.classList.remove("hidden");
  const kb = promo.knowledge || {};
  const ps = promo.promo_script || {};
  const layoutText =
    { split: "左网站 · 右数字人", website_only: "仅网站画面", avatar_only: "仅人物" }[
      promo.layout
    ] || promo.layout;

  const box = $("promoStatus");
  box.innerHTML = "";
  box.appendChild(
    pfRow(
      promo.enabled ? "ok" : "warn",
      promo.enabled ? "宣讲模式已开启" : "宣讲模式未开启",
      promo.message || ""
    )
  );
  box.appendChild(
    pfRow(
      promo.enabled ? "ok" : "warn",
      `画面布局：${layoutText}`,
      promo.website_url || "未配置官网地址"
    )
  );
  box.appendChild(
    pfRow(
      kb.chunks ? "ok" : "warn",
      `知识库：${kb.chunks || 0} 段`,
      (kb.files || []).length
        ? `${kb.files.length} 个文件：${kb.files.join("、")}`
        : "还没有放 .md / .txt 文件，数字人只能凭内置话术回答"
    )
  );
  box.appendChild(
    pfRow(
      ps.lines ? "ok" : "warn",
      `闲时宣讲：${ps.lines || 0} 条`,
      ps.lines
        ? `没人提问超过 ${promo.idle_seconds || 45} 秒，自动播一条`
        : "没有宣讲稿，闲时不会自动讲话"
    )
  );

  $("promoHint").textContent = promo.enabled
    ? "开播时房间选 promo。下面可以先试一个观众可能会问的问题，确认它答得上。"
    : "当前房间没开宣讲模式，普通直播不受影响。";
}

async function testPromoQuery() {
  const out = $("promoTestResult");
  const q = ($("promoQuery")?.value || "").trim();
  if (!q) {
    out.innerHTML = "";
    out.appendChild(pfRow("warn", "先写个问题", "比如「贵不贵」「多久出片」「支持苹果吗」"));
    return;
  }
  try {
    const r = await api("/api/v1/promo/test", {
      method: "POST",
      body: JSON.stringify({ query: q }),
    });
    out.innerHTML = "";
    if (r.hit) {
      const first = r.chunks[0] || {};
      out.appendChild(
        pfRow(
          "ok",
          `答得上：命中 ${r.count} 段`,
          `${first.heading || first.source || ""}｜${(first.text || "").slice(0, 100)}`
        )
      );
    } else {
      out.appendChild(pfRow("warn", "答不上：知识库里没有", r.hint || ""));
    }
  } catch (e) {
    out.innerHTML = "";
    out.appendChild(pfRow("block", "试一下失败", e.message || String(e)));
  }
}

// —— 数据加载 ——
async function loadBootstrap() {
  const data = await api("/api/v1/bootstrap");
  state.platforms = data.platforms || [];
  state.runtimes = data.runtime_modes || [];
  state.keys = data.keys || {};
  state.platformId = state.platformId || data.defaults?.platform || "preview";
  state.runtimeId = state.runtimeId || data.defaults?.runtime_mode || "cloud";
  state.roomId = data.defaults?.room_id || "demo";
  renderPlatformPushGrid();
  renderRuntimes();
  renderKeyStatus();
  renderReadyPills();
  renderPromoPanel(data.promo);
  refreshRtmpCard();
  updatePrimaryButton();
}

async function loadPersona() {
  try {
    const list = await api("/api/v1/personas");
    if (!list.length) return;
    const p = list[0];
    state.personaId = p.id;
    if ($("personaName")) $("personaName").value = p.name || "";
    if ($("personaGreeting")) $("personaGreeting").value = p.greeting || "";
    if ($("personaPrompt")) $("personaPrompt").value = p.system_prompt || "";
  } catch {}
}

async function refreshStatus() {
  try {
    const s = await api(`/api/v1/live/${state.roomId}/status`);
    if (s.running) {
      state.live = true;
      if (s.portrait_url) state.stillImageUrl = s.portrait_url;
      if (s.idle_video_url) state.idleVideoUrl = s.idle_video_url;
      if (s.last_video_url) state.lastVideoUrl = s.last_video_url;
      $("livePill").textContent = s.engines?.dry_run ? "预览中" : "直播中";
      $("livePill").classList.add("on");
      $("livePill").classList.remove("off");
      $("phaseValue").textContent = s.phase_label || s.phase || "直播中";
      if (s.last_reply) $("phaseReply").textContent = s.last_reply;
      // 恢复时：说话中才播成片，否则待机微动
      if (s.phase === "speaking" && s.last_video_url) {
        playSpeakVideo(s.last_video_url);
      } else {
        showIdleLoop();
      }
      connectWs();
      updatePrimaryButton();
    }
  } catch {}
}

// —— 快捷键 ——
function installHotkeys() {
  document.addEventListener("keydown", (e) => {
    const tag = (e.target && e.target.tagName) || "";
    const typing = tag === "INPUT" || tag === "TEXTAREA" || e.target?.isContentEditable;

    // 非输入框：1–5 切换侧栏页签
    if (!typing && !e.altKey && !e.ctrlKey && !e.metaKey) {
      if (e.key >= "1" && e.key <= "5") {
        e.preventDefault();
        const name = TAB_ORDER[Number(e.key) - 1];
        if (name) {
          switchTab(name);
          if (name === "voice") loadVoiceCatalog();
        }
        return;
      }
    }

    if (!e.altKey || e.ctrlKey || e.metaKey) return;
    const k = e.key;
    const code = e.code;
    if (k === "/" || k === "?" || code === "Slash") {
      e.preventDefault();
      openHotkeyHelp();
      return;
    }
    if (k === "q" || k === "Q") {
      e.preventDefault();
      if (state.live) stopLiveSession();
      else toast("当前未开播");
      return;
    }
    if (k === "s" || k === "S") {
      e.preventDefault();
      startLiveSession({
        platform: state.platformId,
        runtime: state.runtimeId,
        rtmp_key: ($("rtmpKey")?.value || "").trim() || getRtmpKey(state.platformId),
        rtmp_url: ($("rtmpUrl")?.value || "").trim() || null,
        autoHello: state.platformId === "preview",
      }).catch(() => {});
      return;
    }
    const digit =
      k >= "0" && k <= "5"
        ? k
        : code.startsWith("Digit")
          ? code.replace("Digit", "")
          : code.startsWith("Numpad")
            ? code.replace("Numpad", "")
            : null;
    if (digit !== null && digit >= "0" && digit <= "5") {
      e.preventDefault();
      const entry = Object.entries(PLATFORM_HOTKEYS).find(([, v]) => v.key === digit);
      if (entry) quickGoLive(entry[0]);
    }
  });
}

// —— 事件绑定 ——
function bindEvents() {
  document.querySelectorAll(".tab").forEach((t) => {
    t.addEventListener("click", () => {
      switchTab(t.dataset.tab);
      if (t.dataset.tab === "voice") loadVoiceCatalog();
    });
  });
  document.querySelectorAll("#genderGroup .orient-btn").forEach((b) => {
    b.addEventListener("click", () => {
      state.voiceGender = b.dataset.gender || "all";
      renderVoiceUI();
    });
  });
  document.querySelectorAll("#orientGroup .orient-btn").forEach((b) => {
    b.addEventListener("click", () => setOrientation(b.dataset.orient));
  });
  document.querySelectorAll("#fitGroup .orient-btn").forEach((b) => {
    b.addEventListener("click", () => setFit(b.dataset.fit));
  });

  $("btnPrimaryGo")?.addEventListener("click", () => {
    startLiveSession({
      platform: state.platformId,
      runtime: state.runtimeId,
      rtmp_key: ($("rtmpKey")?.value || "").trim() || getRtmpKey(state.platformId),
      rtmp_url: ($("rtmpUrl")?.value || "").trim() || null,
      autoHello: isPreviewPlatform(),
    }).catch(() => {});
  });
  $("btnStop")?.addEventListener("click", () => stopLiveSession());
  $("btnPreflight")?.addEventListener("click", () => runPreflight());
  $("btnSaveRtmpKey")?.addEventListener("click", () => {
    const p = currentPlatform();
    if (isPreviewPlatform(p)) {
      toast("预览无需推流码");
      return;
    }
    const key = ($("rtmpKey")?.value || "").trim();
    if (!key) {
      toast("请先粘贴推流码", true);
      return;
    }
    saveRtmpKey(p.id, key);
    renderPlatformPushGrid();
    updateSavedKeyHint();
    toast(`已记住「${p.name}」推流码`);
  });
  $("rtmpKey")?.addEventListener("input", updateSavedKeyHint);

  $("btnSend")?.addEventListener("click", async () => {
    const text = $("inputText")?.value?.trim();
    if (!text) return;
    await sendText(text);
    if ($("inputText")) $("inputText").value = "";
  });
  $("inputText")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("btnSend")?.click();
  });
  document.querySelectorAll(".chip").forEach((el) => {
    if (el.id === "btnInterrupt") return;
    el.addEventListener("click", () => {
      const gift = el.dataset.gift === "1";
      sendText(el.dataset.text || el.textContent, {
        is_gift: gift,
        priority: gift ? 80 : 10,
      });
    });
  });
  $("btnInterrupt")?.addEventListener("click", () => {
    if (state.ws?.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify({ type: "interrupt" }));
      toast("已打断");
    }
  });

  $("btnSavePersona")?.addEventListener("click", async () => {
    try {
      await api(`/api/v1/personas/${state.personaId}`, {
        method: "PUT",
        body: JSON.stringify({
          name: $("personaName").value,
          greeting: $("personaGreeting").value,
          system_prompt: $("personaPrompt").value,
        }),
      });
      toast("人设已保存");
    } catch (e) {
      toast(e.message, true);
    }
  });
  $("btnChatTest")?.addEventListener("click", async () => {
    const out = $("chatTestOut");
    if (out) {
      out.classList.remove("hidden");
      out.textContent = "请求中…";
    }
    try {
      const data = await api("/api/v1/chat/test", {
        method: "POST",
        body: JSON.stringify({
          text: "你好呀，介绍一下你自己",
          system_prompt: $("personaPrompt")?.value || null,
        }),
      });
      if (out) out.textContent = `【${data.provider}${data.demo ? "·演示" : ""}】${data.reply}`;
      toast("试聊完成（仅文字，不推流）");
    } catch (e) {
      if (out) out.textContent = "失败：" + e.message;
      toast(e.message, true);
    }
  });

  $("btnOpenSettings")?.addEventListener("click", openSettings);
  $("btnCloseSettings")?.addEventListener("click", closeSettings);
  $("settingsOverlay")?.addEventListener("click", (e) => {
    if (e.target === $("settingsOverlay")) closeSettings();
  });
  $("btnHotkeyHelp")?.addEventListener("click", openHotkeyHelp);
  $("btnCloseHotkey")?.addEventListener("click", closeHotkeyHelp);
  $("hotkeyOverlay")?.addEventListener("click", (e) => {
    if (e.target === $("hotkeyOverlay")) closeHotkeyHelp();
  });
  $("btnSaveSettings")?.addEventListener("click", async () => {
    try {
      await api("/api/v1/settings", {
        method: "PUT",
        body: JSON.stringify({ values: collectSettingsValues() }),
      });
      toast("已保存");
      await loadBootstrap();
      await loadSettingsForm();
    } catch (e) {
      toast(e.message, true);
    }
  });
  $("btnTestDeepseek")?.addEventListener("click", () => testTarget("deepseek"));
  $("btnTestMinimax")?.addEventListener("click", () => testTarget("minimax"));
  $("btnTestOllama")?.addEventListener("click", () => testTarget("ollama"));

  $("btnFreeTtsOn")?.addEventListener("click", () => setFreeTts(true));
  $("btnFreeTtsOff")?.addEventListener("click", () => setFreeTts(false));
  $("btnPromoTest")?.addEventListener("click", testPromoQuery);
  $("promoQuery")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      testPromoQuery();
    }
  });

  $("btnUnmute")?.addEventListener("click", (e) => {
    e.stopPropagation();
    unlockSound();
    toast("已开启声音");
  });
  $("stageFrame")?.addEventListener("click", () => {
    unlockSound();
    // 仅在说话视频暂停时继续播；静止态不自动开循环
    const v = $("previewVideo");
    if (state.stageMode === "speaking" && v && !v.classList.contains("hidden") && v.paused) {
      v.play().catch(() => {});
    }
  });
}

// —— 启动 ——
(async () => {
  installHotkeys();
  bindEvents();
  switchTab(state.activeTab || "go", { persist: false });
  applyStageLayout();
  try {
    const login = await api("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ username: "admin", password: "admin" }),
    });
    state.token = login.token;
    localStorage.setItem("token", state.token);
  } catch {}
  try {
    await loadBootstrap();
    await loadCharacters();
    await loadPersona();
    await loadIdlePreview();
    await loadVoiceCatalog();
    await refreshStatus();
    applyStageLayout();
    if (!localStorage.getItem("dh_shell_v3")) {
      localStorage.setItem("dh_shell_v3", "1");
      toast("右侧有「声音」页：先选男/女声，再点音色选用/试听");
    }
  } catch (e) {
    toast("加载失败：" + e.message, true);
  }
})();
