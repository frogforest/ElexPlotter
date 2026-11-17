// Keep the existing UI data access stable while the services expose ENSI envelopes.
const nativeFetch = window.fetch.bind(window);
window.fetch = async (...args) => {
  const response = await nativeFetch(...args);
  const nativeJson = response.json.bind(response);
  response.json = async () => {
    const body = await nativeJson();
    if (!body || typeof body !== "object" || !("data" in body)) return body;
    if (body.errors) return body;
    if (Array.isArray(body.data) && body.meta?.pagination) {
      const p = body.meta.pagination;
      return { data: body.data, meta: {
        current_page: Math.floor((p.offset || 0) / (p.limit || 20)) + 1,
        per_page: p.limit, total: p.total
      }};
    }
    return body.data;
  };
  return response;
};

const STORY_API = "http://127.0.0.1:8002/api/v1";
const LORE_API = "http://127.0.0.1:8001/api/v1";

// In-memory UI State
let state = {
  characters: [],
  events: [],
  stories: [],
  viewMode: "tree", // 'tree' (hierarchical by milestone) or 'flat' (all stories grid)
  selectedCharacterIds: new Set(),
  selectedParentEventIds: new Set(),
  selectedEventCharIds: new Set(),
  editMilestoneCharIds: new Set(),
  editMilestoneParentIds: new Set(),
};

// Category Metadata
const EVENT_CATEGORIES = {
  COMPANION_JOIN: { label: "Присоединение спутника", class: "type-companion" },
  NPC_APPEAR: { label: "Появление нового NPC", class: "type-npc" },
  RELATIONSHIP: { label: "Отношения спутников", class: "type-relationship" },
  WORLD_STATE: { label: "Глобальные события", class: "type-world-state" },
  PLOT_MILESTONE: { label: "Сюжетный рубеж", class: "type-plot" },
  REVELATION: { label: "Раскрытие тайны", class: "type-revelation" },
  CHARACTER_BACKSTORY: { label: "Прошлое персонажей", class: "type-backstory" },
  CHARACTER_DEATH: { label: "Гибель персонажа", class: "type-death" },
};

// DOM Elements
const elements = {
  tabs: document.querySelectorAll(".nav-item"),
  panes: document.querySelectorAll(".tab-pane"),
  pageTitle: document.getElementById("page-title"),
  pageSubtitle: document.getElementById("page-subtitle"),

  // Views & Filters
  btnViewTree: document.getElementById("btn-view-tree"),
  btnViewFlat: document.getElementById("btn-view-flat"),
  chronicleTree: document.getElementById("chronicle-tree"),
  storiesGrid: document.getElementById("stories-grid"),
  filterSearch: document.getElementById("filter-search"),
  filterEventType: document.getElementById("filter-event-type"),
  filterCharacter: document.getElementById("filter-character"),
  btnRefreshStories: document.getElementById("btn-refresh-stories"),
  btnQuickNewStory: document.getElementById("btn-quick-new-story"),
  btnQuickNewEvent: document.getElementById("btn-quick-new-event"),

  // Editor
  editingStoryId: document.getElementById("editing-story-id"),
  editorModeBanner: document.getElementById("editor-mode-banner"),
  editorEditingTitle: document.getElementById("editor-editing-title"),
  btnCancelStoryEdit: document.getElementById("btn-cancel-story-edit"),
  storyTitle: document.getElementById("story-title"),
  storySummary: document.getElementById("story-summary"),
  storyContent: document.getElementById("story-content"),
  storyMilestone: document.getElementById("story-milestone"),
  editorCharactersChips: document.getElementById("editor-characters-chips"),
  checkCreatesMilestone: document.getElementById("check-creates-milestone"),
  newMilestoneFields: document.getElementById("new-milestone-fields"),
  modeCreateNew: document.getElementById("mode-create-new-milestone"),
  modeLinkExisting: document.getElementById("mode-link-existing-milestone"),
  boxCreateNew: document.getElementById("box-create-new-milestone"),
  boxLinkExisting: document.getElementById("box-link-existing-milestone"),
  newMilestoneTitle: document.getElementById("new-milestone-title"),
  newMilestoneType: document.getElementById("new-milestone-type"),
  selectEstablishedMilestone: document.getElementById("select-established-milestone"),
  liveWarningBox: document.getElementById("live-warning-box"),
  warningIcon: document.getElementById("warning-icon"),
  warningTitle: document.getElementById("warning-title"),
  warningList: document.getElementById("warning-list"),
  btnPrecheckCanon: document.getElementById("btn-precheck-canon"),
  btnSaveStory: document.getElementById("btn-save-story"),

  // Timeline Graph
  timelineTrack: document.getElementById("timeline-track"),

  // Characters & Events Management
  charName: document.getElementById("char-name"),
  charType: document.getElementById("char-type"),
  charDesc: document.getElementById("char-desc"),
  btnCreateCharacter: document.getElementById("btn-create-character"),
  charactersList: document.getElementById("characters-list"),

  eventTitle: document.getElementById("event-title"),
  eventType: document.getElementById("event-type"),
  eventCharsChips: document.getElementById("event-chars-chips"),
  eventParentsChips: document.getElementById("event-parents-chips"),
  btnCreateEvent: document.getElementById("btn-create-event"),
  eventsList: document.getElementById("events-list"),

  // Story Reader Modal
  storyModal: document.getElementById("story-modal"),
  modalTitle: document.getElementById("modal-story-title"),
  modalMeta: document.getElementById("modal-story-meta"),
  modalFilePath: document.getElementById("modal-file-path"),
  modalContent: document.getElementById("modal-story-content"),
  modalWarnings: document.getElementById("modal-warnings"),
  btnCloseModal: document.getElementById("btn-close-modal"),

  // Milestone Edit Modal
  milestoneModal: document.getElementById("milestone-modal"),
  editMilestoneId: document.getElementById("edit-milestone-id"),
  editMilestoneTitle: document.getElementById("edit-milestone-title"),
  editMilestoneType: document.getElementById("edit-milestone-type"),
  editMilestoneDesc: document.getElementById("edit-milestone-desc"),
  editMilestoneCharsChips: document.getElementById("edit-milestone-chars-chips"),
  editMilestoneParentsChips: document.getElementById("edit-milestone-parents-chips"),
  btnCloseMilestoneModal: document.getElementById("btn-close-milestone-modal"),
  btnCancelMilestoneEdit: document.getElementById("btn-cancel-milestone-edit"),
  btnSaveMilestoneEdit: document.getElementById("btn-save-milestone-edit"),

  // Demo Seed
  btnSeedData: document.getElementById("btn-seed-data"),
};

// Navigation tab switching
function switchTab(targetId) {
  elements.tabs.forEach((t) => t.classList.remove("active"));
  elements.panes.forEach((p) => p.classList.remove("active"));

  const targetTab = Array.from(elements.tabs).find((t) => t.dataset.tab === targetId);
  if (targetTab) targetTab.classList.add("active");

  const targetPane = document.getElementById(targetId);
  if (targetPane) targetPane.classList.add("active");

  if (targetId === "tab-stories") {
    elements.pageTitle.textContent = "Хроника Канона и Текстов";
    elements.pageSubtitle.textContent = "Линейная структура мира: ключевые вехи и вложенные истории по периодам";
    loadEvents().then(() => loadStories());
  } else if (targetId === "tab-editor") {
    elements.pageTitle.textContent = elements.editingStoryId.value ? "Редактирование текста" : "Новый текст";
    elements.pageSubtitle.textContent = "Написание сцены с автоматической проверкой канона через Lore Service";
    populateMilestoneDropdown();
    renderEditorChips();
    triggerLivePrecheck();
  } else if (targetId === "tab-events") {
    elements.pageTitle.textContent = "Ключевые вехи канона";
    elements.pageSubtitle.textContent = "Линейная последовательность ключевых сюжетных рубежей мира";
    loadEvents();
  } else if (targetId === "tab-characters") {
    elements.pageTitle.textContent = "Персонажи сеттинга";
    elements.pageSubtitle.textContent = "Основы и второстепенные NPC мира";
    loadCharacters();
  } else if (targetId === "tab-timeline") {
    elements.pageTitle.textContent = "Граф связей канона";
    elements.pageSubtitle.textContent = "Визуализация причинно-следственного DAG-графа";
    loadTimeline();
  }
}

