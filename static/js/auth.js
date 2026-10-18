// Session state: one place that knows who is signed in.

import { api } from "./api.js";

let ME = null;

export const me = () => ME;

export async function refresh() {
  try {
    const r = await api("/api/me");
    ME = r.user;
  } catch {
    ME = null;
  }
  return ME;
}

export async function login(username, password) {
  const r = await api("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  ME = r.user;
  return ME;
}

export async function register(payload) {
  const r = await api("/api/auth/register", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  ME = r.user;
  return ME;
}

export async function logout() {
  try {
    await api("/api/auth/logout", { method: "POST" });
  } finally {
    ME = null;
  }
}

export async function myLogins() {
  const r = await api("/api/me/logins");
  return r.logins || [];
}
