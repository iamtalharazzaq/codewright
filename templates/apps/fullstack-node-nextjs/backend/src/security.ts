import { createHmac, randomBytes, scryptSync, timingSafeEqual } from "node:crypto";

export const TOKEN_SECONDS = 7 * 24 * 3600;

/** "salt$hash" (both hex). */
export function hashPassword(password: string): string {
  const salt = randomBytes(16);
  return `${salt.toString("hex")}$${scryptSync(password, salt, 32).toString("hex")}`;
}

export function checkPassword(password: string, stored: string): boolean {
  const [saltHex, hashHex] = stored.split("$");
  if (!saltHex || !hashHex) return false;
  const expected = Buffer.from(hashHex, "hex");
  const actual = scryptSync(password, Buffer.from(saltHex, "hex"), expected.length);
  return actual.length === expected.length && timingSafeEqual(actual, expected);
}

const sign = (secret: string, payload: string): string => createHmac("sha256", secret).update(payload).digest("hex");

export function makeToken(secret: string, userId: number, now = Date.now() / 1000): string {
  const payload = Buffer.from(JSON.stringify({ sub: userId, exp: Math.floor(now + TOKEN_SECONDS) })).toString("base64url");
  return `${payload}.${sign(secret, payload)}`;
}

/** The user id in a valid, unexpired token; undefined otherwise. */
export function readToken(secret: string, token: string, now = Date.now() / 1000): number | undefined {
  const [payload, signature] = token.split(".");
  if (!payload || !signature) return undefined;
  const expected = sign(secret, payload);
  if (signature.length !== expected.length || !timingSafeEqual(Buffer.from(signature), Buffer.from(expected))) return undefined;
  try {
    const claims = JSON.parse(Buffer.from(payload, "base64url").toString()) as { sub?: unknown; exp?: unknown };
    if (typeof claims.sub !== "number" || typeof claims.exp !== "number" || claims.exp < now) return undefined;
    return claims.sub;
  } catch {
    return undefined;
  }
}