elements.tabs.forEach((tab) => {
  tab.addEventListener("click", () => switchTab(tab.dataset.tab));
});

if (elements.btnQuickNewStory) {
  elements.btnQuickNewStory.addEventListener("click", () => {
    cancelStoryEdit();
    switchTab("tab-editor");
  });
}
if (elements.btnQuickNewEvent) {
  elements.btnQuickNewEvent.addEventListener("click", () => switchTab("tab-events"));
}

// View Mode Switching
if (elements.btnViewTree && elements.btnViewFlat) {
  elements.btnViewTree.addEventListener("click", () => {
    state.viewMode = "tree";
    elements.btnViewTree.classList.add("active");
    elements.btnViewFlat.classList.remove("active");
    elements.chronicleTree.classList.remove("hidden");
    elements.storiesGrid.classList.add("hidden");
    renderChronicleView();
  });

  elements.btnViewFlat.addEventListener("click", () => {
    state.viewMode = "flat";
    elements.btnViewFlat.classList.add("active");
    elements.btnViewTree.classList.remove("active");
    elements.storiesGrid.classList.remove("hidden");
    elements.chronicleTree.classList.add("hidden");
    renderFlatView();
  });
}

// Health Check
async function checkHealth() {
  try {
    const sRes = await fetch(`${STORY_API}/stories:search`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({pagination: {offset: 0, limit: 1}})
    });
    updateStatusPill("status-story", sRes.ok);
  } catch {
    updateStatusPill("status-story", false);
  }

  try {
    const lRes = await fetch(`${LORE_API}/timeline`);
    updateStatusPill("status-lore", lRes.ok);
  } catch {
    updateStatusPill("status-lore", false);
  }
}

function updateStatusPill(id, isOnline) {
  const el = document.getElementById(id);
  if (!el) return;
  const dot = el.querySelector(".dot");
  if (isOnline) {
    dot.className = "dot online";
    el.style.borderColor = "rgba(16, 185, 129, 0.4)";
  } else {
    dot.className = "dot offline";
    el.style.borderColor = "rgba(239, 68, 68, 0.4)";
  }
}

// Data Loaders
async function loadCharacters() {
  try {
    const res = await fetch(`${LORE_API}/characters:search`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({pagination: {offset: 0, limit: 100}})
    });
    if (!res.ok) return;
    const data = await res.json();
    state.characters = data.data || [];
    renderCharactersList();
    populateCharacterFilter();
    renderEditorChips();
    renderEventCharChips();
  } catch (err) {
    console.error("Error loading characters:", err);
  }
}

async function loadEvents() {
  try {
    const res = await fetch(`${LORE_API}/world-events:search`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({pagination: {offset: 0, limit: 100}})
    });
    if (!res.ok) return;
    const data = await res.json();
    // Sort events strictly by sort_order
    state.events = (data.data || []).sort((a, b) => a.sort_order - b.sort_order || a.id - b.id);
    renderEventsList();
    renderEventParentChips();
    populateMilestoneDropdown();
  } catch (err) {
    console.error("Error loading events:", err);
  }
}

async function loadStories() {
  try {
    const search = elements.filterSearch.value.trim();
    const charId = elements.filterCharacter.value;
    const filter = {};
    if (search) filter.q = search;
    if (charId) filter.character_id = Number(charId);

    const res = await fetch(`${STORY_API}/stories:search`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({filter, pagination: {offset: 0, limit: 100}})
    });
    if (!res.ok) return;
    const data = await res.json();
    state.stories = data.data || [];

    if (state.viewMode === "tree") {
      renderChronicleView();
    } else {
      renderFlatView();
    }
  } catch (err) {
    console.error("Error loading stories:", err);
  }
}

async function loadTimeline() {
  try {
    const res = await fetch(`${LORE_API}/timeline`);
    if (!res.ok) {
      elements.timelineTrack.innerHTML = `<div class="empty-state">Не удалось загрузить хронологию канона.</div>`;
      return;
    }
    const events = await res.json();
    renderTimelineGraph(events);
  } catch (err) {
    elements.timelineTrack.innerHTML = `<div class="empty-state">Ошибка связи: ${err.message}</div>`;
  }
}

