const $ = (id) => document.getElementById(id);

const state = {
  query: "",
  book: "",
  results: null,
  library: null,
  libraryQuery: "",
  expandedCategories: new Set(),
  shelf: new Set(),
  bookmarks: [],
  reader: null,
  user: null,
  bookCache: new Map(),
};

const picker = { open: false, active: -1, items: [] };
const QUERY_SEPARATORS = /[\s，。！？；：、,.!?;:'"“”‘’（）()《》〈〉【】\[\]{}…—–\-·\/\\|～]+/;

function splitTerms(text) {
  return text.split(QUERY_SEPARATORS).filter(Boolean);
}

const SHELF_KEY = "novel-shelf-v1";
const BOOKMARKS_KEY = "novel-bookmarks-v1";

function readJSON(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function writeJSON(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {}
}

function loadPersonalData() {
  const shelf = readJSON(SHELF_KEY, []);
  state.shelf = new Set(Array.isArray(shelf) ? shelf.filter((title) => typeof title === "string") : []);

  const bookmarks = readJSON(BOOKMARKS_KEY, []);
  state.bookmarks = Array.isArray(bookmarks)
    ? bookmarks.filter((mark) => mark
      && typeof mark.book === "string"
      && Number.isFinite(mark.chapter_no)
      && Number.isFinite(mark.paragraph))
    : [];
}

function saveShelf() {
  if (state.user) {
    queueAccountSync();
    return;
  }
  writeJSON(SHELF_KEY, [...state.shelf]);
}

function saveBookmarks() {
  if (state.user) {
    queueAccountSync();
    return;
  }
  writeJSON(BOOKMARKS_KEY, state.bookmarks);
}

function clearGuestData() {
  try {
    localStorage.removeItem(SHELF_KEY);
    localStorage.removeItem(BOOKMARKS_KEY);
  } catch {}
}

let accountSyncTimer = 0;

async function syncAccountNow() {
  if (!state.user) return false;
  const headers = { "Content-Type": "application/json" };
  try {
    await Promise.all([
      api("/api/me/shelf", {
        method: "PUT",
        headers,
        body: JSON.stringify({ titles: [...state.shelf] }),
      }),
      api("/api/me/bookmarks", {
        method: "PUT",
        headers,
        body: JSON.stringify({ bookmarks: state.bookmarks }),
      }),
    ]);
    return true;
  } catch {
    return false;
  }
}

function queueAccountSync() {
  if (!state.user) return;
  clearTimeout(accountSyncTimer);
  accountSyncTimer = setTimeout(() => {
    accountSyncTimer = 0;
    syncAccountNow();
  }, 250);
}

const VIEWS = ["search", "library", "shelf", "book", "reader"];
const BASE_TITLE = "古典小说全文检索 · yjw的云上项目";

function setTitle(text) {
  document.title = text ? `${text} · 古典小说全文检索` : BASE_TITLE;
}

function showView(name) {
  for (const view of VIEWS) {
    $("view-" + view).hidden = view !== name;
  }
  let tab = "search";
  if (name === "library" || name === "book") tab = "library";
  if (name === "shelf") tab = "shelf";
  document.querySelectorAll(".tabs a").forEach((link) => {
    const current = link.dataset.tab === tab && name !== "reader";
    link.classList.toggle("active", current);
    if (current) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
}

function setHint(text, isError = false) {
  const hint = $("hint");
  hint.textContent = text;
  hint.classList.toggle("error", isError);
}

function renderRetry(container, message, retry) {
  container.textContent = "";
  const box = document.createElement("div");
  box.className = "error-box";
  const text = document.createElement("p");
  text.textContent = message;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "retry-btn";
  button.textContent = "重试";
  button.addEventListener("click", retry);
  box.append(text, button);
  container.append(box);
  return box;
}

async function api(path, options = {}) {
  let res;
  try {
    res = await fetch(path, options);
  } catch {
    throw new Error("网络连接失败，请检查网络后重试");
  }
  let data = {};
  try {
    data = await res.json();
  } catch {}
  if (res.status === 401 && !path.startsWith("/api/login") && state.user) {
    handleSessionExpired();
  }
  if (!res.ok) throw new Error(data.error || `请求失败（${res.status}）`);
  return data;
}

/* ---------- 弹层焦点管理 ---------- */
const FOCUSABLE = 'input:not([type="hidden"]):not([disabled]), button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';
const modalStack = [];
const modalReturnFocus = new Map();

function modalFocusable(modal) {
  return Array.from(modal.querySelectorAll(FOCUSABLE)).filter((node) => node.offsetParent !== null);
}

function openModal(id) {
  const modal = $(id);
  if (!modal) return;
  modalReturnFocus.set(id, document.activeElement);
  modal.hidden = false;
  if (!modalStack.includes(id)) modalStack.push(id);
  const main = document.querySelector("main");
  if (main) main.inert = true;
  const nodes = modalFocusable(modal);
  const first = nodes.find((node) => node.classList.contains("modal-close")) || nodes[0];
  if (first) first.focus();
}

function closeModal(id) {
  const modal = $(id);
  if (!modal || modal.hidden) return;
  modal.hidden = true;
  const index = modalStack.lastIndexOf(id);
  if (index !== -1) modalStack.splice(index, 1);
  if (!modalStack.length) {
    const main = document.querySelector("main");
    if (main) main.inert = false;
  }
  const back = modalReturnFocus.get(id);
  modalReturnFocus.delete(id);
  if (back && document.contains(back)) back.focus();
}

document.addEventListener("keydown", (event) => {
  if (event.key !== "Tab" || !modalStack.length) return;
  const modal = $(modalStack[modalStack.length - 1]);
  const nodes = modalFocusable(modal);
  if (!nodes.length) return;
  const first = nodes[0];
  const last = nodes[nodes.length - 1];
  if (!modal.contains(document.activeElement)) {
    event.preventDefault();
    first.focus();
  } else if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
});

function updateNetworkBanner() {
  const banner = $("net-banner");
  if (banner) banner.hidden = navigator.onLine;
}

let sessionExpired = false;

function handleSessionExpired() {
  if (sessionExpired) return;
  sessionExpired = true;
  const username = state.user ? state.user.username : "";
  if (state.user) {
    writeJSON(SHELF_KEY, [...state.shelf]);
    writeJSON(BOOKMARKS_KEY, state.bookmarks);
  }
  clearTimeout(accountSyncTimer);
  state.user = null;
  if (!$("account-modal").hidden) closeModal("account-modal");
  refreshAccountUI();
  refreshPersonalUI();
  const banner = $("session-banner");
  if (banner) {
    banner.dataset.username = username;
    banner.hidden = false;
  }
  setHint("登录状态已过期，请重新登录。书架和书签已暂存到本地。", true);
}

function hideSessionBanner() {
  const banner = $("session-banner");
  if (banner) {
    banner.hidden = true;
    delete banner.dataset.username;
  }
  sessionExpired = false;
}

function mergeRanges(ranges) {
  const sorted = [...ranges].sort((a, b) => a.start - b.start || a.length - b.length);
  const merged = [];
  for (const range of sorted) {
    const last = merged[merged.length - 1];
    if (last && range.start <= last.start + last.length) {
      last.length = Math.max(last.length, range.start + range.length - last.start);
    } else {
      merged.push({ ...range });
    }
  }
  return merged;
}

function appendHighlighted(container, text, ranges) {
  let cursor = 0;
  for (const range of mergeRanges(ranges)) {
    if (range.start > cursor) container.append(text.slice(cursor, range.start));
    const mark = document.createElement("mark");
    mark.textContent = text.slice(range.start, range.start + range.length);
    container.append(mark);
    cursor = range.start + range.length;
  }
  container.append(text.slice(cursor));
}

/* ---------- 路由 ---------- */
function parseRoute() {
  const hash = location.hash;
  if (hash.startsWith("#book/")) {
    return { name: "book", title: decodeURIComponent(hash.slice(6)) };
  }
  if (hash.startsWith("#read/")) {
    const [path, queryString = ""] = hash.slice(6).split("?");
    const slash = path.lastIndexOf("/");
    const params = new URLSearchParams(queryString);
    return {
      name: "read",
      title: decodeURIComponent(path.slice(0, slash)),
      no: Number(path.slice(slash + 1)),
      q: params.get("q") || "",
      p: Number(params.get("p")) || 1,
    };
  }
  if (hash.startsWith("#library")) return { name: "library" };
  if (hash.startsWith("#shelf")) return { name: "shelf" };
  return { name: "search" };
}

function readHash(book, no, query, paragraph) {
  const params = new URLSearchParams({ q: query || "", p: String(paragraph || 1) });
  return `#read/${encodeURIComponent(book)}/${no}?${params.toString()}`;
}

async function route() {
  const route = parseRoute();

  if (route.name === "search") {
    showView("search");
    setTitle(state.query && state.results ? `「${state.query}」的检索结果` : "全文检索");
    if (state.query) $("query").value = state.query;
    if (state.results) renderResults(state.results);
    return;
  }

  if (route.name === "library") {
    showView("library");
    setTitle("图书馆");
    $("library-query").value = state.libraryQuery;
    await loadLibrary();
    return;
  }

  if (route.name === "shelf") {
    showView("shelf");
    setTitle("我的书架");
    await loadShelf();
    return;
  }

  if (route.name === "book") {
    showView("book");
    await loadBook(route.title);
    return;
  }

  await loadChapter(route);
}

/* ---------- 检索 ---------- */
function allBooks() {
  const books = [];
  for (const category of (state.library && state.library.categories) || []) {
    for (const book of category.books) {
      books.push({ ...book, category: category.name });
    }
  }
  return books;
}

function closeBookPicker() {
  const input = $("book-picker");
  const list = $("book-picker-list");
  if (!input || !list) return;
  list.hidden = true;
  input.setAttribute("aria-expanded", "false");
  picker.open = false;
  picker.active = -1;
}

function selectBook(title) {
  state.book = title || "";
  const input = $("book-picker");
  if (input) input.value = state.book;
  closeBookPicker();
  if (state.query) doSearch(state.query, 1);
}

function openBookPicker(query) {
  const input = $("book-picker");
  const list = $("book-picker-list");
  if (!input || !list) return;

  const terms = splitTerms(query.toLowerCase());
  const counts = (state.results && state.results.counts) || {};
  const books = allBooks().filter((book) => {
    if (!terms.length) return true;
    const haystack = `${book.title} ${book.author || ""} ${book.category}`.toLowerCase();
    return terms.every((term) => haystack.includes(term));
  });

  picker.items = [
    { title: "", meta: "" },
    ...books.map((book) => ({
      title: book.title,
      meta: `${book.category}${counts[book.title] ? ` · ${counts[book.title]} 段` : ""}`,
    })),
  ];
  picker.active = -1;
  list.textContent = "";

  for (const item of picker.items) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "book-option";
    button.setAttribute("role", "option");

    const label = document.createElement("span");
    label.className = "book-option-title";
    label.textContent = item.title || "全部书目";

    const meta = document.createElement("span");
    meta.className = "book-option-meta";
    meta.textContent = item.meta;

    button.append(label, meta);
    button.addEventListener("mousedown", (event) => event.preventDefault());
    button.addEventListener("click", () => selectBook(item.title));
    list.append(button);
  }

  if (!books.length && terms.length) {
    const empty = document.createElement("div");
    empty.className = "book-option-empty";
    empty.textContent = "没有匹配的书目";
    list.append(empty);
  }

  list.hidden = false;
  input.setAttribute("aria-expanded", "true");
  picker.open = true;
}

function movePicker(delta) {
  const list = $("book-picker-list");
  if (!picker.open || !list) return;
  const options = Array.from(list.querySelectorAll(".book-option"));
  if (!options.length) return;
  picker.active = Math.max(0, Math.min(options.length - 1, picker.active + delta));
  options.forEach((option, index) => option.classList.toggle("active", index === picker.active));
  options[picker.active].scrollIntoView({ block: "nearest" });
}

function renderBookPicker() {
  const input = $("book-picker");
  if (!input) return;
  if (document.activeElement !== input) {
    input.value = state.book;
    closeBookPicker();
  }
  input.placeholder = state.book ? "" : "全部书目，可输入书名筛选";
}

function matchingBooks(query) {
  const terms = splitTerms(query.toLowerCase());
  if (!terms.length) return [];
  return allBooks().filter((book) => {
    const haystack = `${book.title} ${book.author || ""} ${book.category}`.toLowerCase();
    return terms.every((term) => haystack.includes(term));
  });
}

function renderBookMatches(query) {
  const wrap = $("book-matches");
  if (!wrap) return 0;
  const books = matchingBooks(query);
  wrap.textContent = "";
  wrap.hidden = !books.length;
  if (!books.length) return 0;

  const heading = document.createElement("h2");
  heading.textContent = "书目";
  const grid = document.createElement("div");
  grid.className = "book-match-grid";

  for (const book of books) {
    const link = document.createElement("a");
    link.className = "book-match";
    link.href = "#book/" + encodeURIComponent(book.title);
    const title = document.createElement("strong");
    title.textContent = book.title;
    const meta = document.createElement("span");
    meta.textContent = `${book.category}${book.author ? ` · ${book.author}` : ""}`;
    link.append(title, meta);
    grid.append(link);
  }

  wrap.append(heading, grid);
  return books.length;
}

function renderPagination(data) {
  const nav = $("pagination");
  nav.textContent = "";
  nav.hidden = data.pages <= 1;
  if (nav.hidden) return;

  const addButton = (label, page, disabled, current = false) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "page-btn" + (current ? " current" : "");
    btn.textContent = label;
    btn.disabled = disabled;
    if (!disabled && !current) {
      btn.addEventListener("click", () => doSearch(state.query, page));
    }
    nav.append(btn);
  };

  addButton("上一页", data.page - 1, data.page === 1);
  const start = Math.max(1, Math.min(data.page - 2, data.pages - 4));
  const end = Math.min(data.pages, start + 4);
  for (let page = start; page <= end; page += 1) {
    addButton(String(page), page, false, page === data.page);
  }
  addButton("下一页", data.page + 1, data.page === data.pages);

  const info = document.createElement("span");
  info.className = "page-info";
  info.textContent = `共 ${data.pages} 页 · ${data.total} 段`;
  nav.append(info);
}

function renderResults(data) {
  const matchCount = renderBookMatches(data.query);
  const bookCount = Object.keys(data.counts).length;
  if (data.total) {
    const extra = matchCount ? ` 另匹配 ${matchCount} 本书目。` : "";
    $("summary").textContent =
      `「${data.query}」命中 ${data.total} 段，分布在 ${bookCount} 本书中。${extra}`;
  } else if (matchCount) {
    $("summary").textContent =
      `找到 ${matchCount} 本相关书目，正文中没有匹配段落。`;
  } else {
    $("summary").textContent = `没有找到「${data.query}」，换个词试试。`;
  }

  const list = $("result-list");
  list.textContent = "";

  for (const group of data.groups) {
    const section = document.createElement("section");
    section.className = "book-group";

    const heading = document.createElement("h2");
    heading.textContent = group.title;
    const count = document.createElement("span");
    count.textContent = `${group.count} 段`;
    heading.append(count);
    section.append(heading);

    for (const hit of group.hits) {
      const card = document.createElement("article");
      card.className = "hit";
      card.tabIndex = 0;
      card.setAttribute("role", "link");

      const meta = document.createElement("div");
      meta.className = "hit-meta";
      const book = document.createElement("span");
      book.className = "book";
      book.textContent = hit.book;
      const pos = document.createElement("span");
      pos.textContent = `第 ${hit.chapter_no} 回 · 第 ${hit.paragraph} 段 · 第 ${hit.offset} 字`;
      meta.append(book, pos);

      const text = document.createElement("p");
      text.className = "hit-snippet";
      if (hit.cut_before) text.append("……");
      appendHighlighted(text, hit.context, hit.ranges);
      if (hit.cut_after) text.append("……");

      card.append(meta, text);
      const open = () => {
        location.hash = readHash(hit.book, hit.chapter_no, state.query, hit.paragraph);
      };
      card.addEventListener("click", open);
      card.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          open();
        }
      });
      section.append(card);
    }

    list.append(section);
  }

  renderPagination(data);
  renderBookPicker();
}

