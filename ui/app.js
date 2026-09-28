const STORY_API = "http://127.0.0.1:8002/api/v1";
const LORE_API = "http://127.0.0.1:8001/api/v1";

// In-memory UI State
let state = {
  characters: [],
  events: [],
  stories: [],
  selectedCharacterIds: new Set(),
  selectedRequiresIds: new Set(),
  selectedCreatesIds: new Set(),
  selectedParentEventIds: new Set(),
};

// DOM Elements
const elements = {
  tabs: document.querySelectorAll(".nav-item"),
  panes: document.querySelectorAll(".tab-pane"),
  pageTitle: document.getElementById("page-title"),
  pageSubtitle: document.getElementById("page-subtitle"),
  storiesGrid: document.getElementById("stories-grid"),
  filterSearch: document.getElementById("filter-search"),
  filterCharacter: document.getElementById("filter-character"),
  btnRefreshStories: document.getElementById("btn-refresh-stories"),
  btnQuickNewStory: document.getElementById("btn-quick-new-story"),

  // Editor
  storyTitle: document.getElementById("story-title"),
  storySummary: document.getElementById("story-summary"),
  storyContent: document.getElementById("story-content"),
  editorCharactersChips: document.getElementById("editor-characters-chips"),
  editorRequiresChips: document.getElementById("editor-requires-chips"),
  editorCreatesChips: document.getElementById("editor-creates-chips"),
  liveWarningBox: document.getElementById("live-warning-box"),
  warningList: document.getElementById("warning-list"),
  btnPrecheckCanon: document.getElementById("btn-precheck-canon"),
  btnSaveStory: document.getElementById("btn-save-story"),

  // Timeline
  timelineTrack: document.getElementById("timeline-track"),

  // Characters & Events
  charName: document.getElementById("char-name"),
  charType: document.getElementById("char-type"),
  charDesc: document.getElementById("char-desc"),
  btnCreateCharacter: document.getElementById("btn-create-character"),
  charactersList: document.getElementById("characters-list"),

  eventTitle: document.getElementById("event-title"),
  eventType: document.getElementById("event-type"),
  eventParentsChips: document.getElementById("event-parents-chips"),
  btnCreateEvent: document.getElementById("btn-create-event"),
  eventsList: document.getElementById("events-list"),

  // Modal
  storyModal: document.getElementById("story-modal"),
  modalTitle: document.getElementById("modal-story-title"),
  modalMeta: document.getElementById("modal-story-meta"),
  modalContent: document.getElementById("modal-story-content"),
  modalWarnings: document.getElementById("modal-warnings"),
  btnCloseModal: document.getElementById("btn-close-modal"),

  // Seed demo
  btnSeedData: document.getElementById("btn-seed-data"),
};

// Navigation tab switching
elements.tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    elements.tabs.forEach((t) => t.classList.remove("active"));
    elements.panes.forEach((p) => p.classList.remove("active"));

    tab.classList.add("active");
    const targetId = tab.dataset.tab;
    const targetPane = document.getElementById(targetId);
    if (targetPane) targetPane.classList.add("active");

    // Dynamic headers
    if (targetId === "tab-stories") {
      elements.pageTitle.textContent = "Библиотека текстов";
      elements.pageSubtitle.textContent = "Хронология и тексты с контролем причинно-следственных связей";
      loadStories();
    } else if (targetId === "tab-editor") {
      elements.pageTitle.textContent = "Редактор текста";
      elements.pageSubtitle.textContent = "Написание сцены с автоматической проверкой канона через Lore Service";
      renderEditorChips();
    } else if (targetId === "tab-timeline") {
      elements.pageTitle.textContent = "Граф и Таймлайн канона";
      elements.pageSubtitle.textContent = "Топологический порядок ключевых сюжетных вех";
      loadTimeline();
    } else if (targetId === "tab-characters") {
      elements.pageTitle.textContent = "Персонажи сеттинга";
      elements.pageSubtitle.textContent = "Управление спутниками, NPC и ключевыми лицами";
      loadCharacters();
    } else if (targetId === "tab-events") {
      elements.pageTitle.textContent = "Ключевые события мира";
      elements.pageSubtitle.textContent = "Дерево сюжетных точек и правила зависимостей";
      loadEvents();
    }
  });
});

