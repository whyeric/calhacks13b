// All backend calls go through here. The frontend formats API output; it never calculates.
export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function responseBody<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const payload = await res.json().catch(() => null);
    throw new Error(
      payload?.error?.message ??
        `Request failed (${res.status}). Please retry.`,
    );
  }
  return (await res.json()) as T;
}

export async function apiGet<T>(path: string): Promise<T> {
  if (process.env.NEXT_PUBLIC_MOCK === "1")
    return (await import("./mock")).mockRequest<T>("GET", path);
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  return responseBody<T>(res);
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  if (process.env.NEXT_PUBLIC_MOCK === "1")
    return (await import("./mock")).mockRequest<T>("POST", path, body);
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return responseBody<T>(res);
}