// RENDER: Chronicle Tree (Google Docs Style Hierarchy)
function renderChronicleView() {
  const selectedType = elements.filterEventType ? elements.filterEventType.value : "";
  const selectedCharId = elements.filterCharacter ? parseInt(elements.filterCharacter.value) : null;
  const searchQuery = elements.filterSearch ? elements.filterSearch.value.trim().toLowerCase() : "";

  if (!state.events || state.events.length === 0) {
    elements.chronicleTree.innerHTML = `
      <div class="empty-state">
        <p>В мире пока нет ключевых вех канона.</p>
        <button class="btn-primary" onclick="switchTab('tab-events')" style="margin-top:12px;">+ Добавить первую веху</button>
      </div>`;
    return;
  }

  // Group stories by their primary_event_id and extract origin stories (role CREATES)
  const storiesByMilestone = {};
  const originStoriesByEvent = {};
  const unassignedStories = [];

  state.stories.forEach((s) => {
    // Character filter
    if (selectedCharId && !(s.character_ids || []).includes(selectedCharId)) {
      return;
    }

    // Check if this story creates/establishes a key milestone
    const createsEv = (s.events || []).find((e) => e.role === "CREATES");
    if (createsEv) {
      originStoriesByEvent[createsEv.event_id] = s;
      return; // Origin story lives directly inside the milestone header!
    }

    // Assign to milestone as regular subsequent story
    let milestoneId = s.primary_event_id;
    if (!milestoneId && s.events && s.events.length > 0) {
      milestoneId = s.events[0].event_id;
    }

    if (milestoneId) {
      if (!storiesByMilestone[milestoneId]) storiesByMilestone[milestoneId] = [];
      storiesByMilestone[milestoneId].push(s);
    } else {
      unassignedStories.push(s);
    }
  });

  // Filter events by selected category
  const hasActiveStoryFilter = Boolean(searchQuery || selectedCharId);

  const filteredEvents = state.events.filter((ev) => {
    if (selectedType && ev.type !== selectedType) return false;

    // During a story search (text query or character filter), hide milestones
    // that have no matching stories. This keeps the chronology focused on
    // actual search results instead of showing unrelated empty periods.
    if (hasActiveStoryFilter) {
      const hasMatchingOriginStory = Boolean(originStoriesByEvent[ev.id]);
      const hasMatchingRegularStories = (storiesByMilestone[ev.id] || []).length > 0;
      if (!hasMatchingOriginStory && !hasMatchingRegularStories) return false;
    }

    return true;
  });

  if (filteredEvents.length === 0 && selectedType) {
    const typeLabel = EVENT_CATEGORIES[selectedType]?.label || selectedType;
    elements.chronicleTree.innerHTML = `
      <div class="empty-state">
        <p>В каноне пока нет вех мира с категорией «${escapeHtml(typeLabel)}».</p>
        <button class="btn-secondary" onclick="elements.filterEventType.value = ''; renderChronicleView();" style="margin-top:12px;">Сбросить фильтр категорий</button>
      </div>`;
    return;
  }

  const milestoneHtml = filteredEvents
    .map((ev, evIndex) => {
      const catMeta = EVENT_CATEGORIES[ev.type] || { label: ev.type, class: "type-plot" };
      const stories = storiesByMilestone[ev.id] || [];
      const originStory = originStoriesByEvent[ev.id];

      // Participants list
      const participantsHtml = (ev.participants || [])
        .map((p) => {
          const char = state.characters.find((c) => c.id === p.character_id);
          const name = char ? char.name : `Персонаж #${p.character_id}`;
          return `<span class="participant-pill"> ${escapeHtml(name)}</span>`;
        })
        .join("");

      // Origin Story block inside the milestone header
      let originStoryHtml = "";
      if (originStory) {
        const originFilename = originStory.file_path
          ? originStory.file_path.split(/[\\/]/).pop()
          : `${originStory.title}.txt`;
        originStoryHtml = `
          <div class="origin-story-box" onclick="openStoryModal(${originStory.id})">
            <div class="origin-story-badge">
              <span class="pulse-dot"></span>
              <span>Текст-первоисточник вехи (как мир пришел к этому событию):</span>
            </div>
            <div class="origin-story-content">
              <div class="origin-story-title-row">
                <h4 class="origin-story-title"> ${escapeHtml(originStory.title)}</h4>
                <span class="file-name-badge"> ${escapeHtml(originFilename)}</span>
              </div>
              ${originStory.summary ? `<p class="origin-story-summary">${escapeHtml(originStory.summary)}</p>` : ""}
            </div>
            <div class="origin-story-actions" onclick="event.stopPropagation()">
              <button class="btn-read-origin" onclick="openStoryModal(${originStory.id})">Читать текст события</button>
              <button class="btn-action-icon" onclick="openEditStory(${originStory.id})" title="Редактировать текст">️</button>
              <button class="btn-action-icon btn-danger" onclick="deleteStory(${originStory.id})" title="Удалить текст">️</button>
            </div>
          </div>`;
      } else {
        originStoryHtml = `
          <div class="origin-story-placeholder">
            <div class="origin-placeholder-left">
              <span class="placeholder-icon"></span>
              <div class="placeholder-text">
                <strong>У этой вехи пока нет закрепленного текста-первоисточника.</strong>
                <span>Сцена («как до этого дошло»), породившая этот поворотный пункт канона.</span>
              </div>
            </div>
            <button class="btn-outline-sm btn-origin-add" onclick="writeOriginStoryForMilestone(${ev.id}, '${escapeHtml(ev.title)}')">
              + Написать текст-первоисточник
            </button>
          </div>`;
      }

      // Render nested stories for this milestone
      let storiesHtml = "";
      if (stories.length === 0) {
        storiesHtml = `<div class="empty-milestone-stories">Пока нет написанных текстов в этом периоде сюжета.</div>`;
      } else {
        storiesHtml = stories
          .map((s, sIndex) => {
            const charBadges = (s.character_ids || [])
              .map((cid) => {
                const char = state.characters.find((c) => c.id === cid);
                return `<span class="tag-char"> ${char ? char.name : "ID " + cid}</span>`;
              })
              .join("");

            const safeFilename = s.file_path ? s.file_path.split(/[\\/]/).pop() : `${s.title}.txt`;

            return `
            <div class="nested-story-card" onclick="openStoryModal(${s.id})">
              <div class="nested-story-left">
                <div class="story-order-tag" title="Порядковый номер в периоде">${ev.sort_order || evIndex + 1}.${sIndex + 1}</div>
                <div class="story-info">
                  <div class="story-title-row">
                    <h4 class="story-title">${escapeHtml(s.title)}</h4>
                    <span class="file-name-badge"> ${escapeHtml(safeFilename)}</span>
                  </div>
                  <p class="story-summary">${escapeHtml(s.summary || "Без аннотации")}</p>
                  <div class="story-characters">
                    ${charBadges}
                  </div>
                </div>
              </div>
              <div class="story-card-actions">
                <button class="btn-read" onclick="event.stopPropagation(); openStoryModal(${s.id})">Читать</button>
                <button class="btn-action-icon" onclick="event.stopPropagation(); openEditStory(${s.id})" title="Редактировать текст">️</button>
                <button class="btn-action-icon btn-danger" onclick="event.stopPropagation(); deleteStory(${s.id})" title="Удалить текст">️</button>
              </div>
            </div>`;
          })
          .join("");
      }

      const isFirst = evIndex === 0;
      const isLast = evIndex === filteredEvents.length - 1;

      return `
      <div class="milestone-block" data-event-id="${ev.id}">
        <div class="milestone-header">
          <div class="milestone-order-badge">#${ev.sort_order || evIndex + 1}</div>
          <div class="milestone-content">
            <div class="milestone-top">
              <div class="milestone-title-wrap">
                <span class="tag-event-type ${catMeta.class}">${catMeta.label}</span>
                <h3 class="milestone-title">${escapeHtml(ev.title)}</h3>
              </div>
              <div class="milestone-actions">
                <button class="btn-icon btn-reorder" onclick="moveEvent(${evIndex}, -1)" ${isFirst ? "disabled" : ""} title="Переместить веху выше">▲</button>
                <button class="btn-icon btn-reorder" onclick="moveEvent(${evIndex}, 1)" ${isLast ? "disabled" : ""} title="Переместить веху ниже">▼</button>
                <button class="btn-outline-sm" onclick="quickAddStoryToMilestone(${ev.id})">+ Текст в этот период</button>
                <button class="btn-action-icon" onclick="openEditMilestoneModal(${ev.id})" title="Редактировать веху">️</button>
                <button class="btn-action-icon btn-danger" onclick="deleteMilestone(${ev.id})" title="Удалить веху">️</button>
              </div>
            </div>
            ${ev.description ? `<div class="milestone-desc">${escapeHtml(ev.description)}</div>` : ""}
            ${participantsHtml ? `<div class="milestone-participants">${participantsHtml}</div>` : ""}
            ${originStoryHtml}
          </div>
        </div>

        <div class="milestone-stories-container">
          <div class="stories-sub-header">
            <span class="stories-sub-title"> Последующие тексты и сцены этого периода:</span>
          </div>
          ${storiesHtml}
        </div>
      </div>`;
    })
    .join("");

  // Unassigned stories section (Prologue / General) - only shown when viewing all categories
  let unassignedHtml = "";
  if (!selectedType && unassignedStories.length > 0) {
    const unassignedItems = unassignedStories
      .map(
        (s, idx) => `
      <div class="nested-story-card" onclick="openStoryModal(${s.id})">
        <div class="nested-story-left">
          <div class="story-order-tag">0.${idx + 1}</div>
          <div class="story-info">
            <div class="story-title-row">
              <h4 class="story-title">${escapeHtml(s.title)}</h4>
              <span class="file-name-badge"> ${escapeHtml(s.file_path ? s.file_path.split(/[\\/]/).pop() : s.title + '.txt')}</span>
            </div>
            <p class="story-summary">${escapeHtml(s.summary || "Без аннотации")}</p>
          </div>
        </div>
        <div class="story-card-actions">
          <button class="btn-read" onclick="event.stopPropagation(); openStoryModal(${s.id})">Читать</button>
          <button class="btn-action-icon" onclick="event.stopPropagation(); openEditStory(${s.id})" title="Редактировать текст">️</button>
          <button class="btn-action-icon btn-danger" onclick="event.stopPropagation(); deleteStory(${s.id})" title="Удалить текст">️</button>
        </div>
      </div>`
      )
      .join("");

    unassignedHtml = `
      <div class="unassigned-block">
        <h3>НЕСОРТИРОВАННЫЕ ТЕКСТЫ</h3>
        <div class="milestone-stories-container" style="padding-left:0; background:none;">
          ${unassignedItems}
        </div>
      </div>`;
  }

  elements.chronicleTree.innerHTML = milestoneHtml + unassignedHtml;
}