elements.btnQuickNewStory.addEventListener("click", () => {
  const editorBtn = document.getElementById("btn-tab-editor");
  if (editorBtn) editorBtn.click();
});

// API Calls & Data Loaders
async function checkHealth() {
  try {
    await fetch("http://127.0.0.1:8000/health");
  } catch (e) {
    document.querySelector("#status-story .dot")?.classList.remove("online");
  }
  try {
    await fetch("http://127.0.0.1:8001/health");
  } catch (e) {
    document.querySelector("#status-lore .dot")?.classList.remove("online");
  }
}

async function loadCharacters() {
  try {
    const res = await fetch(`${LORE_API}/characters?page[size]=100`);
    if (!res.ok) return;
    const data = await res.json();
    state.characters = data.data || [];
    renderCharactersList();
    populateCharacterFilter();
    renderEditorChips();
  } catch (err) {
    console.error("Error loading characters:", err);
  }
}

async function loadEvents() {
  try {
    const res = await fetch(`${LORE_API}/world-events?page[size]=100`);
    if (!res.ok) return;
    const data = await res.json();
    state.events = data.data || [];
    renderEventsList();
    renderEditorChips();
    renderEventParentChips();
  } catch (err) {
    console.error("Error loading events:", err);
  }
}

async function loadStories() {
  try {
    let url = `${STORY_API}/stories?page[size]=50`;
    const search = elements.filterSearch.value.trim();
    const charId = elements.filterCharacter.value;

    if (search) url += `&filter[q]=${encodeURIComponent(search)}`;
    if (charId) url += `&filter[character_id]=${charId}`;

    const res = await fetch(url);
    if (!res.ok) return;
    const data = await res.json();
    state.stories = data.data || [];
    renderStoriesGrid();
  } catch (err) {
    elements.storiesGrid.innerHTML = `<div class="empty-state">Ошибка подключения к Story Service. Убедитесь, что сервер запущен на порту 8000.</div>`;
  }
}

async function loadTimeline() {
  try {
    const res = await fetch(`${LORE_API}/timeline`);
    if (!res.ok) return;
    const events = await res.json();
    renderTimeline(events);
  } catch (err) {
    console.error("Error loading timeline:", err);
  }
}

// Rendering UI Lists
function renderStoriesGrid() {
  if (state.stories.length === 0) {
    elements.storiesGrid.innerHTML = `<div class="empty-state">Пока нет созданных текстов. Нажмите "Новый Текст", чтобы добавить первую историю с проверкой канона!</div>`;
    return;
  }

  elements.storiesGrid.innerHTML = state.stories
    .map((s) => {
      const charBadges = (s.character_ids || [])
        .map((cid) => {
          const char = state.characters.find((c) => c.id === cid);
          return `<span class="tag-char">👤 ${char ? char.name : "ID " + cid}</span>`;
        })
        .join("");

      const eventBadges = (s.events || [])
        .map((ev) => {
          const eventObj = state.events.find((e) => e.id === ev.event_id);
          const title = eventObj ? eventObj.title : `Событие #${ev.event_id}`;
          return `<span class="tag-event">${ev.role}: ${title}</span>`;
        })
        .join("");

      return `
      <div class="story-card" onclick="openStoryModal(${s.id})">
        <div class="story-card-header">
          <div class="story-card-title">${escapeHtml(s.title)}</div>
          <span class="story-id-badge">ID #${s.id}</span>
        </div>
        <div class="story-card-summary">${escapeHtml(s.summary || "Без аннотации")}</div>
        <div class="story-card-footer">
          ${charBadges}
          ${eventBadges}
        </div>
      </div>
    `;
    })
    .join("");
}

function renderTimeline(events) {
  if (!events || events.length === 0) {
    elements.timelineTrack.innerHTML = `<div class="empty-state">В каноне пока нет зафиксированных событий. Добавьте их во вкладке "События Мира".</div>`;
    return;
  }

  elements.timelineTrack.innerHTML = events
    .map(
      (ev, index) => `
    <div class="timeline-node">
      <div class="timeline-dot"></div>
      <div class="timeline-card">
        <span class="timeline-card-type">Шаг ${index + 1} • ${ev.type}</span>
        <div class="timeline-card-title">${escapeHtml(ev.title)}</div>
        <div class="timeline-card-desc">${escapeHtml(ev.description || "Ключевая точка сюжетной линии")}</div>
      </div>
    </div>
  `
    )
    .join("");
}

