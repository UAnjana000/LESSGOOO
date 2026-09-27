import { useCallback, useEffect, useState } from "react";
import { api, ApiError, apiErrorFromBody } from "./api";

export interface Loaded<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  offline: boolean;
  reload: () => void;
}

export function useApi<T>(path: string | null, token?: string | null): Loaded<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const [offline, setOffline] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!path) return;
    let live = true;
    setLoading(true);
    setError(null);
    fetch(path, token ? { headers: { Authorization: `Bearer ${token}` } } : {})
      .then(async (res) => {
        const fromCache = res.headers.get("x-archive-offline") === "1";
        if (!res.ok) {
          try {
            throw apiErrorFromBody(res.status, await res.json(), fromCache);
          } catch (e) {
            if (e instanceof ApiError) throw e;
            throw new ApiError(res.status, res.statusText, fromCache);
          }
        }
        const body = (await res.json()) as T;
        if (live) {
          setData(body);
          setOffline(fromCache);
        }
      })
      .catch((e: unknown) => {
        if (live) setError(e instanceof ApiError ? e : new ApiError(0, "offline", true));
      })
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [path, token, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, offline, reload };
}

export { api };

export function formatMs(ms: number): string {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
