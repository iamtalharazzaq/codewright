export interface User {
  id: number;
  email: string;
  passwordHash: string;
  isAdmin: boolean;
}

export interface Item {
  id: number;
  ownerId: number;
  name: string;
  done: boolean;
}

/** Where users and items live: in memory (tests, quick tries) or in PostgreSQL (see pgstore.ts). */
export interface Store {
  /** Adds a user (the very first one becomes the admin); undefined when the email is taken. */
  createUser(email: string, passwordHash: string): Promise<User | undefined>;
  userByEmail(email: string): Promise<User | undefined>;
  userById(id: number): Promise<User | undefined>;
  listUsers(): Promise<User[]>;
  listItems(ownerId: number): Promise<Item[]>;
  createItem(ownerId: number, name: string): Promise<Item>;
  updateItem(ownerId: number, id: number, name: string, done: boolean): Promise<Item | undefined>;
  deleteItem(ownerId: number, id: number): Promise<boolean>;
}

export class MemoryStore implements Store {
  private users: User[] = [];
  private items = new Map<number, Item>();
  private nextItem = 1;

  async createUser(email: string, passwordHash: string) {
    if (this.users.some((u) => u.email === email)) return undefined;
    const user = { id: this.users.length + 1, email, passwordHash, isAdmin: this.users.length === 0 };
    this.users.push(user);
    return user;
  }

  async userByEmail(email: string) {
    return this.users.find((u) => u.email === email);
  }

  async userById(id: number) {
    return this.users.find((u) => u.id === id);
  }

  async listUsers() {
    return [...this.users];
  }

  async listItems(ownerId: number) {
    return [...this.items.values()].filter((i) => i.ownerId === ownerId).sort((a, b) => a.id - b.id);
  }

  async createItem(ownerId: number, name: string) {
    const item = { id: this.nextItem++, ownerId, name, done: false };
    this.items.set(item.id, item);
    return item;
  }

  async updateItem(ownerId: number, id: number, name: string, done: boolean) {
    const item = this.items.get(id);
    if (!item || item.ownerId !== ownerId) return undefined;
    const saved = { ...item, name, done };
    this.items.set(id, saved);
    return saved;
  }

  async deleteItem(ownerId: number, id: number) {
    const item = this.items.get(id);
    if (!item || item.ownerId !== ownerId) return false;
    return this.items.delete(id);
  }
}