function renderCharactersList() {
  elements.charactersList.innerHTML = state.characters
    .map(
      (c) => `
    <div class="item-card">
      <h4>${escapeHtml(c.name)}</h4>
      <span class="tag-char">${c.type}</span>
      <p>${escapeHtml(c.description || "Без описания")}</p>
    </div>
  `
    )
    .join("");
}

function renderEventsList() {
  elements.eventsList.innerHTML = state.events
    .map((e) => {
      const parentTitles = (e.parent_ids || [])
        .map((pid) => {
          const parent = state.events.find((p) => p.id === pid);
          return parent ? parent.title : `#${pid}`;
        })
        .join(", ");

      return `
      <div class="item-card">
        <h4>${escapeHtml(e.title)}</h4>
        <span class="tag-event">${e.type}</span>
        <p>${escapeHtml(e.description || "")}</p>
        ${parentTitles ? `<p style="font-size:0.75rem; color:var(--text-dim);">Требует: ${escapeHtml(parentTitles)}</p>` : ""}
      </div>
    `;
    })
    .join("");
}

function populateCharacterFilter() {
  elements.filterCharacter.innerHTML =
    `<option value="">Все персонажи</option>` +
    state.characters.map((c) => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join("");
}

// Editor Interactive Chips
function renderEditorChips() {
  // Characters
  elements.editorCharactersChips.innerHTML = state.characters
    .map(
      (c) => `
    <div class="chip-item ${state.selectedCharacterIds.has(c.id) ? "selected" : ""}"
         onclick="toggleCharacterSelection(${c.id})">
      ${escapeHtml(c.name)}
    </div>
  `
    )
    .join("");

  // Requires (Prerequisites)
  elements.editorRequiresChips.innerHTML = state.events
    .map(
      (e) => `
    <div class="chip-item ${state.selectedRequiresIds.has(e.id) ? "selected" : ""}"
         onclick="toggleRequiresSelection(${e.id})">
      ${escapeHtml(e.title)}
    </div>
  `
    )
    .join("");

  // Creates (Results)
  elements.editorCreatesChips.innerHTML = state.events
    .map(
      (e) => `
    <div class="chip-item ${state.selectedCreatesIds.has(e.id) ? "selected" : ""}"
         onclick="toggleCreatesSelection(${e.id})">
      ${escapeHtml(e.title)}
    </div>
  `
    )
    .join("");
}

function renderEventParentChips() {
  elements.eventParentsChips.innerHTML = state.events
    .map(
      (e) => `
    <div class="chip-item ${state.selectedParentEventIds.has(e.id) ? "selected" : ""}"
         onclick="toggleEventParentSelection(${e.id})">
      ${escapeHtml(e.title)}
    </div>
  `
    )
    .join("");
}

// Toggle chip selections
window.toggleCharacterSelection = function (id) {
  if (state.selectedCharacterIds.has(id)) state.selectedCharacterIds.delete(id);
  else state.selectedCharacterIds.add(id);
  renderEditorChips();
};

window.toggleRequiresSelection = function (id) {
  if (state.selectedRequiresIds.has(id)) state.selectedRequiresIds.delete(id);
  else state.selectedRequiresIds.add(id);
  renderEditorChips();
};

window.toggleCreatesSelection = function (id) {
  if (state.selectedCreatesIds.has(id)) state.selectedCreatesIds.delete(id);
  else state.selectedCreatesIds.add(id);
  renderEditorChips();
};

window.toggleEventParentSelection = function (id) {
  if (state.selectedParentEventIds.has(id)) state.selectedParentEventIds.delete(id);
  else state.selectedParentEventIds.add(id);
  renderEventParentChips();
};

// Canon Consistency Pre-check
elements.btnPrecheckCanon.addEventListener("click", async () => {
  const requires = Array.from(state.selectedRequiresIds);
  const creates = Array.from(state.selectedCreatesIds);
  const characterIds = Array.from(state.selectedCharacterIds);

  try {
    const res = await fetch(`${LORE_API}/consistency/check`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        requires,
        creates,
        participating_character_ids: characterIds,
      }),
    });
    const result = await res.json();
    displayWarnings(result.warnings || []);
  } catch (err) {
    alert("Ошибка проверки канона через Lore Service: " + err.message);
  }
});