async function doSearch(query, page = 1) {
  state.query = query;
  setHint("正在查找……");
  const submit = $("search-submit");
  const submitText = submit.textContent;
  submit.disabled = true;
  submit.textContent = "搜索中…";
  try {
    const params = new URLSearchParams({ q: query, page: String(page) });
    if (state.book) params.set("book", state.book);
    const data = await api("/api/search?" + params.toString());
    state.results = data;
    setHint("多个关键词用空格或标点分隔，会同时匹配。");
    setTitle(`「${data.query}」的检索结果`);
    if (location.hash === "#search") {
      showView("search");
      renderResults(data);
    } else {
      location.hash = "#search";
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  } catch (err) {
    setHint(err.message, true);
    $("summary").textContent = "";
    $("book-matches").hidden = true;
    renderRetry($("result-list"), `检索失败：${err.message}`, () => doSearch(query, page));
  } finally {
    submit.disabled = false;
    submit.textContent = submitText;
  }
}

/* ---------- 图书馆 ---------- */
function updateShelfButton(button) {
  const title = button.dataset.shelfTitle;
  const inShelf = state.shelf.has(title);
  const context = button.dataset.shelfContext || "card";
  button.classList.toggle("active", inShelf);
  button.setAttribute("aria-pressed", String(inShelf));
  if (inShelf) {
    button.textContent = context === "shelf" || context === "detail" ? "移出书架" : "已在书架";
  } else {
    button.textContent = "加入书架";
  }
}

function createShelfButton(title, context = "card") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "shelf-btn";
  button.dataset.shelfTitle = title;
  button.dataset.shelfContext = context;
  button.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    toggleShelf(title);
  });
  updateShelfButton(button);
  return button;
}

