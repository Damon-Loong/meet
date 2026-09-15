import i18n from 'i18next'
import resourcesToBackend from 'i18next-resources-to-backend'
import { initReactI18next } from 'react-i18next'
import LanguageDetector from 'i18next-browser-languagedetector'
const i18nDefaultNamespace = 'global'
const fallbackLng = 'zh-CN'

i18n.setDefaultNamespace(i18nDefaultNamespace)
i18n
  .use(
    resourcesToBackend((language: string, namespace: string) => {
      return import(`../locales/${language}/${namespace}.json`)
    })
  )
  .use(initReactI18next)
  .use(LanguageDetector)
  .init({
    supportedLngs: ['zh-CN', 'en', 'fr', 'nl', 'de', 'es'],
    fallbackLng: ['zh-CN', 'en'],
    ns: i18nDefaultNamespace,
    detection: {
      order: ['localStorage'],
      lookupLocalStorage: 'meetLanguage',
    },
    interpolation: {
      escapeValue: false,
    },
  })
  .then(() => {
    document.documentElement.setAttribute('lang', i18n.language || fallbackLng)
  })

i18n.on('languageChanged', (lang) => {
  document.documentElement.setAttribute('lang', lang)
})
