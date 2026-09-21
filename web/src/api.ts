export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public requestId = "",
  ) {
    super(message);
  }
}
export function errorText(error: unknown) {
  return error instanceof Error ? error.message : "操作失敗，請稍後重試";
}
export function detailText(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail
      .map(
        (x) =>
          `${Array.isArray(x.loc) ? x.loc.slice(1).join(".") : "欄位"}：${x.msg || "格式不正確"}`,
      )
      .join("；");
  return "請求失敗，請重新整理後重試";
}
export async function request<T>(
  path: string,
  method = "GET",
  body?: unknown,
  options?: { csrf?: string; token?: string; signal?: AbortSignal },
): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (options?.csrf) headers["X-CSRF-Token"] = options.csrf;
  if (options?.token) headers.Authorization = `Bearer ${options.token}`;
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: options?.token ? "omit" : "same-origin",
      signal: options?.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new ApiError(0, "無法連線，請檢查服務是否啟動；重試不會丟失輸入");
  }
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401 && !options?.token && path != "/v1/auth/login")
      window.dispatchEvent(new Event("kcs:session-expired"));
    throw new ApiError(
      response.status,
      detailText(data?.detail),
      response.headers.get("X-Request-ID") || data?.request_id || "",
    );
  }
  if (data === null) throw new ApiError(response.status, "服務回傳格式錯誤");
  return data as T;
}
