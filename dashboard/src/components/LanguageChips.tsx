import { useTranslation } from "react-i18next";

import { Chip } from "@/components/States";
import { languageName, nativeLanguageName } from "@/lib/format";

/** A law's languages, the one that prevails named in itself and marked, where there are two. */
export function LanguageChips({
  languages,
  authoritative,
}: {
  languages: readonly string[];
  authoritative: string | null | undefined;
}) {
  const { t } = useTranslation();
  const prevailing = languages.length > 1 ? authoritative : null;
  return (
    <span className="flex flex-wrap gap-2">
      {languages.map((lang) =>
        lang === prevailing ? (
          <Chip key={lang} tone="brand" lang={lang}>
            {nativeLanguageName(lang)} · {t("library.prevails")}
          </Chip>
        ) : (
          <Chip key={lang} tone="quiet">
            {languageName(lang)}
            {prevailing ? `, ${t("library.officialTranslation")}` : ""}
          </Chip>
        ),
      )}
    </span>
  );
}
