"use client";

import React, {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { encodeBase64 } from "@/lib/utils";

interface User {
  user_id: string;
  email: string;
  name: string;
  picture?: string;
  provider: string;
  last_login?: string;
}

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  isNoAuthMode: boolean;
  isIbmAuthMode: boolean;
  version: string | null;
  login: () => void;
  loginWithIbm: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshAuth: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}

interface AuthProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isNoAuthMode, setIsNoAuthMode] = useState(false);
  const [isIbmAuthMode, setIsIbmAuthMode] = useState(false);
  const [version, setVersion] = useState<string | null>(null);

  const checkAuth = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await fetch("/api/auth/me");

      // If we can't reach the backend, keep loading
      if (!response.ok && (response.status === 0 || response.status >= 500)) {
        setTimeout(checkAuth, 2000);
        return;
      }

      const data = await response.json();
      if (data.version) setVersion(data.version);

      // Check auth mode flags
      if (data.ibm_auth_mode) {
        setIsIbmAuthMode(true);
        setIsNoAuthMode(false);
        setUser(data.authenticated && data.user ? data.user : null);
      } else if (data.no_auth_mode) {
        setIsNoAuthMode(true);
        setIsIbmAuthMode(false);
        setUser(null);
      } else if (data.authenticated && data.user) {
        setIsNoAuthMode(false);
        setIsIbmAuthMode(false);
        setUser(data.user);
      } else {
        setIsNoAuthMode(false);
        setIsIbmAuthMode(false);
        setUser(null);
      }

      setIsLoading(false);
    } catch (error) {
      console.error("Auth check failed:", error);
      setTimeout(checkAuth, 2000);
    }
  }, []);

  const login = () => {
    // Don't allow login in no-auth mode or IBM auth mode
    if (isNoAuthMode) {
      return;
    }
    if (isIbmAuthMode) {
      return;
    }

    // Use the correct auth callback URL, not connectors callback
    const redirectUri = `${window.location.origin}/auth/callback`;

    fetch("/api/auth/init", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        connector_type: "google_drive",
        purpose: "app_auth",
        name: "App Authentication",
        redirect_uri: redirectUri,
      }),
    })
      .then((response) => response.json())
      .then((result) => {
        if (result.oauth_config) {
          // Store that this is for app authentication
          localStorage.setItem("auth_purpose", "app_auth");
          localStorage.setItem("connecting_connector_id", result.connection_id);
          localStorage.setItem("connecting_connector_type", "app_auth");
          localStorage.setItem("auth_redirect_to", window.location.pathname);

          const state = isIbmAuthMode
            ? encodeBase64(
                `id=${result.connection_id}&return=${window.location.origin}/auth/callback`,
              )
            : result.connection_id;

          const authUrl =
            `${result.oauth_config.authorization_endpoint}?` +
            `client_id=${result.oauth_config.client_id}&` +
            `response_type=code&` +
            `scope=${result.oauth_config.scopes.join(" ")}&` +
            `redirect_uri=${encodeURIComponent(result.oauth_config.redirect_uri)}&` +
            `access_type=offline&` +
            `prompt=select_account&` +
            `state=${encodeURIComponent(state)}`;
          window.location.href = authUrl;
        } else {
          console.error("No oauth_config in response:", result);
        }
      })
      .catch((error) => {
        console.error("Login failed:", error);
      });
  };

  const loginWithIbm = async (username: string, password: string) => {
    const response = await fetch("/api/auth/ibm/login", {
      method: "POST",
      headers: {
        Authorization: "Basic " + btoa(username + ":" + password),
      },
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || "Login failed");
    }
    await checkAuth();
  };

  const logout = async () => {
    if (isNoAuthMode) {
      return;
    }

    try {
      await fetch("/api/auth/logout", {
        method: "POST",
      });
      setUser(null);
    } catch (error) {
      console.error("Logout failed:", error);
    }
  };

  const refreshAuth = async () => {
    await checkAuth();
  };

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  const value: AuthContextType = {
    user,
    isLoading,
    isAuthenticated: !!user,
    isNoAuthMode,
    isIbmAuthMode,
    version,
    login,
    loginWithIbm,
    logout,
    refreshAuth,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