// RENDER: Flat Grid View
function renderFlatView() {
  if (!state.stories || state.stories.length === 0) {
    elements.storiesGrid.innerHTML = `<div class="empty-state">Нет написанных текстов. Нажмите "+ Написать текст", чтобы создать первую историю мира.</div>`;
    return;
  }

  elements.storiesGrid.innerHTML = state.stories
    .map((s, idx) => {
      const charBadges = (s.character_ids || [])
        .map((cid) => {
          const char = state.characters.find((c) => c.id === cid);
          return `<span class="tag-char"> ${char ? char.name : "ID " + cid}</span>`;
        })
        .join("");

      const safeFilename = s.file_path ? s.file_path.split(/[\\/]/).pop() : `${s.title}.txt`;

      let milestoneTitle = "Вне вех";
      if (s.primary_event_id) {
        const m = state.events.find((e) => e.id === s.primary_event_id);
        if (m) milestoneTitle = m.title;
      }

      return `
      <div class="story-card" onclick="openStoryModal(${s.id})">
        <div class="story-card-header">
          <div class="story-card-title">${escapeHtml(s.title)}</div>
          <span class="story-id-badge">#${idx + 1}</span>
        </div>
        <div class="file-name-badge" style="width:fit-content; margin-bottom:4px;"> ${escapeHtml(safeFilename)}</div>
        <div class="story-card-summary">${escapeHtml(s.summary || "Без аннотации")}</div>
        ${s.search_excerpt ? `<div class="search-result-excerpt">Найдено в тексте: ${escapeHtml(s.search_excerpt)}</div>` : ""}
        <div style="font-size:0.75rem; color:var(--accent-primary);">Период: ${escapeHtml(milestoneTitle)}</div>
        <div class="story-card-footer">
          <div style="display:flex; flex-wrap:wrap; gap:4px; flex:1;">${charBadges}</div>
          <div class="story-card-actions">
            <button class="btn-action-icon" onclick="event.stopPropagation(); openEditStory(${s.id})" title="Редактировать"></button>
            <button class="btn-action-icon btn-danger" onclick="event.stopPropagation(); deleteStory(${s.id})" title="Удалить"></button>
          </div>
        </div>
      </div>`;
    })
    .join("");
}

// Quick Add Story to Milestone (as subsequent story in that period)
function quickAddStoryToMilestone(milestoneId) {
  cancelStoryEdit();
  switchTab("tab-editor");
  if (elements.storyMilestone) {
    elements.storyMilestone.value = String(milestoneId);
    triggerLivePrecheck();
  }
}

// Write Origin Story for Milestone (as the defining genesis/catalyst scene)
function writeOriginStoryForMilestone(eventId, eventTitle) {
  cancelStoryEdit();
  switchTab("tab-editor");

  const currentEvent = state.events.find((e) => e.id === eventId);
  if (currentEvent && currentEvent.parent_ids && currentEvent.parent_ids.length > 0) {
    elements.storyMilestone.value = String(currentEvent.parent_ids[0]);
  } else {
    // Find preceding milestone
    const earlier = state.events.filter((e) => (e.sort_order || 0) < (currentEvent?.sort_order || 0));
    if (earlier.length > 0) {
      elements.storyMilestone.value = String(earlier[earlier.length - 1].id);
    } else {
      elements.storyMilestone.value = "";
    }
  }

  // Pre-select participating characters of this milestone if any
  state.selectedCharacterIds.clear();
  if (currentEvent && currentEvent.participants) {
    currentEvent.participants.forEach((p) => state.selectedCharacterIds.add(p.character_id));
  }
  renderEditorChips();

  // Set "This story establishes a milestone" pointing to this existing milestone
  if (elements.checkCreatesMilestone) {
    elements.checkCreatesMilestone.checked = true;
    elements.newMilestoneFields.classList.remove("hidden");
  }
  if (elements.modeLinkExisting) {
    elements.modeLinkExisting.checked = true;
    elements.modeCreateNew.checked = false;
    elements.boxCreateNew.classList.add("hidden");
    elements.boxLinkExisting.classList.remove("hidden");
    populateEstablishedMilestonesDropdown();
    elements.selectEstablishedMilestone.value = String(eventId);
  }

  elements.storyTitle.value = "";
  elements.storyTitle.placeholder = `например: Битва, приведшая к "${eventTitle}"`;
  elements.storyTitle.focus();
  triggerLivePrecheck();
}

// Populate Milestone Dropdown in Editor
function populateMilestoneDropdown() {
  if (!elements.storyMilestone) return;

  const currentVal = elements.storyMilestone.value;
  elements.storyMilestone.innerHTML =
    `<option value="">-- Вне ключевых вех (Пролог / Общие события) --</option>` +
    state.events
      .map((ev, index) => {
        const cat = EVENT_CATEGORIES[ev.type] ? EVENT_CATEGORIES[ev.type].label : ev.type;
        return `<option value="${ev.id}">[Веха #${ev.sort_order || index + 1}] ${escapeHtml(ev.title)} (${cat})</option>`;
      })
      .join("");

  if (currentVal) elements.storyMilestone.value = currentVal;
  populateEstablishedMilestonesDropdown();
}

function populateEstablishedMilestonesDropdown() {
  if (!elements.selectEstablishedMilestone) return;

  const currentVal = elements.selectEstablishedMilestone.value;
  elements.selectEstablishedMilestone.innerHTML =
    `<option value="">-- Выберите существующую веху канона --</option>` +
    state.events
      .map((ev, index) => {
        const cat = EVENT_CATEGORIES[ev.type] ? EVENT_CATEGORIES[ev.type].label : ev.type;
        return `<option value="${ev.id}">[Веха #${ev.sort_order || index + 1}] ${escapeHtml(ev.title)} (${cat})</option>`;
      })
      .join("");

  if (currentVal) elements.selectEstablishedMilestone.value = currentVal;
}

// Reordering World Events (▲ / ▼)
async function moveEvent(index, direction) {
  const targetIndex = index + direction;
  if (targetIndex < 0 || targetIndex >= state.events.length) return;

  const temp = state.events[index];
  state.events[index] = state.events[targetIndex];
  state.events[targetIndex] = temp;

  const items = state.events.map((e, idx) => ({
    event_id: e.id,
    sort_order: idx + 1,
  }));

  renderChronicleView();
  renderEventsList();

  try {
    const res = await fetch(`${LORE_API}/world-events:reorder`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items }),
    });

    if (res.ok) {
      await loadEvents();
      if (state.viewMode === "tree") renderChronicleView();
    } else {
      const err = await res.json();
      alert("Не удалось изменить порядок: " + (err.detail || "Ошибка сервера"));
      await loadEvents();
      if (state.viewMode === "tree") renderChronicleView();
    }
  } catch (err) {
    alert("Ошибка связи с сервером при смене порядка: " + err.message);
    await loadEvents();
    if (state.viewMode === "tree") renderChronicleView();
  }
}

// ==========================================
// STORY EDIT & DELETE LOGIC
// ==========================================
async function openEditStory(storyId) {
  try {
    const res = await fetch(`${STORY_API}/stories/${storyId}`);
    if (!res.ok) return alert("Не удалось загрузить данные истории");
    const story = await res.json();

    elements.editingStoryId.value = String(story.id);
    elements.storyTitle.value = story.title;
    elements.storySummary.value = story.summary || "";
    elements.storyContent.value = story.content || "";
    elements.storyMilestone.value = story.primary_event_id ? String(story.primary_event_id) : "";

    state.selectedCharacterIds = new Set(story.character_ids || []);
    renderEditorChips();

    // Check if this story creates/establishes a milestone (role CREATES)
    const createsEv = (story.events || []).find((e) => e.role === "CREATES");
    if (createsEv) {
      if (elements.checkCreatesMilestone) {
        elements.checkCreatesMilestone.checked = true;
        elements.newMilestoneFields.classList.remove("hidden");
      }
      if (elements.modeLinkExisting) {
        elements.modeLinkExisting.checked = true;
        elements.modeCreateNew.checked = false;
        elements.boxCreateNew.classList.add("hidden");
        elements.boxLinkExisting.classList.remove("hidden");
        populateEstablishedMilestonesDropdown();
        elements.selectEstablishedMilestone.value = String(createsEv.event_id);
      }
    } else {
      if (elements.checkCreatesMilestone) {
        elements.checkCreatesMilestone.checked = false;
        elements.newMilestoneFields.classList.add("hidden");
      }
      if (elements.modeCreateNew) {
        elements.modeCreateNew.checked = true;
        elements.modeLinkExisting.checked = false;
        elements.boxCreateNew.classList.remove("hidden");
        elements.boxLinkExisting.classList.add("hidden");
      }
    }

    elements.editorEditingTitle.textContent = story.title;
    elements.editorModeBanner.classList.remove("hidden");
    elements.btnSaveStory.textContent = "Сохранить изменения в тексте";

    switchTab("tab-editor");
    triggerLivePrecheck();
  } catch (err) {
    alert("Ошибка при открытии текста для редактирования: " + err.message);
  }
}

