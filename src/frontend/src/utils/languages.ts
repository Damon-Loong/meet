// Map frontend language codes to backend language codes

export type BackendLanguage = 'en-us' | 'fr-fr' | 'nl-nl' | 'de-de' | 'es-es'
export type FrontendLanguage = 'zh-CN' | 'en' | 'fr' | 'nl' | 'de' | 'es'

const frontendToBackendMap: Record<FrontendLanguage, BackendLanguage> = {
  // Backend does not yet support Chinese; keep its preferences in English.
  'zh-CN': 'en-us',
  en: 'en-us',
  fr: 'fr-fr',
  nl: 'nl-nl',
  de: 'de-de',
  es: 'es-es',
}

export const convertToBackendLanguage = (
  frontendLang: string = 'zh-CN'
): BackendLanguage => {
  return frontendToBackendMap[frontendLang as FrontendLanguage] || 'en-us'
}
