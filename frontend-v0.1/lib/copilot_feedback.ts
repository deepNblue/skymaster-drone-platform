/**
 * F4.1 · Copilot v2 turn feedback client.
 */
const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

function token(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('skymaster_token');
}

async function _do<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init?.headers as Record<string, string> | undefined),
  };
  const t = token();
  if (t) headers['Authorization'] = `Bearer ${t}`;
  const res = await fetch(`${API}/api/v1${path}`, { ...init, headers });
  if (res.status === 204) return undefined as unknown as T;
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  }
  return res.json();
}

export type FeedbackRating = 'up' | 'down';

export interface Feedback {
  id: string;
  turn_id: string;
  user_id: string;
  rating: FeedbackRating;
  comment: string | null;
  updated: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface MyFeedback {
  turn_id: string;
  rating: FeedbackRating | null;
  comment?: string | null;
}

export interface TurnStats {
  total: number;
  up: number;
  down: number;
  score: number;
}

export interface NegativeFeedback {
  feedback_id: string;
  turn_id: string;
  session_id: string;
  intent: string | null;
  user_text: string;
  reply_text: string | null;
  comment: string | null;
  created_at: string | null;
}

export interface IntentScore {
  intent: string;
  total: number;
  up: number;
  down: number;
  score: number;
}

export function submitFeedback(
  turn_id: string, rating: FeedbackRating, comment?: string,
): Promise<Feedback> {
  return _do<Feedback>(
    `/copilot/feedback/turns/${encodeURIComponent(turn_id)}`,
    { method: 'POST', body: JSON.stringify({ rating, comment }) },
  );
}

export function clearFeedback(turn_id: string): Promise<void> {
  return _do<void>(
    `/copilot/feedback/turns/${encodeURIComponent(turn_id)}`,
    { method: 'DELETE' },
  );
}

export function getMyFeedback(turn_id: string): Promise<MyFeedback> {
  return _do<MyFeedback>(
    `/copilot/feedback/turns/${encodeURIComponent(turn_id)}/me`,
  );
}

export function getTurnStats(turn_id: string): Promise<TurnStats> {
  return _do<TurnStats>(
    `/copilot/feedback/turns/${encodeURIComponent(turn_id)}/stats`,
  );
}

export function getRecentNegative(opts?: {
  limit?: number; intent?: string;
}): Promise<NegativeFeedback[]> {
  const p = new URLSearchParams();
  if (opts?.limit != null) p.set('limit', String(opts.limit));
  if (opts?.intent) p.set('intent', opts.intent);
  const qs = p.toString();
  return _do<NegativeFeedback[]>(
    `/copilot/feedback/recent-negative${qs ? '?' + qs : ''}`,
  );
}

export function getIntentScoreboard(
  min_total = 3,
): Promise<IntentScore[]> {
  return _do<IntentScore[]>(
    `/copilot/feedback/intent-scoreboard?min_total=${min_total}`,
  );
}

// -- Pure helpers ------------------------------------------------

/** Toggle: current rating == new → clear; else set. */
export async function toggleFeedback(
  turn_id: string, current: FeedbackRating | null,
  next: FeedbackRating, comment?: string,
): Promise<{ rating: FeedbackRating | null }> {
  if (current === next && !comment) {
    await clearFeedback(turn_id);
    return { rating: null };
  }
  await submitFeedback(turn_id, next, comment);
  return { rating: next };
}

/** Classify an intent score into 差/一般/好 for UI badges. */
export function scoreTier(
  score: number,
): { label: string; color: string } {
  if (score >= 0.5) return { label: '好', color: 'green' };
  if (score >= 0) return { label: '一般', color: 'gold' };
  return { label: '差', color: 'red' };
}

/** Approval ratio [0..1]; NaN-safe. */
export function approvalRate(s: TurnStats): number {
  return s.total > 0 ? s.up / s.total : 0;
}

/** Format score for display, always with sign. */
export function formatScore(score: number): string {
  const pct = Math.round(score * 100);
  return `${pct > 0 ? '+' : ''}${pct}%`;
}