function updateShelfButtons() {
  document.querySelectorAll(".shelf-btn[data-shelf-title]").forEach(updateShelfButton);
}

function toggleShelf(title) {
  if (state.shelf.has(title)) {
    state.shelf.delete(title);
  } else {
    state.shelf.add(title);
  }
  saveShelf();
  updateShelfButtons();
  if (parseRoute().name === "shelf") renderShelf();
}

function createBookCard(book, context = "card") {
  const wrap = document.createElement("div");
  wrap.className = "book-card-wrap";

  const card = document.createElement("a");
  card.className = "book-card";
  card.href = "#book/" + encodeURIComponent(book.title);

  const title = document.createElement("h3");
  title.textContent = book.title;
  const author = document.createElement("p");
  author.className = "book-author";
  author.textContent = book.author || "佚名";
  const blurb = document.createElement("p");
  blurb.className = "blurb";
  blurb.textContent = book.blurb || "";
  const meta = document.createElement("p");
  meta.className = "book-meta";
  meta.textContent = `${book.chapters} 回 · ${book.chars.toLocaleString()} 字`;
  const enter = document.createElement("span");
  enter.className = "enter";
  enter.textContent = "进入阅读 →";

  card.append(title, author);
  if (book.blurb) card.append(blurb);
  card.append(meta, enter);
  wrap.append(card, createShelfButton(book.title, context));
  return wrap;
}