function cancelStoryEdit() {
  elements.editingStoryId.value = "";
  elements.storyTitle.value = "";
  elements.storySummary.value = "";
  elements.storyContent.value = "";
  elements.storyMilestone.value = "";
  state.selectedCharacterIds.clear();
  renderEditorChips();

  elements.editorModeBanner.classList.add("hidden");
  elements.btnSaveStory.textContent = "Сохранить текст (.txt)";
  if (elements.checkCreatesMilestone) elements.checkCreatesMilestone.checked = false;
  if (elements.newMilestoneFields) elements.newMilestoneFields.classList.add("hidden");
  if (elements.newMilestoneTitle) elements.newMilestoneTitle.value = "";
  if (elements.modeCreateNew) elements.modeCreateNew.checked = true;
  if (elements.modeLinkExisting) elements.modeLinkExisting.checked = false;
  if (elements.boxCreateNew) elements.boxCreateNew.classList.remove("hidden");
  if (elements.boxLinkExisting) elements.boxLinkExisting.classList.add("hidden");
  if (elements.selectEstablishedMilestone) elements.selectEstablishedMilestone.value = "";
  if (elements.liveWarningBox) elements.liveWarningBox.classList.add("hidden");
}

if (elements.btnCancelStoryEdit) {
  elements.btnCancelStoryEdit.addEventListener("click", cancelStoryEdit);
}

async function deleteStory(storyId) {
  const story = state.stories.find((s) => s.id === storyId);
  const title = story ? story.title : `#${storyId}`;

  if (!confirm(`Вы действительно хотите удалить текст "${title}" и его .txt файл из базы?`)) {
    return;
  }

  try {
    const res = await fetch(`${STORY_API}/stories/${storyId}`, {
      method: "DELETE",
    });

    if (res.ok) {
      if (elements.editingStoryId.value === String(storyId)) {
        cancelStoryEdit();
      }
      await loadStories();
      alert(`Текст "${title}" успешно удален.`);
    } else {
      const err = await res.json();
      alert("Ошибка удаления текста: " + (err.detail || "Неизвестная ошибка"));
    }
  } catch (err) {
    alert("Ошибка соединения при удалении текста: " + err.message);
  }
}

// ==========================================
// MILESTONE (EVENT) EDIT & DELETE LOGIC
// ==========================================
function openEditMilestoneModal(eventId) {
  const ev = state.events.find((e) => e.id === eventId);
  if (!ev) return;

  elements.editMilestoneId.value = String(ev.id);
  elements.editMilestoneTitle.value = ev.title;
  elements.editMilestoneType.value = ev.type;
  elements.editMilestoneDesc.value = ev.description || "";

  state.editMilestoneCharIds = new Set((ev.participants || []).map((p) => p.character_id));
  renderEditMilestoneCharChips();

  state.editMilestoneParentIds = new Set(ev.parent_ids || []);
  renderEditMilestoneParentChips(ev.id);

  elements.milestoneModal.classList.remove("hidden");
}

function renderEditMilestoneCharChips() {
  if (!elements.editMilestoneCharsChips) return;
  elements.editMilestoneCharsChips.innerHTML = state.characters
    .map(
      (c) => `
    <div class="chip-item ${state.editMilestoneCharIds.has(c.id) ? "selected" : ""}"
         onclick="toggleEditMilestoneChar(${c.id})">
      ${escapeHtml(c.name)}
    </div>`
    )
    .join("");
}

function toggleEditMilestoneChar(cid) {
  if (state.editMilestoneCharIds.has(cid)) {
    state.editMilestoneCharIds.delete(cid);
  } else {
    state.editMilestoneCharIds.add(cid);
  }
  renderEditMilestoneCharChips();
}

function renderEditMilestoneParentChips(currentEventId) {
  if (!elements.editMilestoneParentsChips) return;
  const availableEvents = state.events.filter((e) => e.id !== currentEventId);
  if (availableEvents.length === 0) {
    elements.editMilestoneParentsChips.innerHTML = `<span style="color:var(--text-muted); font-size:12px;">Нет других вех для выбора</span>`;
    return;
  }
  elements.editMilestoneParentsChips.innerHTML = availableEvents
    .map(
      (e) => `
    <div class="chip-item ${state.editMilestoneParentIds.has(e.id) ? "selected" : ""}"
         onclick="toggleEditMilestoneParent(${e.id}, ${currentEventId})">
      ${escapeHtml(e.title)}
    </div>`
    )
    .join("");
}

function toggleEditMilestoneParent(parentId, currentEventId) {
  if (state.editMilestoneParentIds.has(parentId)) {
    state.editMilestoneParentIds.delete(parentId);
  } else {
    state.editMilestoneParentIds.add(parentId);
  }
  renderEditMilestoneParentChips(currentEventId);
}

function closeMilestoneModal() {
  elements.milestoneModal.classList.add("hidden");
  elements.editMilestoneId.value = "";
  state.editMilestoneCharIds.clear();
  state.editMilestoneParentIds.clear();
}

if (elements.btnCloseMilestoneModal) {
  elements.btnCloseMilestoneModal.addEventListener("click", closeMilestoneModal);
}
if (elements.btnCancelMilestoneEdit) {
  elements.btnCancelMilestoneEdit.addEventListener("click", closeMilestoneModal);
}

