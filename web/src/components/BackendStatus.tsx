import { useEffect, useState } from 'react';
import { useI18n } from '../i18n';
import { fetchHealth, readRuntimeState } from '../lib/backend';

type StatusState =
  | { kind: 'loading' }
  | { kind: 'connected'; baseUrl: string }
  | { kind: 'failed'; message: string };

export function BackendStatus() {
  const { t } = useI18n();
  const [state, setState] = useState<StatusState>({ kind: 'loading' });

  useEffect(() => {
    let cancelled = false;
    let retries = 0;
    const maxRetries = 30; // 30 x 1s = 30s max wait

    async function tryConnect() {
      const runtime = await readRuntimeState();

      if (!runtime) {
        return false;
      }

      try {
        await fetchHealth(runtime.baseUrl);
        if (!cancelled) {
          setState({ kind: 'connected', baseUrl: runtime.baseUrl });
        }
        return true;
      } catch {
        return false;
      }
    }

    async function poll() {
      while (retries < maxRetries && !cancelled) {
        const ok = await tryConnect();
        if (ok || cancelled) {
          return;
        }
        retries++;
        // Wait 1s before retrying
        await new Promise((r) => setTimeout(r, 1000));
      }

      if (!cancelled) {
        setState({ kind: 'failed', message: t('backend.healthCheckFailed') });
      }
    }

    void poll();

    return () => {
      cancelled = true;
    };
  }, [t]);

  if (state.kind === 'loading') {
    return <div className="backend-status">{t('backend.loading')}</div>;
  }

  if (state.kind === 'failed') {
    return <div className="backend-status failed">{t('backend.failed')}</div>;
  }

  return <div className="backend-status connected">{t('backend.connected')}</div>;
}