function renderLibrary(data) {
  const wrap = $("library");
  wrap.textContent = "";
  const query = (state.libraryQuery || "").trim();
  const terms = splitTerms(query.toLowerCase());
  let total = 0;

  for (const category of data.categories) {
    const books = category.books.filter((book) => {
      if (!terms.length) return true;
      const haystack = `${book.title} ${book.author || ""} ${book.blurb || ""} ${category.name}`.toLowerCase();
      return terms.every((term) => haystack.includes(term));
    });
    if (!books.length) continue;
    total += books.length;

    const expanded = state.expandedCategories.has(category.name);
    const visibleBooks = expanded ? books : books.slice(0, 3);

    const section = document.createElement("section");
    const heading = document.createElement("h2");
    heading.className = "shelf-title";
    heading.textContent = category.name;
    const desc = document.createElement("small");
    desc.textContent = category.desc;
    heading.append(desc);
    section.append(heading);

    const grid = document.createElement("div");
    grid.className = `book-grid ${expanded ? "book-grid-four" : "book-grid-three"}`;

    for (const book of visibleBooks) {
      grid.append(createBookCard(book));
    }

    section.append(grid);

    if (books.length > 3) {
      const more = document.createElement("button");
      more.type = "button";
      more.className = "shelf-more";
      more.textContent = expanded ? "收起" : "查看更多";
      more.addEventListener("click", () => {
        if (state.expandedCategories.has(category.name)) {
          state.expandedCategories.delete(category.name);
        } else {
          state.expandedCategories.add(category.name);
        }
        renderLibrary(data);
      });
      section.append(more);
    }

    wrap.append(section);
  }

  if (!total) {
    const empty = document.createElement("p");
    empty.className = "library-empty";
    empty.textContent = query ? `没有找到与「${query}」相关的书。` : "书库为空。";
    wrap.append(empty);
  }

  const count = $("library-count");
  if (count) count.textContent = terms.length ? `找到 ${total} 本` : `共 ${total} 本`;
}

async function loadLibrary() {
  if (state.library) {
    renderLibrary(state.library);
    return;
  }
  const count = $("library-count");
  if (count) count.textContent = "加载中……";
  $("library").textContent = "";
  try {
    state.library = await api("/api/library");
    renderLibrary(state.library);
  } catch (err) {
    if (count) count.textContent = "";
    renderRetry($("library"), `书目加载失败：${err.message}`, loadLibrary);
  }
}

async function getBook(title) {
  if (!state.bookCache.has(title)) {
    state.bookCache.set(title, await api("/api/book?title=" + encodeURIComponent(title)));
  }
  return state.bookCache.get(title);
}

/* ---------- 书架 ---------- */
function emptyShelfNotice(text) {
  const empty = document.createElement("p");
  empty.className = "shelf-empty";
  empty.textContent = text;
  return empty;
}