function displayWarnings(warnings) {
  if (!warnings || warnings.length === 0) {
    elements.liveWarningBox.classList.remove("hidden");
    elements.liveWarningBox.style.borderColor = "var(--success-color)";
    elements.liveWarningBox.style.background = "rgba(34, 197, 94, 0.1)";
    elements.warningList.innerHTML = `<li style="color:var(--success-color);">✓ Канон соблюден! Все предпосылки и участники согласованы.</li>`;
    return;
  }

  elements.liveWarningBox.classList.remove("hidden");
  elements.liveWarningBox.style.borderColor = "var(--warning-border)";
  elements.liveWarningBox.style.background = "var(--warning-bg)";
  elements.warningList.innerHTML = warnings
    .map((w) => `<li><strong>[${w.code}]</strong> ${escapeHtml(w.message)}</li>`)
    .join("");
}

// Save Story Handler
elements.btnSaveStory.addEventListener("click", async () => {
  const title = elements.storyTitle.value.trim();
  if (!title) {
    alert("Пожалуйста, введите название текста!");
    return;
  }

  const events = [
    ...Array.from(state.selectedRequiresIds).map((id) => ({ event_id: id, role: "REQUIRES" })),
    ...Array.from(state.selectedCreatesIds).map((id) => ({ event_id: id, role: "CREATES" })),
  ];

  const payload = {
    title,
    summary: elements.storySummary.value.trim() || null,
    content: elements.storyContent.value || null,
    character_ids: Array.from(state.selectedCharacterIds),
    events,
  };

  try {
    const res = await fetch(`${STORY_API}/stories`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const err = await res.json();
      alert("Ошибка сохранения: " + (err.detail || JSON.stringify(err)));
      return;
    }

    const saved = await res.json();

    // Reset form
    elements.storyTitle.value = "";
    elements.storySummary.value = "";
    elements.storyContent.value = "";
    state.selectedCharacterIds.clear();
    state.selectedRequiresIds.clear();
    state.selectedCreatesIds.clear();
    elements.liveWarningBox.classList.add("hidden");
    renderEditorChips();

    alert(`Текст "${saved.title}" успешно сохранен в базе и на диске!`);
    document.getElementById("btn-tab-stories")?.click();
  } catch (err) {
    alert("Ошибка соединения с Story Service: " + err.message);
  }
});

// Story Detail Modal
window.openStoryModal = async function (id) {
  try {
    const res = await fetch(`${STORY_API}/stories/${id}`);
    if (!res.ok) return;
    const story = await res.json();

    elements.modalTitle.textContent = story.title;
    elements.modalMeta.textContent = `Создан: ${new Date(story.created_at).toLocaleString("ru")} | Файл: ${story.file_path || "без файла"}`;
    elements.modalContent.textContent = story.content || "Текст отсутствует или не был загружен.";

    elements.storyModal.classList.remove("hidden");
  } catch (e) {
    alert("Не удалось загрузить подробности текста");
  }
};

elements.btnCloseModal.addEventListener("click", () => {
  elements.storyModal.classList.add("hidden");
});

// Character Creator
elements.btnCreateCharacter.addEventListener("click", async () => {
  const name = elements.charName.value.trim();
  if (!name) return alert("Введите имя персонажа");

  const res = await fetch(`${LORE_API}/characters`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name,
      type: elements.charType.value,
      description: elements.charDesc.value.trim() || null,
    }),
  });

  if (res.ok) {
    elements.charName.value = "";
    elements.charDesc.value = "";
    await loadCharacters();
    alert("Персонаж успешно добавлен в мир!");
  } else {
    const err = await res.json();
    alert("Ошибка: " + (err.detail || "Не удалось создать персонажа"));
  }
});

