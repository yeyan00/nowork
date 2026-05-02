import {
  sendNotification,
  isPermissionGranted,
  requestPermission,
} from '@tauri-apps/plugin-notification';

/** Maximum length for notification body text. */
const MAX_NOTIFY_LEN = 50;

/** Truncate text for notification display, appending ellipsis if needed. */
function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max - 3) + '...';
}

/** Send system notification when a worker task completes. */
export async function notifyWorkerDone(workerName: string, userPrompt: string): Promise<void> {
  try {
    let granted = await isPermissionGranted();
    if (!granted) {
      const permission = await requestPermission();
      granted = permission === 'granted';
    }
    if (!granted) {
      console.warn('[notify] Notification permission not granted');
      return;
    }
    const body = `${workerName} 完成：${truncate(userPrompt, MAX_NOTIFY_LEN)}`;
    await sendNotification({ title: 'nowork', body });
  } catch (e) {
    console.error('[notify] Failed to send notification:', e);
  }
}