function renderBookmarks() {
  const wrap = $("bookmark-list");
  if (!wrap) return;
  wrap.textContent = "";

  const marks = [...state.bookmarks].sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
  const count = $("bookmark-count");
  if (count) count.textContent = `${marks.length} 条`;

  if (!marks.length) {
    wrap.append(emptyShelfNotice("还没有书签。阅读时点右上角“书签”，会记住当前段落。"));
    return;
  }

  for (const mark of marks) {
    const item = document.createElement("article");
    item.className = "bookmark-item";

    const link = document.createElement("a");
    link.className = "bookmark-link";
    link.href = readHash(mark.book, mark.chapter_no, "", mark.paragraph);

    const head = document.createElement("div");
    head.className = "bookmark-head";
    const book = document.createElement("strong");
    book.textContent = mark.book;
    const chapter = document.createElement("span");
    chapter.className = "bookmark-chapter";
    chapter.textContent = mark.chapter_title || `第 ${mark.chapter_no} 回`;
    head.append(book, chapter);

    const excerpt = document.createElement("p");
    excerpt.className = "bookmark-excerpt";
    excerpt.textContent = mark.excerpt || "";
    link.append(head, excerpt);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "bookmark-remove";
    remove.textContent = "删除";
    remove.addEventListener("click", () => {
      state.bookmarks = state.bookmarks.filter((entry) => entry.id !== mark.id);
      saveBookmarks();
      renderBookmarks();
      updateBookmarkButton();
    });

    item.append(link, remove);
    wrap.append(item);
  }
}

function renderShelf() {
  const wrap = $("shelf-books");
  if (!wrap) return;
  wrap.textContent = "";

  const books = allBooks().filter((book) => state.shelf.has(book.title));
  const count = $("shelf-count");
  if (count) count.textContent = `${books.length} 本`;

  if (!books.length) {
    wrap.append(emptyShelfNotice("书架还是空的，去图书馆挑几本。"));
  } else {
    for (const book of books) {
      wrap.append(createBookCard(book, "shelf"));
    }
  }
  renderBookmarks();
}

async function loadShelf() {
  if (!state.library) {
    try {
      state.library = await api("/api/library");
    } catch {}
  }
  renderShelf();
}

function renderBookActions(title) {
  const wrap = $("book-actions");
  if (!wrap) return;
  wrap.textContent = "";
  wrap.append(createShelfButton(title, "detail"));
}

async function loadBook(title) {
  setTitle(`${title} · 目录`);
  $("book-title").textContent = title;
  $("book-meta").textContent = "加载中……";
  $("book-actions").textContent = "";
  const list = $("chapter-list");
  list.textContent = "";

  try {
    const data = await getBook(title);
    $("book-meta").textContent = `共 ${data.chapters.length} 回`;
    renderBookActions(title);
    for (const chapter of data.chapters) {
      const link = document.createElement("a");
      link.className = "chapter-link";
      link.href = readHash(title, chapter.no, "", 1);
      link.textContent = chapter.title;
      list.append(link);
    }
  } catch (err) {
    $("book-meta").textContent = "";
    renderRetry(list, `书目加载失败：${err.message}`, () => loadBook(title));
  }
}

/* ---------- 阅读 ---------- */
function renderReader(data, route) {
  $("reader-title").textContent = data.title;
  const body = $("reader-body");
  body.textContent = "";

  const matchMap = new Map(data.matches.map((m) => [m.paragraph, m.ranges]));
  data.paragraphs.forEach((text, index) => {
    const p = document.createElement("p");
    p.id = `p-${index + 1}`;
    appendHighlighted(p, text, matchMap.get(index + 1) || []);
    body.append(p);
  });

  const target = route.p > 1 ? route.p : (data.matches.length ? data.matches[0].paragraph : 0);
  requestAnimationFrame(() => {
    const node = target ? document.getElementById(`p-${target}`) : null;
    if (node) node.scrollIntoView({ block: "center" });
    else window.scrollTo({ top: 0 });
  });
}

function bookmarkKey(book, chapterNo, paragraph) {
  return `${book}|${chapterNo}|${paragraph}`;
}

function currentParagraphInfo() {
  const paragraphs = Array.from($("reader-body").querySelectorAll("p"));
  if (!paragraphs.length) return null;

  const marker = window.innerHeight * 0.35;
  let current = paragraphs[0];
  for (const paragraph of paragraphs) {
    if (paragraph.getBoundingClientRect().top <= marker) current = paragraph;
    else break;
  }

  return {
    paragraph: Number(current.id.replace("p-", "")) || 1,
    text: (current.textContent || "").replace(/\s+/g, " ").trim(),
  };
}

function currentBookmark() {
  if (!state.reader) return null;
  const info = currentParagraphInfo();
  if (!info) return null;
  const id = bookmarkKey(state.reader.book, state.reader.no, info.paragraph);
  return {
    id,
    info,
    mark: state.bookmarks.find((entry) => entry.id === id) || null,
  };
}

function updateBookmarkButton() {
  const button = $("bookmark-toggle");
  if (!button) return;

  if (!state.reader) {
    button.disabled = true;
    button.classList.remove("active");
    button.setAttribute("aria-pressed", "false");
    button.textContent = "书签";
    return;
  }

  button.disabled = false;
  const found = currentBookmark();
  const active = Boolean(found && found.mark);
  button.classList.toggle("active", active);
  button.setAttribute("aria-pressed", String(active));
  button.textContent = active ? "已书签" : "书签";
}

function toggleBookmark() {
  if (!state.reader) return;
  const found = currentBookmark();
  if (!found) return;

  if (found.mark) {
    state.bookmarks = state.bookmarks.filter((entry) => entry.id !== found.id);
  } else {
    state.bookmarks.push({
      id: found.id,
      book: state.reader.book,
      chapter_no: state.reader.no,
      chapter_title: state.reader.title || `第 ${state.reader.no} 回`,
      paragraph: found.info.paragraph,
      excerpt: found.info.text.slice(0, 90),
      created_at: Date.now(),
    });
  }

  saveBookmarks();
  updateBookmarkButton();
  if (parseRoute().name === "shelf") renderBookmarks();
}

