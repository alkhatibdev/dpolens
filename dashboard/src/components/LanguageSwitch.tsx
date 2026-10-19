import { useTranslation } from "react-i18next";

import { nativeLanguageName, readingOrder } from "@/lib/format";

import { SegmentedChoice } from "./Segmented";

/** English | العربية: which of a law's languages to read it in, each named in itself. */
export function LanguageSwitch({
  languages,
  value,
  onChange,
}: {
  languages: readonly string[];
  value: string;
  onChange: (lang: string) => void;
}) {
  const { t } = useTranslation();
  if (languages.length < 2) {
    return null;
  }
  return (
    <SegmentedChoice
      label={t("document.language")}
      value={value}
      onChange={onChange}
      options={readingOrder(languages).map((lang) => ({
        value: lang,
        label: <span lang={lang}>{nativeLanguageName(lang)}</span>,
      }))}
    />
  );
}