// Event Creator
elements.btnCreateEvent.addEventListener("click", async () => {
  const title = elements.eventTitle.value.trim();
  if (!title) return alert("Введите название события");

  const res = await fetch(`${LORE_API}/world-events`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title,
      type: elements.eventType.value,
      parent_ids: Array.from(state.selectedParentEventIds),
    }),
  });

  if (res.ok) {
    elements.eventTitle.value = "";
    state.selectedParentEventIds.clear();
    await loadEvents();
    alert("Событие зафиксировано в каноне!");
  } else {
    const err = await res.json();
    alert("Ошибка: " + (err.detail || "Не удалось зафиксировать событие"));
  }
});

// Filter Handlers
elements.filterSearch.addEventListener("input", debounce(loadStories, 300));
elements.filterCharacter.addEventListener("change", loadStories);
elements.btnRefreshStories.addEventListener("click", loadStories);

// Demo World Seed
elements.btnSeedData.addEventListener("click", async () => {
  if (!confirm("Загрузить начальный набор персонажей (Фальк, Синда, Айзек, Конрад) и событий?")) return;

  try {
    // 1. Create Characters
    const c1 = await postJson(`${LORE_API}/characters`, { name: "Айзек", type: "COMPANION", description: "Спутник отряда" });
    const c2 = await postJson(`${LORE_API}/characters`, { name: "Синда", type: "COMPANION", description: "Спутница отряда" });
    const c3 = await postJson(`${LORE_API}/characters`, { name: "Фальк", type: "COMPANION", description: "Спутник-андроид" });
    const c4 = await postJson(`${LORE_API}/characters`, { name: "Конрад", type: "NPC", description: "Таинственный изобретатель" });

    // 2. Create Events
    const e1 = await postJson(`${LORE_API}/world-events`, {
      title: "Фальк присоединился к отряду",
      type: "COMPANION_JOIN",
      participants: [{ character_id: c3.id, role: "PARTICIPANT" }]
    });

    const e2 = await postJson(`${LORE_API}/world-events`, {
      title: "Конрад впервые появился",
      type: "NPC_APPEAR",
      participants: [{ character_id: c4.id, role: "PARTICIPANT" }]
    });

    const e3 = await postJson(`${LORE_API}/world-events`, {
      title: "Раскрыта правда о происхождении Фалька",
      type: "REVELATION",
      parent_ids: [e1.id, e2.id],
      participants: [{ character_id: c3.id }, { character_id: c4.id }]
    });

    const e4 = await postJson(`${LORE_API}/world-events`, {
      title: "Айзек и Синда стали парой",
      type: "RELATIONSHIP",
      participants: [{ character_id: c1.id }, { character_id: c2.id }]
    });

    // 3. Create Sample Stories
    await postJson(`${STORY_API}/stories`, {
      title: "Незнакомец в лесу",
      summary: "Первая встреча отряда с Фальком на лесной опушке.",
      content: "Солнце уже садилось за кроны деревьев, когда часовой заметил странную фигуру. Это был Фальк. После коротких переговоров он согласился присоединиться к лагерю.",
      character_ids: [c3.id],
      events: [{ event_id: e1.id, role: "CREATES" }]
    });

    await postJson(`${STORY_API}/stories`, {
      title: "Вечер у костра",
      summary: "Разговоры в лагере у огня, пока Фальк дежурит.",
      content: "Пламя трещало, согревая уставших спутников. Фальк сидел неподвижно, всматриваясь в ночную тьму механическим взглядом.",
      character_ids: [c3.id, c1.id],
      events: [{ event_id: e1.id, role: "REQUIRES" }]
    });

    await loadCharacters();
    await loadEvents();
    await loadStories();
    alert("Демо-мир успешно загружен!");
  } catch (e) {
    alert("Ошибка загрузки демо-данных: " + e.message);
  }
});

async function postJson(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  return res.json();
}

function escapeHtml(text) {
  if (!text) return "";
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

// Initial Bootstrap
window.addEventListener("DOMContentLoaded", () => {
  checkHealth();
  loadCharacters();
  loadEvents();
  loadStories();
});
