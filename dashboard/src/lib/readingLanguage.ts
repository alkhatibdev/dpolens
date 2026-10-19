import { useState } from "react";
import { useTranslation } from "react-i18next";

const REMEMBERED = "dpolens.reading-language.";

function remembered(law: string): string | null {
  try {
    return globalThis.localStorage.getItem(REMEMBERED + law);
  } catch {
    return null;
  }
}

function remember(law: string, lang: string): void {
  try {
    globalThis.localStorage.setItem(REMEMBERED + law, lang);
  } catch {
    // Where the browser keeps nothing, the choice lasts until the page is left.
  }
}

/**
 * The one language a law is read in, and a way to change it.
 *
 * The reader's last choice for that law in this browser, or else the dashboard's
 * language where the law has it, or else the language that prevails. A law's library
 * page and its clause pages share the choice, so switching once is enough.
 */
export function useReadingLanguage(
  law: string | null,
  languages: readonly string[],
  prevailing?: string | null,
): [string | null, (lang: string) => void] {
  const { i18n } = useTranslation();
  const [picked, setPicked] = useState<{ law: string | null; lang: string } | null>(null);
  const dashboard = i18n.language.split("-")[0];
  const lang =
    [
      picked?.law === law ? picked.lang : null,
      law ? remembered(law) : null,
      dashboard,
      prevailing,
      languages[0],
    ].find((candidate): candidate is string => !!candidate && languages.includes(candidate)) ??
    null;

  function choose(next: string) {
    if (law) {
      remember(law, next);
    }
    setPicked({ law, lang: next });
  }

  return [lang, choose];
}
