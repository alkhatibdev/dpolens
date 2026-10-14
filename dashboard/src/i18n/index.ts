import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import { en } from "./en";

declare module "i18next" {
  interface CustomTypeOptions {
    defaultNS: "translation";
    resources: { translation: typeof en };
  }
}

void i18n.use(initReactI18next).init({
  lng: "en",
  fallbackLng: "en",
  resources: { en: { translation: en } },
  interpolation: { escapeValue: false },
  returnNull: false,
});

/** The direction of the interface itself. Document text sets its own. */
export function directionOf(lang: string): "ltr" | "rtl" {
  return lang === "ar" ? "rtl" : "ltr";
}

export default i18n;