if (elements.btnSaveMilestoneEdit) {
  elements.btnSaveMilestoneEdit.addEventListener("click", async () => {
    const eventId = parseInt(elements.editMilestoneId.value);
    const title = elements.editMilestoneTitle.value.trim();
    if (!title) return alert("Введите название вехи");

    const participants = Array.from(state.editMilestoneCharIds).map((cid) => ({
      character_id: cid,
      role: "PARTICIPANT",
    }));

    try {
      const res = await fetch(`${LORE_API}/world-events/${eventId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title,
          type: elements.editMilestoneType.value,
          description: elements.editMilestoneDesc.value.trim() || null,
          participants,
          parent_ids: Array.from(state.editMilestoneParentIds),
        }),
      });

      if (res.ok) {
        closeMilestoneModal();
        await loadEvents();
        await loadStories();
        alert("Веха канона успешно обновлена!");
      } else {
        const err = await res.json();
        alert("Ошибка обновления вехи: " + (err.detail || "Неизвестная ошибка"));
      }
    } catch (err) {
      alert("Ошибка связи с Lore Service: " + err.message);
    }
  });
}

async function deleteMilestone(eventId) {
  const ev = state.events.find((e) => e.id === eventId);
  const title = ev ? ev.title : `#${eventId}`;

  if (!confirm(`Вы действительно хотите удалить ключевую веху "${title}"?\n\n(Вложенные тексты останутся в базе и будут перенесены в раздел "Вне ключевых вех")`)) {
    return;
  }

  try {
    const res = await fetch(`${LORE_API}/world-events/${eventId}`, {
      method: "DELETE",
    });

    if (res.ok) {
      await loadEvents();
      await loadStories();
      alert(`Веха "${title}" успешно удалена.`);
    } else {
      const err = await res.json();
      alert("Ошибка удаления вехи: " + (err.detail || "Неизвестная ошибка"));
    }
  } catch (err) {
    alert("Ошибка соединения с Lore Service: " + err.message);
  }
}

// RENDER: Characters List (Separated into Companions and NPCs)
function renderCharactersList() {
  if (!elements.charactersList) return;

  const companions = state.characters.filter((c) => c.type === "COMPANION");
  const others = state.characters.filter((c) => c.type !== "COMPANION");

  const renderCard = (c) => `
    <div class="item-card character-card" data-character-id="${c.id}">
      <div style="display:flex; justify-content:space-between; align-items:center; gap:10px;">
        <h4>${escapeHtml(c.name)}</h4>
        <span class="tag-char">${escapeHtml(c.type)}</span>
      </div>
      <p>${escapeHtml(c.description || "Без описания")}</p>
      <div class="character-card-actions">
        <button type="button" class="btn-outline-sm" data-character-action="edit" data-character-id="${c.id}"> Редактировать</button>
        <button type="button" class="btn-action-icon btn-danger" title="Удалить персонажа" aria-label="Удалить персонажа"
          data-character-action="delete" data-character-id="${c.id}"></button>
      </div>
    </div>`;

  let html = "";
  if (companions.length > 0) {
    html += `
      <div style="grid-column: 1 / -1; margin-top:8px;">
        <h4 style="color:var(--accent-secondary); margin-bottom:8px;">Спутники отряда (${companions.length})</h4>
      </div>
      ${companions.map(renderCard).join("")}`;
  }

  if (others.length > 0) {
    html += `
      <div style="grid-column: 1 / -1; margin-top:16px;">
        <h4 style="color:var(--accent-primary); margin-bottom:8px;">Второстепенные NPC мира (${others.length})</h4>
      </div>
      ${others.map(renderCard).join("")}`;
  }

  elements.charactersList.innerHTML = html || `<div class="empty-state">Персонажи пока не добавлены.</div>`;
}

// Character edit/delete actions. Delegation survives list re-rendering.
if (elements.charactersList) {
  elements.charactersList.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-character-action]");
    if (!button) return;

    const characterId = Number(button.dataset.characterId);
    const character = state.characters.find((item) => item.id === characterId);
    if (!character) {
      await loadCharacters();
      return;
    }

    const action = button.dataset.characterAction;
    if (action === "edit") {
      const name = prompt("Имя персонажа:", character.name);
      if (name === null) return;
      const trimmedName = name.trim();
      if (!trimmedName) return alert("Имя персонажа не может быть пустым.");

      const type = prompt(
        "Тип персонажа (COMPANION, NPC, PROTAGONIST, ANTAGONIST):",
        character.type
      );
      if (type === null) return;
      const normalizedType = type.trim().toUpperCase();
      const allowedTypes = ["COMPANION", "NPC", "PROTAGONIST", "ANTAGONIST"];
      if (!allowedTypes.includes(normalizedType)) {
        return alert("Неизвестный тип персонажа. Допустимо: " + allowedTypes.join(", "));
      }

      const description = prompt("Описание персонажа (можно оставить пустым):", character.description || "");
      if (description === null) return;

      try {
        const response = await fetch(`${LORE_API}/characters/${characterId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: trimmedName,
            type: normalizedType,
            description: description.trim() || null,
          }),
        });
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          const message = body.errors?.[0]?.message || body.detail || "Не удалось обновить персонажа";
          return alert("Ошибка обновления: " + message);
        }
        await loadCharacters();
        alert("Персонаж успешно обновлён.");
      } catch (error) {
        alert("Не удалось связаться с Lore Service: " + error.message);
      }
      return;
    }

    if (action === "delete") {
      const confirmed = confirm(
        `Удалить персонажа «${character.name}»?\n\nСвязи участия в событиях будут удалены. Сами события и зависимости DAG сохранятся.`
      );
      if (!confirmed) return;

      try {
        const response = await fetch(`${LORE_API}/characters/${characterId}`, {
          method: "DELETE",
        });
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          const message = body.errors?.[0]?.message || body.detail || "Не удалось удалить персонажа";
          return alert("Ошибка удаления: " + message);
        }
        await loadCharacters();
        await loadEvents();
        alert("Персонаж удалён. События канона сохранены.");
      } catch (error) {
        alert("Не удалось связаться с Lore Service: " + error.message);
      }
    }
  });
}

// RENDER: Events List in Management Tab
function renderEventsList() {
  if (!elements.eventsList) return;

  if (!state.events || state.events.length === 0) {
    elements.eventsList.innerHTML = `<div class="empty-state">Событий пока нет.</div>`;
    return;
  }

  elements.eventsList.innerHTML = state.events
    .map((e, index) => {
      const catMeta = EVENT_CATEGORIES[e.type] || { label: e.type, class: "type-plot" };
      const parentTitles = (e.parent_ids || [])
        .map((pid) => {
          const parent = state.events.find((p) => p.id === pid);
          return parent ? parent.title : `#${pid}`;
        })
        .join(", ");

      const isFirst = index === 0;
      const isLast = index === state.events.length - 1;

      return `
      <div class="item-card event-item-card" data-event-id="${e.id}">
        <div class="item-card-header">
          <div class="order-badge" title="Порядковый номер следования в каноне">#${index + 1}</div>
          <div class="item-card-title-group">
            <h4>${escapeHtml(e.title)}</h4>
            <span class="tag-event-type ${catMeta.class}">${catMeta.label}</span>
          </div>
          <div class="reorder-actions">
            <button class="btn-icon btn-reorder" onclick="moveEvent(${index}, -1)" ${isFirst ? "disabled" : ""} title="Переместить выше">▲</button>
            <button class="btn-icon btn-reorder" onclick="moveEvent(${index}, 1)" ${isLast ? "disabled" : ""} title="Переместить ниже">▼</button>
            <button class="btn-action-icon" onclick="openEditMilestoneModal(${e.id})" title="Редактировать веху">️</button>
            <button class="btn-action-icon btn-danger" onclick="deleteMilestone(${e.id})" title="Удалить веху">️</button>
          </div>
        </div>
        <p>${escapeHtml(e.description || "")}</p>
        ${parentTitles ? `<p class="item-meta-dep"> Зависит от: <strong>${escapeHtml(parentTitles)}</strong></p>` : ""}
      </div>`;
    })
    .join("");
}

// Populate Filters
function populateCharacterFilter() {
  if (!elements.filterCharacter) return;
  const currentVal = elements.filterCharacter.value;
  elements.filterCharacter.innerHTML =
    `<option value="">Все персонажи</option>` +
    state.characters.map((c) => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join("");
  if (currentVal) elements.filterCharacter.value = currentVal;
}

// Editor Interactive Chips
function renderEditorChips() {
  if (!elements.editorCharactersChips) return;
  elements.editorCharactersChips.innerHTML = state.characters
    .map(
      (c) => `
    <div class="chip-item ${state.selectedCharacterIds.has(c.id) ? "selected" : ""}"
         onclick="toggleCharacterSelection(${c.id})">
      ${escapeHtml(c.name)}
    </div>`
    )
    .join("");
}

function renderEventCharChips() {
  if (!elements.eventCharsChips) return;
  elements.eventCharsChips.innerHTML = state.characters
    .map(
      (c) => `
    <div class="chip-item ${state.selectedEventCharIds.has(c.id) ? "selected" : ""}"
         onclick="toggleEventCharSelection(${c.id})">
      ${escapeHtml(c.name)}
    </div>`
    )
    .join("");
}

function renderEventParentChips() {
  if (!elements.eventParentsChips) return;
  elements.eventParentsChips.innerHTML = state.events
    .map(
      (e) => `
    <div class="chip-item ${state.selectedParentEventIds.has(e.id) ? "selected" : ""}"
         onclick="toggleEventParentSelection(${e.id})">
      ${escapeHtml(e.title)}
    </div>`
    )
    .join("");
}

function toggleCharacterSelection(id) {
  if (state.selectedCharacterIds.has(id)) {
    state.selectedCharacterIds.delete(id);
  } else {
    state.selectedCharacterIds.add(id);
  }
  renderEditorChips();
  triggerLivePrecheck();
}

function toggleEventCharSelection(id) {
  if (state.selectedEventCharIds.has(id)) {
    state.selectedEventCharIds.delete(id);
  } else {
    state.selectedEventCharIds.add(id);
  }
  renderEventCharChips();
}

function toggleEventParentSelection(id) {
  if (state.selectedParentEventIds.has(id)) {
    state.selectedParentEventIds.delete(id);
  } else {
    state.selectedParentEventIds.add(id);
  }
  renderEventParentChips();
}

// Toggle Creates Milestone Fields in Editor
if (elements.checkCreatesMilestone && elements.newMilestoneFields) {
  elements.checkCreatesMilestone.addEventListener("change", (e) => {
    if (e.target.checked) {
      elements.newMilestoneFields.classList.remove("hidden");
      populateEstablishedMilestonesDropdown();
    } else {
      elements.newMilestoneFields.classList.add("hidden");
    }
  });
}

if (elements.modeCreateNew && elements.modeLinkExisting) {
  elements.modeCreateNew.addEventListener("change", () => {
    if (elements.boxCreateNew) elements.boxCreateNew.classList.remove("hidden");
    if (elements.boxLinkExisting) elements.boxLinkExisting.classList.add("hidden");
  });
  elements.modeLinkExisting.addEventListener("change", () => {
    if (elements.boxCreateNew) elements.boxCreateNew.classList.add("hidden");
    if (elements.boxLinkExisting) elements.boxLinkExisting.classList.remove("hidden");
    populateEstablishedMilestonesDropdown();
  });
}

// Editor Live Precheck
if (elements.storyMilestone) {
  elements.storyMilestone.addEventListener("change", () => triggerLivePrecheck());
}

async function triggerLivePrecheck() {
  const milestoneId = elements.storyMilestone.value ? parseInt(elements.storyMilestone.value) : null;
  const characterIds = Array.from(state.selectedCharacterIds);

  const requires = milestoneId ? [milestoneId] : [];
  const creates = [];

  const warnings = [];

  if (milestoneId) {
    const activeMilestone = state.events.find((e) => e.id === milestoneId);
    const activeSortOrder = activeMilestone ? activeMilestone.sort_order : 0;

    characterIds.forEach((cid) => {
      const char = state.characters.find((c) => c.id === cid);
      const charName = char ? char.name : `ID ${cid}`;

      const introEvents = state.events.filter(
        (e) =>
          (e.type === "COMPANION_JOIN" || e.type === "NPC_APPEAR") &&
          (e.participants || []).some((p) => p.character_id === cid)
      );

      if (introEvents.length > 0) {
        const earliestIntro = introEvents[0];
        if (earliestIntro.sort_order > activeSortOrder) {
          warnings.push({
            code: "CHARACTER_NOT_YET_PRESENT",
            message: `Персонаж '${charName}' указан в этой сцене, однако по хронологии канона событие его появления/присоединения к отряду ('${earliestIntro.title}') происходит позже (на вехе #${earliestIntro.sort_order})!`,
          });
        }
      }
    });
  }

  try {
    const res = await fetch(`${LORE_API}/canon:check-consistency`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        requires,
        creates,
        participating_character_ids: characterIds,
      }),
    });

    if (res.ok) {
      const data = await res.json();
      (data.warnings || []).forEach((w) => {
        if (!warnings.some((existing) => existing.message === w.message)) {
          warnings.push(w);
        }
      });
    }
  } catch (err) {
    console.warn("Lore Service precheck error:", err);
  }

  renderLiveWarnings(warnings);
}

