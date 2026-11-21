import { create } from 'zustand';

interface User {
  id?: string;
  email?: string;
  name?: string;
  role?: string;
  org_id?: string | null;
  is_active?: boolean;
}

interface AuthState {
  token: string | null;
  user: User | null;
  setToken: (token: string | null) => void;
  setUser: (user: User | null) => void;
  clear: () => void;
  /** Returns true iff current user role >= requiredRole (rbac ordering). */
  hasRole: (required: 'viewer' | 'operator' | 'admin') => boolean;
}

const ROLE_ORDER: Record<string, number> = {
  viewer: 1,
  operator: 2,
  admin: 3,
};

// -------- localStorage helpers with SSR safety --------
const readLS = (k: string): string | null =>
  typeof window !== 'undefined' ? localStorage.getItem(k) : null;
const writeLS = (k: string, v: string | null) => {
  if (typeof window === 'undefined') return;
  if (v == null) localStorage.removeItem(k);
  else localStorage.setItem(k, v);
};

const _parseUser = (raw: string | null): User | null => {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as User;
  } catch {
    return null;
  }
};

/** Decode JWT `sub`/`role`/`org` claims — no cryptographic verify (server did that). */
export function decodeJwtPayload(token: string): Record<string, any> | null {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    const b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    const padded = b64 + '='.repeat((4 - (b64.length % 4)) % 4);
    return JSON.parse(atob(padded));
  } catch {
    return null;
  }
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: readLS('access_token'),
  user: _parseUser(readLS('user_profile')),
  setToken: (token) => {
    writeLS('access_token', token);
    // Auto-populate user from JWT if profile hasn't been fetched yet.
    if (token) {
      const claims = decodeJwtPayload(token);
      if (claims) {
        const stored = get().user;
        const merged: User = {
          id: claims.sub ?? stored?.id,
          email: claims.email ?? stored?.email,
          role: claims.role ?? stored?.role,
          org_id: claims.org_id ?? stored?.org_id,
          ...stored,
        };
        writeLS('user_profile', JSON.stringify(merged));
        set({ token, user: merged });
        return;
      }
    }
    set({ token });
  },
  setUser: (user) => {
    writeLS('user_profile', user ? JSON.stringify(user) : null);
    set({ user });
  },
  clear: () => {
    writeLS('access_token', null);
    writeLS('user_profile', null);
    set({ token: null, user: null });
  },
  hasRole: (required) => {
    const u = get().user;
    if (!u?.role) return false;
    return (ROLE_ORDER[u.role] ?? 0) >= (ROLE_ORDER[required] ?? 99);
  },
}));
