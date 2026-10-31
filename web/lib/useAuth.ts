"use client";

import { useEffect, useState } from "react";
import { api, type AuthConfig, type User } from "./api";

/** ระบบบัญชีเปิดอยู่ไหม และใครล็อกอินอยู่ (config = null ระหว่างโหลด) */
export function useAuth() {
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [loaded, setLoaded] = useState(false);

  const reload = async () => {
    try {
      const c = await api.authConfig();
      setConfig(c);
      setUser(c.auth ? await api.me().catch(() => null) : null);
    } catch {
      setConfig({ auth: false, billing: false, payments: false });
    } finally { setLoaded(true); }
  };

  useEffect(() => { reload(); }, []);
  return { config, user, loaded, reload };
}
