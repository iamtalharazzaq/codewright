import pg from "pg";
import type { Item, Store, User } from "./store.js";

const SCHEMA = `
CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  is_admin BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE TABLE IF NOT EXISTS items (
  id SERIAL PRIMARY KEY,
  owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  done BOOLEAN NOT NULL DEFAULT FALSE
);`;

type UserRow = { id: number; email: string; password_hash: string; is_admin: boolean };
type ItemRow = { id: number; owner_id: number; name: string; done: boolean };

const toUser = (r: UserRow): User => ({ id: r.id, email: r.email, passwordHash: r.password_hash, isAdmin: r.is_admin });
const toItem = (r: ItemRow): Item => ({ id: r.id, ownerId: r.owner_id, name: r.name, done: r.done });

export class PostgresStore implements Store {
  private constructor(private pool: pg.Pool) {}

  /** Connects and creates the tables when they are missing. */
  static async open(url: string): Promise<PostgresStore> {
    const pool = new pg.Pool({ connectionString: url });
    await pool.query(SCHEMA);
    return new PostgresStore(pool);
  }

  async close(): Promise<void> {
    await this.pool.end();
  }

  async createUser(email: string, passwordHash: string) {
    const res = await this.pool.query<UserRow>(
      `INSERT INTO users (email, password_hash, is_admin) VALUES ($1, $2, NOT EXISTS (SELECT 1 FROM users))
       ON CONFLICT (email) DO NOTHING RETURNING id, email, password_hash, is_admin`,
      [email, passwordHash],
    );
    return res.rows[0] && toUser(res.rows[0]);
  }

  async userByEmail(email: string) {
    const res = await this.pool.query<UserRow>("SELECT id, email, password_hash, is_admin FROM users WHERE email = $1", [email]);
    return res.rows[0] && toUser(res.rows[0]);
  }

  async userById(id: number) {
    const res = await this.pool.query<UserRow>("SELECT id, email, password_hash, is_admin FROM users WHERE id = $1", [id]);
    return res.rows[0] && toUser(res.rows[0]);
  }

  async listUsers() {
    const res = await this.pool.query<UserRow>("SELECT id, email, password_hash, is_admin FROM users ORDER BY id");
    return res.rows.map(toUser);
  }

  async listItems(ownerId: number) {
    const res = await this.pool.query<ItemRow>("SELECT id, owner_id, name, done FROM items WHERE owner_id = $1 ORDER BY id", [ownerId]);
    return res.rows.map(toItem);
  }

  async createItem(ownerId: number, name: string) {
    const res = await this.pool.query<ItemRow>(
      "INSERT INTO items (owner_id, name) VALUES ($1, $2) RETURNING id, owner_id, name, done",
      [ownerId, name],
    );
    return toItem(res.rows[0]);
  }

  async updateItem(ownerId: number, id: number, name: string, done: boolean) {
    const res = await this.pool.query<ItemRow>(
      "UPDATE items SET name = $1, done = $2 WHERE id = $3 AND owner_id = $4 RETURNING id, owner_id, name, done",
      [name, done, id, ownerId],
    );
    return res.rows[0] && toItem(res.rows[0]);
  }

  async deleteItem(ownerId: number, id: number) {
    const res = await this.pool.query("DELETE FROM items WHERE id = $1 AND owner_id = $2", [id, ownerId]);
    return (res.rowCount ?? 0) > 0;
  }
}
