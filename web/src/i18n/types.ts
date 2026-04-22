export type Locale = 'en' | 'zh-CN';

export interface LocaleMessages {
  [key: string]: string | LocaleMessages;
}
