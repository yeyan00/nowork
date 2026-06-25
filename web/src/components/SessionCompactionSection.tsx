import { useEffect, useState } from 'react';
import { useI18n } from '../i18n';
import { getSessionConfig, updateSessionConfig } from '../lib/backend';

type SessionCompactionState = {
  readonly threshold: number;
  readonly reserve: number;
  readonly preserve: number;
  readonly maxSummaries: number;
};

const DEFAULT_STATE: SessionCompactionState = {
  threshold: 75,
  reserve: 4000,
  preserve: 5,
  maxSummaries: 3,
};

export function SessionCompactionSection() {
  const { t } = useI18n();
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [state, setState] = useState<SessionCompactionState>(DEFAULT_STATE);

  useEffect(() => {
    let cancelled = false;

    async function loadConfig() {
      try {
        const cfg = await getSessionConfig();
        if (cancelled) return;
        const compaction = cfg.compaction;
        setState({
          threshold: Math.round((compaction.context_usage_threshold ?? 0.75) * 100),
          reserve: compaction.context_reserve_tokens ?? 4000,
          preserve: compaction.preserve_recent_messages ?? 5,
          maxSummaries: compaction.max_summaries_injected ?? 3,
        });
      } catch {
        if (!cancelled) setState(DEFAULT_STATE);
      } finally {
        if (!cancelled) setLoaded(true);
      }
    }

    void loadConfig();
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSave() {
    setSaving(true);
    try {
      await updateSessionConfig({
        enabled: true,
        context_usage_threshold: state.threshold / 100,
        context_reserve_tokens: state.reserve,
        preserve_recent_messages: state.preserve,
        max_summaries_injected: state.maxSummaries,
      });
      setDirty(false);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="settings-block">
      <h3 className="settings-block-title">{t('settings.session')}</h3>
      <div className="settings-block-body">
        <p className="settings-section-desc">{t('settings.sessionHint')}</p>
        <div className="settings-form" style={{ gap: '10px' }}>
          <label className="settings-label">
            {t('settings.compactionThreshold')}
            <div className="slider-row">
              <input
                type="range"
                className="settings-slider"
                min={50}
                max={95}
                step={5}
                value={state.threshold}
                disabled={!loaded}
                onChange={(e) => {
                  setState((current) => ({ ...current, threshold: Number(e.target.value) }));
                  setDirty(true);
                }}
              />
              <span className="slider-value">{state.threshold}%</span>
            </div>
          </label>
          <div style={{ display: 'flex', gap: '12px' }}>
            <label className="settings-label" style={{ flex: 1 }}>
              {t('settings.compactionReserve')}
              <input
                type="number"
                className="settings-input"
                min={1000}
                max={50000}
                step={500}
                value={state.reserve}
                disabled={!loaded}
                onChange={(e) => {
                  setState((current) => ({ ...current, reserve: Number(e.target.value) || 4000 }));
                  setDirty(true);
                }}
              />
            </label>
            <label className="settings-label" style={{ flex: 1 }}>
              {t('settings.compactionPreserve')}
              <input
                type="number"
                className="settings-input"
                min={0}
                max={20}
                value={state.preserve}
                disabled={!loaded}
                onChange={(e) => {
                  setState((current) => ({ ...current, preserve: Number(e.target.value) || 5 }));
                  setDirty(true);
                }}
              />
            </label>
          </div>
          <label className="settings-label">
            {t('settings.compactionMaxSummaries')}
            <input
              type="number"
              className="settings-input"
              min={1}
              max={10}
              value={state.maxSummaries}
              disabled={!loaded}
              onChange={(e) => {
                setState((current) => ({ ...current, maxSummaries: Number(e.target.value) || 3 }));
                setDirty(true);
              }}
            />
          </label>
        </div>
        {dirty && (
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '4px' }}>
            <button type="button" className="primary-button" disabled={saving} onClick={() => void handleSave()}>
              {saving ? t('settings.saving') : t('settings.save')}
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
