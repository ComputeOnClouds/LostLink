import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiClient, MatchSuggestion, Report } from './api';

const POLL_INTERVAL_MS = 4_000;
const POLL_WINDOW_MS = 60_000;

export function useReportMatches(api: ApiClient) {
  const [reports, setReports] = useState<Report[] | null>(null);
  const [matches, setMatches] = useState<MatchSuggestion[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pollUntil, setPollUntil] = useState(0);
  const request = useRef<AbortController | null>(null);
  // The owner index can briefly omit a new report or return its pre-edit revision.
  const awaitingReports = useRef(new Map<string, number>());

  const refresh = useCallback(async (afterWrite = false) => {
    if (request.current) {
      if (!afterWrite) return;
      request.current.abort();
    }
    const controller = new AbortController();
    const { signal } = controller;
    request.current = controller;
    let refreshError: string | null = null;
    let searching: boolean | undefined;
    try {
      const result = await api.listReports(signal);
      if (signal.aborted) return;
      for (const report of result.reports) {
        const revision = awaitingReports.current.get(report.itemId);
        if (revision !== undefined && report.revision >= revision) {
          awaitingReports.current.delete(report.itemId);
        }
      }
      setReports(result.reports);
      searching = awaitingReports.current.size > 0
        || result.reports.some((report) => report.status === 'pending_match');
      if (searching) {
        const deadline = Date.now() + POLL_WINDOW_MS;
        setPollUntil((until) => until || deadline);
      }
    } catch (err) {
      if (signal.aborted) return;
      refreshError = err instanceof Error ? err.message : 'Please try again.';
    }

    try {
      // Read matches after the report status, so a completed job gets a final match read.
      const result = await api.listMatches(signal);
      if (signal.aborted) return;
      setMatches(result.matches);
      if (searching === false) setPollUntil(0);
    } catch (err) {
      if (signal.aborted) return;
      refreshError ??= err instanceof Error ? err.message : 'Please try again.';
    }
    request.current = null;
    setError(refreshError);
  }, [api]);

  const watchReport = useCallback((itemId: string, revision = 0) => {
    awaitingReports.current.set(itemId, revision);
    setPollUntil(Date.now() + POLL_WINDOW_MS);
    return refresh(true);
  }, [refresh]);

  useEffect(() => {
    void refresh();
    function refreshWhenVisible() {
      if (!document.hidden) void refresh();
    }
    document.addEventListener('visibilitychange', refreshWhenVisible);
    return () => {
      document.removeEventListener('visibilitychange', refreshWhenVisible);
      request.current?.abort();
      request.current = null;
    };
  }, [refresh]);

  useEffect(() => {
    if (!pollUntil || Date.now() >= pollUntil) return;
    const timer = window.setInterval(() => {
      if (Date.now() >= pollUntil) {
        awaitingReports.current.clear();
        window.clearInterval(timer);
      } else if (!document.hidden) {
        void refresh();
      }
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [pollUntil, refresh]);

  return { reports, matches, error, refresh, watchReport };
}
