// All backend calls go through here. The frontend formats API output; it never calculates.
export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Fixture mode: serve frontend/fixtures/*.json instead of the API.
// NEXT_PUBLIC_FIXTURES=1 is an alias for NEXT_PUBLIC_MOCK=1.
export const MOCK_MODE =
  process.env.NEXT_PUBLIC_MOCK === "1" ||
  process.env.NEXT_PUBLIC_FIXTURES === "1";

// Carries the contract error code (e.g. 409 `backtest_not_ready`) so regions can show honest states.
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
export const errorCode = (err: unknown): string | undefined =>
  err instanceof ApiError ? err.code : undefined;

async function responseBody<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const payload = await res.json().catch(() => null);
    throw new ApiError(
      payload?.error?.message ??
        `Request failed (${res.status}). Please retry.`,
      res.status,
      payload?.error?.code,
    );
  }
  return (await res.json()) as T;
}

export async function apiGet<T>(path: string): Promise<T> {
  if (MOCK_MODE) return (await import("./mock")).mockRequest<T>("GET", path);
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  return responseBody<T>(res);
}

async function send<T>(method: string, path: string, body?: unknown) {
  if (MOCK_MODE)
    return (await import("./mock")).mockRequest<T>(method, path, body);
  const res = await fetch(`${API_URL}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return responseBody<T>(res);
}
export const apiPost = <T>(path: string, body?: unknown) =>
  send<T>("POST", path, body);
export const apiPut = <T>(path: string, body: unknown) =>
  send<T>("PUT", path, body);
// multipart/form-data POST (the browser sets the boundary header itself).
export async function apiUpload<T>(path: string, form: FormData): Promise<T> {
  if (MOCK_MODE)
    return (await import("./mock")).mockRequest<T>("POST", path, form);
  const res = await fetch(`${API_URL}${path}`, { method: "POST", body: form });
  return responseBody<T>(res);
}
