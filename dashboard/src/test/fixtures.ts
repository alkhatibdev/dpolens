import type { Clause, Document, SignedIn } from "@/api/client";

export const signedIn: SignedIn = {
  account: { email: "mariam@example.com", display_name: "Mariam Al Amiri", roles: ["DPO"] },
  permissions: ["documents.read"],
  expires_at: "2026-10-15T17:00:00Z",
  idle_minutes: 30,
};

export const uae: Document = {
  slug: "uae-pdpl",
  title: "Federal Decree by Law No. (45) of 2021 Concerning the Protection of Personal Data",
  kind: "law",
  version_label: "2026.1",
  effective_date: "2022-01-02",
  clauses: 199,
  languages: ["ar", "en"],
  pack_slug: "uae-pdpl",
  jurisdiction: "United Arab Emirates",
  trust_tier: "community",
  source_url: "https://uaelegislation.gov.ae/en/legislations/1972/download",
  authoritative_language: "ar",
  in_selected_laws: true,
};

export const gdpr: Document = {
  ...uae,
  slug: "gdpr",
  title: "General Data Protection Regulation",
  effective_date: "2018-05-25",
  clauses: 867,
  languages: ["en"],
  pack_slug: "gdpr",
  jurisdiction: "European Union",
  authoritative_language: "en",
  in_selected_laws: false,
};

function clause(fields: Partial<Clause> & Pick<Clause, "key" | "text" | "lang">): Clause {
  return {
    clause_type: "paragraph",
    label: null,
    heading: null,
    is_authoritative: fields.lang === "ar",
    authoritative_language: "ar",
    authoritative_text: null,
    is_normative: true,
    depth: 1,
    document_title: uae.title,
    document_slug: "uae-pdpl",
    version_label: "2026.1",
    effective_date: "2022-01-02",
    pack_slug: "uae-pdpl",
    jurisdiction: "United Arab Emirates",
    trust_tier: "community",
    source_url: uae.source_url,
    ...fields,
  } as Clause;
}

export const article13 = {
  en: [
    clause({
      key: "uae-pdpl:art-13",
      lang: "en",
      text: "",
      label: "Article (13)",
      heading: "Right to Receive Information",
      depth: 0,
      clause_type: "article",
    }),
    clause({
      key: "uae-pdpl:art-13:para-1",
      lang: "en",
      label: "1.",
      text: "The Data Subject has the right, by submitting a request to the Controller without any consideration, to obtain the following information:",
      depth: 1,
    }),
    clause({
      key: "uae-pdpl:art-13:para-1:pt-a",
      lang: "en",
      label: "a.",
      text: "The types of its Personal Data that are being processed.",
      depth: 2,
      clause_type: "point",
    }),
  ],
  ar: [
    clause({
      key: "uae-pdpl:art-13",
      lang: "ar",
      text: "",
      label: "المادة (13)",
      heading: "حق الحصول على المعلومات",
      depth: 0,
      clause_type: "article",
    }),
    clause({
      key: "uae-pdpl:art-13:para-1",
      lang: "ar",
      label: "1.",
      text: "يحق لصاحب البيانات وبناءً على طلب يقدمه إلى المتحكم ومن دون أي مقابل الحصول على المعلومات الأتية:",
      depth: 1,
    }),
    clause({
      key: "uae-pdpl:art-13:para-1:pt-a",
      lang: "ar",
      label: "أ.",
      text: "أنواع البيانات الشخصية التابعة له التي يتم معالجتها.",
      depth: 2,
      clause_type: "point",
    }),
  ],
};
