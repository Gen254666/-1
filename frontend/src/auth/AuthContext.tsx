import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import {
  apiGet,
  login as loginApi,
  loadCurrentUser,
  logout as logoutApi,
  setAccessToken,
} from "../api/client";
import type { User } from "../api/types";
import {
  idleTimeoutMinutes,
  readLastActivity,
  shouldIdleLogout,
  touchActivity,
} from "../utils/idleTimeout";

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<User>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadCurrentUser()
      .then((current) => setUser(current))
      .finally(() => setLoading(false));
  }, []);

  const login = async (username: string, password: string) => {
    const result = await loginApi(username, password);
    setUser(result.user);
    return result.user;
  };

  const logout = useCallback(async () => {
    try {
      await logoutApi();
    } finally {
      setAccessToken(null);
      setUser(null);
    }
  }, []);

  useEffect(() => {
    if (!user) return;
    touchActivity(window.localStorage);
    const activityEvents = [
      "mousemove",
      "keydown",
      "click",
      "touchstart",
      "wheel",
      "scroll",
    ];
    const resetActivity = () => {
      touchActivity(window.localStorage);
    };
    activityEvents.forEach((event) =>
      window.addEventListener(event, resetActivity, { passive: true }),
    );
    const timer = window.setInterval(() => {
      if (
        shouldIdleLogout(
          readLastActivity(window.localStorage),
          Date.now(),
          idleTimeoutMinutes(),
        )
      ) {
        void logout();
      }
    }, 30_000);
    return () => {
      activityEvents.forEach((event) =>
        window.removeEventListener(event, resetActivity),
      );
      window.clearInterval(timer);
    };
  }, [user, logout]);

  const refreshUser = async () => {
    const current = await apiGet<User>("/api/auth/me");
    setUser(current);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