function renderLiveWarnings(warnings) {
  if (!elements.liveWarningBox) return;

  if (warnings.length === 0) {
    elements.liveWarningBox.classList.remove("hidden");
    elements.liveWarningBox.style.background = "rgba(16, 185, 129, 0.1)";
    elements.liveWarningBox.style.borderColor = "rgba(16, 185, 129, 0.3)";
    elements.warningTitle.textContent = "Канон соблюден:";
    elements.warningTitle.style.color = "#34d399";
    elements.warningList.innerHTML = `<li style="color:#a7f3d0;">Все персонажи присутствуют в лагере к этой вехе, хронологических противоречий не обнаружено.</li>`;
  } else {
    elements.liveWarningBox.classList.remove("hidden");
    elements.liveWarningBox.style.background = "rgba(239, 68, 68, 0.12)";
    elements.liveWarningBox.style.borderColor = "rgba(239, 68, 68, 0.35)";
    elements.warningTitle.textContent = "Обнаружены логические противоречия канона:";
    elements.warningTitle.style.color = "#f87171";
    elements.warningList.innerHTML = warnings
      .map((w) => `<li style="color:#fecaca;"><strong>[${escapeHtml(w.code || "ОШИБКА")}]:</strong> ${escapeHtml(w.message)}</li>`)
      .join("");
  }
}

if (elements.btnPrecheckCanon) {
  elements.btnPrecheckCanon.addEventListener("click", triggerLivePrecheck);
}