async function loadChapter(route) {
  showView("reader");
  state.reader = null;
  $("reader-title").textContent = "加载中……";
  $("reader-body").textContent = "";
  $("bookmark-toggle").disabled = true;
  $("bookmark-toggle").classList.remove("active");
  $("bookmark-toggle").setAttribute("aria-pressed", "false");
  $("bookmark-toggle").textContent = "书签";
  $("reader-back").href = route.q ? "#search" : "#book/" + encodeURIComponent(route.title);
  $("reader-back").textContent = route.q ? "← 返回结果" : "← 目录";
  $("to-book").href = "#book/" + encodeURIComponent(route.title);
  $("prev-chapter").disabled = false;
  $("next-chapter").disabled = false;

  try {
    const params = new URLSearchParams({
      book: route.title,
      no: String(route.no),
      q: route.q,
    });
    const data = await api("/api/chapter?" + params.toString());
    renderReader(data, route);
    setTitle(`${route.title} · ${data.title}`);
    state.reader = { book: route.title, no: route.no, q: route.q, title: data.title };
    updateBookmarkButton();

    try {
      const bookData = await getBook(route.title);
      const numbers = bookData.chapters.map((chapter) => chapter.no);
      const index = numbers.indexOf(route.no);
      $("prev-chapter").disabled = index <= 0;
      $("next-chapter").disabled = index < 0 || index >= numbers.length - 1;
    } catch {}
  } catch (err) {
    setTitle(route.title || "阅读");
    $("reader-title").textContent = "出错了";
    renderRetry($("reader-body"), `本章加载失败：${err.message}`, () => loadChapter(route));
    $("prev-chapter").disabled = true;
    $("next-chapter").disabled = true;
    updateBookmarkButton();
  }
}

/* ---------- 账户 ---------- */
let authMode = "login";

function refreshAccountUI() {
  const button = $("account-btn");
  if (!button) return;
  if (state.user) {
    button.textContent = state.user.username;
    button.classList.add("logged-in");
    button.title = `当前账户：${state.user.username}`;
  } else {
    button.textContent = "登录 / 注册";
    button.classList.remove("logged-in");
    button.title = "";
  }
  const name = $("account-name");
  if (name) name.textContent = state.user ? `当前账户：${state.user.username}` : "";
}

function refreshPersonalUI() {
  updateShelfButtons();
  const route = parseRoute();
  if (route.name === "library" && state.library) renderLibrary(state.library);
  if (route.name === "shelf") renderShelf();
  if (route.name === "book") {
    const title = ($("book-title").textContent || "").trim();
    if (title) renderBookActions(title);
  }
  if (route.name === "read" && state.reader) updateBookmarkButton();
}

function applyAccountData(data, mergeGuest = false) {
  const guestShelf = [...state.shelf];
  const guestBookmarks = state.bookmarks;

  state.user = data.user;
  state.shelf = new Set(Array.isArray(data.shelf) ? data.shelf : []);
  state.bookmarks = Array.isArray(data.bookmarks) ? data.bookmarks : [];
  if (data.user) hideSessionBanner();

  if (mergeGuest) {
    for (const title of guestShelf) state.shelf.add(title);
    const merged = new Map(state.bookmarks.map((mark) => [mark.id, mark]));
    for (const mark of guestBookmarks) merged.set(mark.id, mark);
    state.bookmarks = [...merged.values()];
  }

  refreshAccountUI();
  refreshPersonalUI();
}

async function enterAccount(data, { mergeGuest = false, recoveryCode = "" } = {}) {
  applyAccountData(data, mergeGuest);
  closeAuthModal();
  if (mergeGuest && await syncAccountNow()) {
    clearGuestData();
  }
  if (recoveryCode) showRecoveryCode(recoveryCode);
}

function showRecoveryCode(code, message) {
  $("recovery-code").textContent = code;
  $("recovery-help").textContent =
    message || "这是找回账号的唯一凭证，只显示这一次。";
  $("recovery-copy").textContent = "复制";
  openModal("recovery-modal");
}

function hideAuthError(id) {
  const node = $(id);
  if (node) {
    node.hidden = true;
    node.textContent = "";
  }
}

function showAuthError(id, message) {
  const node = $(id);
  if (node) {
    node.textContent = message;
    node.hidden = false;
  }
}

