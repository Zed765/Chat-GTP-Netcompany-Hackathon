// A to-do list kept in the browser's local storage, with filtering and undo.

const STORAGE_KEY = "todo-items-v1";

class TodoStore {
  constructor(storage = window.localStorage) {
    this.storage = storage;
    this.items = this.load();
    this.undoStack = [];
    this.listeners = new Set();
  }

  load() {
    try {
      return JSON.parse(this.storage.getItem(STORAGE_KEY)) ?? [];
    } catch (error) {
      console.warn("Could not read saved items", error);
      return [];
    }
  }

  save() {
    this.storage.setItem(STORAGE_KEY, JSON.stringify(this.items));
    this.listeners.forEach((listener) => listener(this.items));
  }

  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  snapshot() {
    this.undoStack.push(JSON.stringify(this.items));
    if (this.undoStack.length > 20) this.undoStack.shift();
  }

  add(title, dueDate = null) {
    const trimmed = title.trim();
    if (!trimmed) throw new Error("A task needs a title");
    this.snapshot();
    this.items.push({ id: crypto.randomUUID(), title: trimmed, done: false, dueDate });
    this.save();
  }

  toggle(id) {
    this.snapshot();
    this.items = this.items.map((item) => (item.id === id ? { ...item, done: !item.done } : item));
    this.save();
  }

  remove(id) {
    this.snapshot();
    this.items = this.items.filter((item) => item.id !== id);
    this.save();
  }

  clearCompleted() {
    this.snapshot();
    this.items = this.items.filter((item) => !item.done);
    this.save();
  }

  undo() {
    const previous = this.undoStack.pop();
    if (!previous) return false;
    this.items = JSON.parse(previous);
    this.save();
    return true;
  }

  filter(view) {
    const today = new Date().toISOString().slice(0, 10);
    switch (view) {
      case "active":
        return this.items.filter((item) => !item.done);
      case "completed":
        return this.items.filter((item) => item.done);
      case "overdue":
        return this.items.filter((item) => !item.done && item.dueDate && item.dueDate < today);
      default:
        return [...this.items];
    }
  }

  rename(id, title) {
    const trimmed = title.trim();
    if (!trimmed) throw new Error("A task needs a title");
    this.snapshot();
    this.items = this.items.map((item) => (item.id === id ? { ...item, title: trimmed } : item));
    this.save();
  }

  sortByDueDate() {
    this.snapshot();
    this.items.sort((a, b) => (a.dueDate ?? "9999").localeCompare(b.dueDate ?? "9999"));
    this.save();
  }

  get remaining() {
    return this.items.filter((item) => !item.done).length;
  }
}

function render(store, list, counter, view = "all") {
  list.replaceChildren(
    ...store.filter(view).map((item) => {
      const row = document.createElement("li");
      row.textContent = item.title;
      row.classList.toggle("done", item.done);
      row.addEventListener("click", () => store.toggle(item.id));
      return row;
    }),
  );
  counter.textContent = `${store.remaining} left`;
}

export { TodoStore, render };
