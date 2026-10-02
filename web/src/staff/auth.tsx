import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, ApiError, resolveApiUrl } from "../api";

export interface StaffUser {
  email: string;
  name: string;
  roles: string[];
  languages: string[];
}

interface Auth {
  token: string | null;
  user: StaffUser | null;
  login: (email: string, password: string) => Promise<void>;
  /** Demo only: the read-only judge account, when the server has judge access switched on. */
  loginAsJudge: () => Promise<void>;
  logout: () => void;
  can: (role: string) => boolean;
}

const Ctx = createContext<Auth | null>(null);
const KEY = "archive-staff-token";

export function StaffAuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => sessionStorage.getItem(KEY));
  const [user, setUser] = useState<StaffUser | null>(null);

  useEffect(() => {
    if (!token) return;
    api.get<StaffUser>("/api/staff/me", token).then(setUser).catch((e: ApiError) => {
      if (e.status === 401) {
        sessionStorage.removeItem(KEY);
        setToken(null);
      }
    });
  }, [token]);

  const signedIn = (r: { token: string; user: StaffUser }) => {
    sessionStorage.setItem(KEY, r.token);
    setToken(r.token);
    setUser(r.user);
  };
  const value: Auth = {
    token,
    user,
    login: async (email, password) => {
      signedIn(await api.post<{ token: string; user: StaffUser }>("/api/staff/login", { email, password }));
    },
    loginAsJudge: async () => {
      signedIn(await api.post<{ token: string; user: StaffUser }>("/api/staff/login/judge", {}));
    },
    logout: () => {
      sessionStorage.removeItem(KEY);
      setToken(null);
      setUser(null);
    },
    can: (role) => Boolean(user?.roles.includes(role) || user?.roles.includes("admin")),
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStaff(): Auth {
  const a = useContext(Ctx);
  if (!a) throw new Error("StaffAuthProvider missing");
  return a;
}

/** Staff file routes need the bearer token, so images are fetched as blobs. */
export function useAuthedObjectUrl(path: string | null): string | null {
  const { token } = useStaff();
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!path || !token) return;
    let revoke: string | null = null;
    let live = true;
    fetch(resolveApiUrl(path), { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => (r.ok ? r.blob() : Promise.reject(r.status)))
      .then((b) => {
        if (!live) return;
        revoke = URL.createObjectURL(b);
        setUrl(revoke);
      })
      .catch(() => live && setUrl(null));
    return () => {
      live = false;
      if (revoke) URL.revokeObjectURL(revoke);
    };
  }, [path, token]);
  return url;
}