function passwordError(password) {
  if (password.length < 6) return "密码至少需要 6 位";
  if (!/[A-Za-z]/.test(password) && !/[!-/:-@\[-`{-~]/.test(password)) {
    return "密码必须包含至少一个英文字母或特殊字符";
  }
  return "";
}

function closeAuthModal() {
  closeModal("auth-modal");
  $("reset-form").hidden = true;
  $("auth-form").hidden = false;
  $("auth-reset-link").hidden = false;
  hideAuthError("auth-error");
  hideAuthError("reset-error");
}

function setAuthMode(mode) {
  authMode = mode;
  $("auth-title").textContent = mode === "register" ? "注册" : "登录";
  $("auth-login-tab").classList.toggle("active", mode === "login");
  $("auth-register-tab").classList.toggle("active", mode === "register");
  $("auth-confirm-wrap").hidden = mode !== "register";
  $("auth-note").hidden = mode !== "register";
  $("auth-password-hint").hidden = mode !== "register";
  $("auth-password").autocomplete = mode === "register" ? "new-password" : "current-password";
  $("auth-submit").textContent = mode === "register" ? "注册" : "登录";
  $("auth-form").hidden = false;
  $("reset-form").hidden = true;
  $("auth-reset-link").hidden = false;
  hideAuthError("auth-error");
  hideAuthError("reset-error");
}

function openAuth(mode = "login", username = "") {
  setAuthMode(mode);
  $("auth-username").value = username;
  $("auth-password").value = "";
  $("auth-confirm").value = "";
  openModal("auth-modal");
  if (username) $("auth-password").focus();
  else $("auth-username").focus();
}

function showResetForm() {
  $("auth-title").textContent = "重置密码";
  $("auth-form").hidden = true;
  $("reset-form").hidden = false;
  $("auth-reset-link").hidden = true;
  hideAuthError("auth-error");
  hideAuthError("reset-error");
  $("reset-username").value = $("auth-username").value;
}

async function submitAuth(event) {
  event.preventDefault();
  hideAuthError("auth-error");
  const username = $("auth-username").value.trim();
  const password = $("auth-password").value;
  if (!username || !password) {
    showAuthError("auth-error", "请输入用户名和密码");
    return;
  }
  if (authMode === "register" && password !== $("auth-confirm").value) {
    showAuthError("auth-error", "两次输入的密码不一致");
    return;
  }
  if (authMode === "register") {
    const weak = passwordError(password);
    if (weak) {
      showAuthError("auth-error", weak);
      return;
    }
  }

  const button = $("auth-submit");
  button.disabled = true;
  try {
    const data = await api(authMode === "register" ? "/api/register" : "/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    await enterAccount(data, {
      mergeGuest: true,
      recoveryCode: data.recovery_code || "",
    });
  } catch (err) {
    showAuthError("auth-error", err.message);
  } finally {
    button.disabled = false;
  }
}

async function submitReset(event) {
  event.preventDefault();
  hideAuthError("reset-error");
  const username = $("reset-username").value.trim();
  const recoveryCode = $("reset-code").value.trim();
  const password = $("reset-password").value;
  if (!username || !recoveryCode || !password) {
    showAuthError("reset-error", "请填写用户名、恢复码和新密码");
    return;
  }
  if (password !== $("reset-password2").value) {
    showAuthError("reset-error", "两次输入的新密码不一致");
    return;
  }
  const weak = passwordError(password);
  if (weak) {
    showAuthError("reset-error", weak);
    return;
  }

  const button = $("reset-form").querySelector('button[type="submit"]');
  button.disabled = true;
  button.textContent = "提交中…";
  try {
    const result = await api("/api/account/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username,
        recovery_code: recoveryCode,
        new_password: password,
      }),
    });
    const data = await api("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    $("auth-password").value = password;
    await enterAccount(data, { recoveryCode: result.recovery_code });
  } catch (err) {
    showAuthError("reset-error", err.message);
  } finally {
    button.disabled = false;
    button.textContent = "重置密码";
  }
}

async function logout() {
  try {
    await api("/api/logout", { method: "POST" });
  } catch {}
  clearTimeout(accountSyncTimer);
  state.user = null;
  loadPersonalData();
  refreshAccountUI();
  refreshPersonalUI();
  closeModal("account-modal");
  hideSessionBanner();
}

function openAccount() {
  refreshAccountUI();
  ["pwd-old", "pwd-new", "pwd-new2", "delete-confirm"].forEach((id) => {
    $(id).value = "";
  });
  hideAuthError("password-error");
  hideAuthError("password-success");
  hideAuthError("delete-error");
  hideAuthError("export-status");
  openModal("account-modal");
}

async function submitPassword(event) {
  event.preventDefault();
  hideAuthError("password-error");
  hideAuthError("password-success");
  const oldPassword = $("pwd-old").value;
  const newPassword = $("pwd-new").value;
  if (!oldPassword || !newPassword) {
    showAuthError("password-error", "请填写当前密码和新密码");
    return;
  }
  if (newPassword !== $("pwd-new2").value) {
    showAuthError("password-error", "两次输入的新密码不一致");
    return;
  }
  const weak = passwordError(newPassword);
  if (weak) {
    showAuthError("password-error", weak);
    return;
  }

  const button = $("password-submit");
  button.disabled = true;
  button.textContent = "提交中…";
  try {
    await api("/api/me/password", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
    });
    $("pwd-old").value = "";
    $("pwd-new").value = "";
    $("pwd-new2").value = "";
    showAuthError("password-success", "密码已更新，当前登录状态保持不变。");
  } catch (err) {
    showAuthError("password-error", err.message);
  } finally {
    button.disabled = false;
    button.textContent = "修改密码";
  }
}

function exportData() {
  const payload = {
    exported_at: new Date().toISOString(),
    account: state.user ? { username: state.user.username } : null,
    shelf: [...state.shelf],
    bookmarks: state.bookmarks,
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `novel-data-${new Date().toISOString().slice(0, 10)}.json`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  showAuthError("export-status", "已导出当前书架和书签。");
}

async function deleteAccount() {
  hideAuthError("delete-error");
  const typed = $("delete-confirm").value.trim();
  if (!typed) {
    showAuthError("delete-error", "请输入用户名以确认");
    return;
  }
  if (!state.user || typed !== state.user.username) {
    showAuthError("delete-error", "输入的用户名与当前账户不一致");
    return;
  }

  const button = $("delete-account-btn");
  button.disabled = true;
  button.textContent = "正在注销…";
  try {
    await api("/api/account", { method: "DELETE" });
    clearTimeout(accountSyncTimer);
    state.user = null;
    state.shelf = new Set();
    state.bookmarks = [];
    clearGuestData();
    $("delete-confirm").value = "";
    refreshAccountUI();
    refreshPersonalUI();
    closeModal("account-modal");
    hideSessionBanner();
    location.hash = "#search";
    setHint("账户已注销，本地书架和书签也已清除。");
  } catch (err) {
    showAuthError("delete-error", err.message);
  } finally {
    button.disabled = false;
    button.textContent = "永久注销账户";
  }
}

/* ---------- 事件 ---------- */
const BOLD_KEY = "novel-reader-bold";

function applyBold(enabled) {
  $("reader-body").classList.toggle("bold", enabled);
  $("bold-toggle").classList.toggle("active", enabled);
  $("bold-toggle").setAttribute("aria-pressed", String(enabled));
  try {
    localStorage.setItem(BOLD_KEY, enabled ? "1" : "0");
  } catch {}
}

$("bold-toggle").addEventListener("click", () => {
  applyBold(!$("reader-body").classList.contains("bold"));
});

$("bookmark-toggle").addEventListener("click", toggleBookmark);

let bookmarkFrame = 0;
window.addEventListener("scroll", () => {
  if (bookmarkFrame || !state.reader || $("view-reader").hidden) return;
  bookmarkFrame = requestAnimationFrame(() => {
    bookmarkFrame = 0;
    updateBookmarkButton();
  });
}, { passive: true });

$("search-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const query = $("query").value.trim();
  if (query) doSearch(query, 1);
});

const bookPickerInput = $("book-picker");
bookPickerInput.addEventListener("focus", () => {
  bookPickerInput.select();
  openBookPicker("");
});
bookPickerInput.addEventListener("input", () => {
  if (state.book && bookPickerInput.value !== state.book) state.book = "";
  openBookPicker(bookPickerInput.value.trim());
});
bookPickerInput.addEventListener("blur", () => {
  setTimeout(() => {
    closeBookPicker();
    bookPickerInput.value = state.book;
    bookPickerInput.placeholder = state.book ? "" : "全部书目，可输入书名筛选";
  }, 120);
});
bookPickerInput.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeBookPicker();
    bookPickerInput.value = state.book;
    bookPickerInput.blur();
    return;
  }
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    if (!picker.open) openBookPicker("");
    movePicker(event.key === "ArrowDown" ? 1 : -1);
    return;
  }
  if (event.key === "Enter" && picker.open) {
    const item = picker.items[picker.active >= 0 ? picker.active : 1];
    if (item) {
      event.preventDefault();
      selectBook(item.title);
    }
  }
});

$("library-query").addEventListener("input", (event) => {
  state.libraryQuery = event.target.value.trim();
  state.expandedCategories.clear();
  if (state.library) renderLibrary(state.library);
});

$("session-login-btn").addEventListener("click", () => {
  openAuth("login", $("session-banner").dataset.username || "");
});
$("session-dismiss-btn").addEventListener("click", hideSessionBanner);

$("account-btn").addEventListener("click", () => {
  if (state.user) openAccount();
  else openAuth("login");
});
$("account-close").addEventListener("click", () => closeModal("account-modal"));
$("auth-close").addEventListener("click", closeAuthModal);
$("auth-login-tab").addEventListener("click", () => setAuthMode("login"));
$("auth-register-tab").addEventListener("click", () => setAuthMode("register"));
$("auth-form").addEventListener("submit", submitAuth);
$("auth-reset-link").addEventListener("click", showResetForm);
$("reset-back").addEventListener("click", () => setAuthMode("login"));
$("reset-form").addEventListener("submit", submitReset);
$("recovery-done").addEventListener("click", () => closeModal("recovery-modal"));
$("recovery-close").addEventListener("click", () => closeModal("recovery-modal"));
$("recovery-copy").addEventListener("click", async () => {
  const button = $("recovery-copy");
  try {
    await navigator.clipboard.writeText($("recovery-code").textContent);
    button.textContent = "已复制";
    setTimeout(() => { button.textContent = "复制"; }, 1500);
  } catch {
    button.textContent = "请手动复制";
  }
});
$("logout-btn").addEventListener("click", logout);
$("password-form").addEventListener("submit", submitPassword);
$("export-btn").addEventListener("click", exportData);
$("delete-account-btn").addEventListener("click", deleteAccount);

["auth-username", "auth-password", "auth-confirm"].forEach((id) => {
  $(id).addEventListener("input", () => hideAuthError("auth-error"));
});
["reset-username", "reset-code", "reset-password", "reset-password2"].forEach((id) => {
  $(id).addEventListener("input", () => hideAuthError("reset-error"));
});
["pwd-old", "pwd-new", "pwd-new2"].forEach((id) => {
  $(id).addEventListener("input", () => {
    hideAuthError("password-error");
    hideAuthError("password-success");
  });
});
$("delete-confirm").addEventListener("input", () => hideAuthError("delete-error"));

window.addEventListener("online", updateNetworkBanner);
window.addEventListener("offline", updateNetworkBanner);

window.addEventListener("keydown", (event) => {
  if (event.key !== "Escape" || !modalStack.length) return;
  const top = modalStack[modalStack.length - 1];
  if (top === "auth-modal") closeAuthModal();
  else closeModal(top);
});

$("prev-chapter").addEventListener("click", () => {
  if (state.reader && state.reader.no > 1) {
    location.hash = readHash(state.reader.book, state.reader.no - 1, state.reader.q, 1);
  }
});

$("next-chapter").addEventListener("click", () => {
  if (state.reader) {
    location.hash = readHash(state.reader.book, state.reader.no + 1, state.reader.q, 1);
  }
});

window.addEventListener("hashchange", route);

(async function init() {
  updateNetworkBanner();
  loadPersonalData();
  try {
    applyBold(localStorage.getItem(BOLD_KEY) === "1");
  } catch {
    applyBold(false);
  }
  try {
    const stats = await api("/api/stats");
    $("stats").textContent =
      `已收录 ${stats.books} 部小说 · ${stats.chapters} 回 · ${stats.chars.toLocaleString()} 字`;
  } catch {}
  try {
    state.library = await api("/api/library");
  } catch {}
  try {
    const me = await api("/api/me");
    if (me.user) applyAccountData(me, false);
    else if (me.expired) handleSessionExpired();
  } catch {}
  refreshAccountUI();
  renderBookPicker();
  route();
})();
