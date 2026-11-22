// Small fetch layer. A 401 means the phone session expired: go to the PIN screen.

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { credentials: "same-origin", ...init });
  if (res.status === 401) {
    window.location.href = "/login";
    throw new ApiError("login required", 401);
  }
  const text = await res.text();
  const body = text ? JSON.parse(text) : {};
  if (!res.ok) throw new ApiError(body.error || `Request failed (${res.status})`, res.status);
  return body as T;
}

export const postJson = <T>(path: string, data: unknown) =>
  api<T>(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(data) });

export type Me = { name: string; spoken: string; user: string; address: string; local: boolean; voice: boolean };
export type Task = { id: number; source: string; title: string; due: string | null; status: string; points: string | null; link: string | null };
export type Connector = { ok: boolean; detail: string };
export type Status = { name: string; user: string; connectors: Record<string, Connector> };
export type SettingsView = {
  fields: Record<string, string | number | boolean | string[] | null>;
  secrets: Record<string, boolean>;
  oauth_client_present: boolean;
  discord_invite_url: string | null;
  phone_url: string | null;
};

// The Android app injects `HavocNative` into the page. It's absent in browsers and the desktop app.
export type HavocNative = {
  openSettings(): void;
  isWakeEnabled(): boolean;
  setWakeEnabled(on: boolean): void;
  appVersion(): string;
};
export const native = (): HavocNative | undefined => (window as unknown as { HavocNative?: HavocNative }).HavocNative;
