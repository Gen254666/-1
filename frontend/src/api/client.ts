import type { User } from "./types";

let accessToken: string | null = null;
let refreshPromise: Promise<boolean> | null = null;

export class ApiError extends Error {
  code: string;
  status: number;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

export async function refreshAccessToken(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = fetch("/api/auth/refresh", {
      method: "POST",
      credentials: "include",
    })
      .then(async (response) => {
        if (!response.ok) return false;
        const data = await response.json();
        accessToken = data.access_token;
        return true;
      })
      .catch(() => false)
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

async function request(
  path: string,
  options: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(options.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const send = () =>
    fetch(path, { ...options, headers, credentials: "include" });

  let response = await send();
  if (response.status === 401 && accessToken) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      headers.set("Authorization", `Bearer ${accessToken}`);
      response = await send();
    }
  }

  if (!response.ok) {
    let code = "REQUEST_FAILED";
    let message = `请求失败 (${response.status})`;
    try {
      const payload = await response.json();
      code = payload.code ?? code;
      message = payload.message ?? message;
    } catch {
      // keep defaults
    }
    throw new ApiError(response.status, code, message);
  }
  return response;
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await request(path);
  return (await response.json()) as T;
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const response = await request(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return (await response.json()) as T;
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const response = await request(path, {
    method: "PUT",
    body: JSON.stringify(body),
  });
  return (await response.json()) as T;
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const response = await request(path, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
  return (await response.json()) as T;
}

export async function apiDelete(path: string): Promise<void> {
  await request(path, { method: "DELETE" });
}

export async function uploadFile<T>(
  path: string,
  file: File,
  fields: Record<string, string> = {},
): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  for (const [key, value] of Object.entries(fields)) form.append(key, value);
  const response = await request(path, { method: "POST", body: form });
  return (await response.json()) as T;
}

export async function login(
  username: string,
  password: string,
): Promise<{ access_token: string; user: User }> {
  const response = await request("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  const data = await response.json();
  accessToken = data.access_token;
  return data;
}

export async function logout(): Promise<void> {
  await request("/api/auth/logout", { method: "POST" });
  accessToken = null;
}

export async function loadCurrentUser(): Promise<User | null> {
  const refreshed = await refreshAccessToken();
  if (!refreshed) return null;
  try {
    return await apiGet<User>("/api/auth/me");
  } catch {
    return null;
  }
}

export interface ChatHandlers {
  onEvent: (event: string, data: any) => void;
}

export async function streamChat(
  message: string,
  sessionId: string | null,
  handlers: ChatHandlers,
): Promise<void> {
  const response = await request("/api/chat/stream", {
    method: "POST",
    body: JSON.stringify({ message, session_id: sessionId }),
  });
  if (!response.body) throw new Error("流式响应不可用");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      let event = "message";
      let data: any = null;
      for (const line of part.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7).trim();
        if (line.startsWith("data: ")) {
          try {
            data = JSON.parse(line.slice(6));
          } catch {
            data = line.slice(6);
          }
        }
      }
      if (data !== null) handlers.onEvent(event, data);
    }
  }
}
