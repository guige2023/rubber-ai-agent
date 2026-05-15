import { useState, useCallback } from 'react';
import en from '../locales/en.json';
import zh from '../locales/zh.json';

export type Locale = 'en' | 'zh';
type Translations = typeof en;

const translations: Record<Locale, Translations> = { en, zh };

export function getStoredLocale(): Locale {
  const saved = localStorage.getItem('rabaiagent_locale');
  if (saved === 'zh' || saved === 'en') {
    return saved;
  }

  const browserLang = navigator.language.toLowerCase();
  return browserLang.startsWith('zh') ? 'zh' : 'en';
}

export function translateStatic(key: string, locale: Locale = getStoredLocale()) {
  const keys = key.split('.');
  let value: any = translations[locale];

  for (const k of keys) {
    if (value && typeof value === 'object' && k in value) {
      value = value[k];
    } else {
      return key;
    }
  }

  return typeof value === 'string' ? value : key;
}

export function useI18n() {
  const [locale, setLocale] = useState<Locale>(() => getStoredLocale());

  const t = useCallback((key: string) => translateStatic(key, locale), [locale]);

  const changeLanguage = (newLocale: Locale) => {
    setLocale(newLocale);
    localStorage.setItem('rabaiagent_locale', newLocale);
  };

  return { t, locale, changeLanguage };
}