// Save Story Handler (Create or Update)
if (elements.btnSaveStory) {
  elements.btnSaveStory.addEventListener("click", async () => {
    const title = elements.storyTitle.value.trim();
    if (!title) return alert("Введите название текста");

    const summary = elements.storySummary.value.trim() || null;
    const content = elements.storyContent.value.trim() || null;
    const milestoneId = elements.storyMilestone.value ? parseInt(elements.storyMilestone.value) : null;
    const characterIds = Array.from(state.selectedCharacterIds);
    const editingId = elements.editingStoryId.value ? parseInt(elements.editingStoryId.value) : null;

    let createdEventId = null;

    // If user checked "Creates/establishes key milestone"
    if (elements.checkCreatesMilestone && elements.checkCreatesMilestone.checked) {
      const isCreateNew = elements.modeCreateNew && elements.modeCreateNew.checked;

      if (isCreateNew) {
        const newEvTitle = elements.newMilestoneTitle.value.trim();
        if (!newEvTitle) return alert("Введите название нового события мира");

        try {
          const evRes = await fetch(`${LORE_API}/world-events`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              title: newEvTitle,
              type: elements.newMilestoneType.value,
              parent_ids: milestoneId ? [milestoneId] : [],
              participants: characterIds.map((cid) => ({ character_id: cid, role: "PARTICIPANT" })),
            }),
          });

          if (evRes.ok) {
            const newEv = await evRes.json();
            createdEventId = newEv.id;
            await loadEvents();
          } else {
            const err = await evRes.json();
            return alert("Ошибка создания нового события: " + (err.detail || "Неизвестная ошибка"));
          }
        } catch (e) {
          return alert("Ошибка соединения с Lore Service: " + e.message);
        }
      } else {
        const existingEvId = elements.selectEstablishedMilestone
          ? parseInt(elements.selectEstablishedMilestone.value)
          : null;
        if (!existingEvId) {
          return alert("Пожалуйста, выберите существующую веху мира, которую устанавливает этот текст.");
        }
        createdEventId = existingEvId;
      }
    }

    const storyEvents = [];
    if (milestoneId) {
      storyEvents.push({ event_id: milestoneId, role: "REQUIRES" });
    }
    if (createdEventId) {
      storyEvents.push({ event_id: createdEventId, role: "CREATES" });
    }

    const payload = {
      title,
      summary,
      content,
      primary_event_id: createdEventId || milestoneId,
      character_ids: characterIds,
      events: storyEvents,
    };

    try {
      let res;
      if (editingId) {
        // UPDATE existing story
        res = await fetch(`${STORY_API}/stories/${editingId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
      } else {
        // CREATE new story
        res = await fetch(`${STORY_API}/stories`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
      }

      if (res.ok) {
        const savedStory = await res.json();
        cancelStoryEdit();
        await loadStories();
        alert(`Текст "${savedStory.title}" успешно сохранен в канон!\nФайл: ${savedStory.file_path || title + ".txt"}`);
        switchTab("tab-stories");
      } else {
        const err = await res.json();
        alert("Ошибка сохранения: " + (err.detail || "Не удалось сохранить текст"));
      }
    } catch (err) {
      alert("Ошибка соединения со Story Service: " + err.message);
    }
  });
}

// Character Creator
if (elements.btnCreateCharacter) {
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
}

// Event Creator
if (elements.btnCreateEvent) {
  elements.btnCreateEvent.addEventListener("click", async () => {
    const title = elements.eventTitle.value.trim();
    if (!title) return alert("Введите название события");

    const participants = Array.from(state.selectedEventCharIds).map((cid) => ({
      character_id: cid,
      role: "PARTICIPANT",
    }));

    const res = await fetch(`${LORE_API}/world-events`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title,
        type: elements.eventType.value,
        parent_ids: Array.from(state.selectedParentEventIds),
        participants,
      }),
    });

    if (res.ok) {
      elements.eventTitle.value = "";
      state.selectedParentEventIds.clear();
      state.selectedEventCharIds.clear();
      await loadEvents();
      alert("Ключевая веха канона успешно зафиксирована!");
    } else {
      const err = await res.json();
      alert("Ошибка: " + (err.detail || "Не удалось зафиксировать событие"));
    }
  });
}

// Timeline Graph Renderer (Tab 5)
function renderTimelineGraph(events) {
  if (!events || events.length === 0) {
    elements.timelineTrack.innerHTML = `<div class="empty-state">В каноне пока нет зафиксированных событий.</div>`;
    return;
  }

  elements.timelineTrack.innerHTML = events
    .map((ev, index) => {
      const catMeta = EVENT_CATEGORIES[ev.type] || { label: ev.type, class: "type-plot" };
      return `
      <div class="timeline-node">
        <div class="timeline-dot"></div>
        <div class="timeline-card">
          <span class="timeline-card-type ${catMeta.class}">Веха #${index + 1} • ${catMeta.label}</span>
          <div class="timeline-card-title">${escapeHtml(ev.title)}</div>
          <div class="timeline-card-desc">${escapeHtml(ev.description || "Ключевая точка сюжетной линии мира")}</div>
        </div>
      </div>`;
    })
    .join("");
}

// Modal Reader
async function openStoryModal(storyId) {
  try {
    const res = await fetch(`${STORY_API}/stories/${storyId}`);
    if (!res.ok) return;
    const story = await res.json();

    elements.modalTitle.textContent = story.title;
    elements.modalMeta.textContent = `ID #${story.id} • Создан: ${new Date(story.created_at).toLocaleDateString()}`;
    elements.modalFilePath.textContent = `Файл: ${story.file_path || story.title + '.txt'}`;
    elements.modalContent.textContent = story.content || "Текстовое содержимое файла пока не добавлено.";

    if (story.warnings && story.warnings.length > 0) {
      elements.modalWarnings.classList.remove("hidden");
      elements.modalWarnings.innerHTML =
        `<strong>Предупреждения канона:</strong><ul>` +
        story.warnings.map((w) => `<li>${escapeHtml(w.message)}</li>`).join("") +
        `</ul>`;
    } else {
      elements.modalWarnings.classList.add("hidden");
    }

    elements.storyModal.classList.remove("hidden");
  } catch (err) {
    alert("Не удалось загрузить текст: " + err.message);
  }
}

if (elements.btnCloseModal) {
  elements.btnCloseModal.addEventListener("click", () => {
    elements.storyModal.classList.add("hidden");
  });
}

window.addEventListener("click", (e) => {
  if (e.target === elements.storyModal) {
    elements.storyModal.classList.add("hidden");
  }
  if (e.target === elements.milestoneModal) {
    closeMilestoneModal();
  }
});

// Filters handlers
if (elements.filterSearch) {
  elements.filterSearch.addEventListener("input", debounce(loadStories, 250));
}
if (elements.filterEventType) {
  elements.filterEventType.addEventListener("change", () => renderChronicleView());
}
if (elements.filterCharacter) {
  elements.filterCharacter.addEventListener("change", loadStories);
}
if (elements.btnRefreshStories) {
  elements.btnRefreshStories.addEventListener("click", loadStories);
}

// Demo World Seed Button
if (elements.btnSeedData) {
  elements.btnSeedData.addEventListener("click", async () => {
    if (
      !confirm(
        "Загрузить?\n\nЕсли они уже есть в базе, дубликаты создаваться не будут."
      )
    ) {
      return;
    }

    try {
      // 1. Refresh latest state from both services
      await Promise.all([loadCharacters(), loadEvents(), loadStories()]);

      let addedChars = 0;
      let addedEvents = 0;
      let addedStories = 0;

      // Helper to safely get or create character
      async function getOrCreateChar(name, type, description) {
        let existing = state.characters.find(
          (c) => c.name.trim().toLowerCase() === name.trim().toLowerCase()
        );
        if (existing) return existing;

        const res = await fetch(`${LORE_API}/characters`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, type, description }),
        });
        if (res.ok) {
          addedChars++;
          const char = await res.json();
          state.characters.push(char);
          return char;
        }

        const refRes = await fetch(`${LORE_API}/characters?page[size]=100`);
        if (refRes.ok) {
          const ref = await refRes.json();
          state.characters = ref.data || [];
          return state.characters.find(
            (c) => c.name.trim().toLowerCase() === name.trim().toLowerCase()
          );
        }
        return null;
      }

      async function getOrCreateEvent(title, type, parentIds = [], participants = []) {
        let existing = state.events.find(
          (e) => e.title.trim().toLowerCase() === title.trim().toLowerCase()
        );
        if (existing) return existing;

        const validParents = parentIds.filter(Boolean);
        const validParticipants = participants.filter((p) => p && p.character_id);

        const res = await fetch(`${LORE_API}/world-events`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title,
            type,
            parent_ids: validParents,
            participants: validParticipants,
          }),
        });
        if (res.ok) {
          addedEvents++;
          const event = await res.json();
          state.events.push(event);
          return event;
        }

        const refRes = await fetch(`${LORE_API}/world-events?page[size]=100`);
        if (refRes.ok) {
          const ref = await refRes.json();
          state.events = (ref.data || []).sort((a, b) => a.sort_order - b.sort_order || a.id - b.id);
          return state.events.find(
            (e) => e.title.trim().toLowerCase() === title.trim().toLowerCase()
          );
        }
        return null;
      }

      // Helper to safely get or create story
      async function getOrCreateStory(title, summary, content, primaryEventId, charIds, reqEventIds) {
        let existing = state.stories.find(
          (s) => s.title.trim().toLowerCase() === title.trim().toLowerCase()
        );
        if (existing) return existing;

        const validCharIds = charIds.filter(Boolean);
        const validEvents = reqEventIds.filter(Boolean).map((id) => ({ event_id: id, role: "REQUIRES" }));

        const res = await fetch(`${STORY_API}/stories`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title,
            summary,
            content,
            primary_event_id: primaryEventId || null,
            character_ids: validCharIds,
            events: validEvents,
          }),
        });
        if (res.ok) {
          addedStories++;
          const story = await res.json();
          state.stories.push(story);
          return story;
        }
        return null;
      }

      await loadCharacters();
      await loadEvents();
      await loadStories();
      switchTab("tab-stories");

      if (addedChars === 0 && addedEvents === 0 && addedStories === 0) {
        alert(
          "Демо-мир уже полностью загружен в вашу базу!"
        );
      } else {
        alert(
          `Демо-данные успешно добавлены!\n\n+ Персонажей: ${addedChars}\n+ Вех канона: ${addedEvents}\n+ Сюжетных текстов: ${addedStories}\n\nВсе они теперь доступны в «Хронике Канона».`
        );
      }
    } catch (e) {
      alert("Ошибка при загрузке демо-мира: " + (e.message || e));
    }
  });
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
window.addEventListener("DOMContentLoaded", async () => {
  checkHealth();
  await loadCharacters();
  await loadEvents();
  await loadStories();
});
