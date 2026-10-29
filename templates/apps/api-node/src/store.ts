export interface Item {
  id: number;
  name: string;
  done: boolean;
}

/** Where items live. Swap `MemoryStore` for a database-backed class with the same methods. */
export interface Store {
  list(): Item[];
  get(id: number): Item | undefined;
  create(name: string): Item;
  update(id: number, name: string, done: boolean): Item | undefined;
  remove(id: number): boolean;
}

export class MemoryStore implements Store {
  private next = 1;
  private items = new Map<number, Item>();

  list(): Item[] {
    return [...this.items.values()].sort((a, b) => a.id - b.id);
  }

  get(id: number): Item | undefined {
    return this.items.get(id);
  }

  create(name: string): Item {
    const item = { id: this.next++, name, done: false };
    this.items.set(item.id, item);
    return item;
  }

  update(id: number, name: string, done: boolean): Item | undefined {
    if (!this.items.has(id)) return undefined;
    const item = { id, name, done };
    this.items.set(id, item);
    return item;
  }

  remove(id: number): boolean {
    return this.items.delete(id);
  }
}
