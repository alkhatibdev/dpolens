import type { Clause, Document, Person, Role, SignedIn, Token } from "@/api/client";

export const signedIn: SignedIn = {
  account: {
    id: "8f0e2c6a-4a1b-4c7d-9e2f-3b5a6c7d8e9f",
    email: "mariam@example.com",
    display_name: "Mariam Al Amiri",
    roles: ["DPO"],
  },
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

export const admin: SignedIn = {
  account: {
    id: "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed",
    email: "yousef@example.com",
    display_name: "Yousef Haddad",
    roles: ["Admin"],
  },
  permissions: [
    "documents.publish",
    "documents.read",
    "documents.upload",
    "governance.read",
    "queries.read_all",
    "queries.read_identities",
    "queries.read_own",
    "roles.manage",
    "settings.manage",
    "tokens.create",
    "users.manage",
  ],
  expires_at: "2026-10-15T17:00:00Z",
  idle_minutes: 30,
};

export function person(fields: Partial<Person> & Pick<Person, "id" | "display_name">): Person {
  return {
    email: `${fields.display_name.split(" ")[0]!.toLowerCase()}@example.com`,
    kind: "person",
    status: "active",
    roles: [],
    created_at: "2026-09-03T08:00:00Z",
    deactivated_at: null,
    has_password: true,
    sign_in_link_expires_at: null,
    working_tokens: 0,
    acts_for_others: false,
    ...fields,
  };
}

export const people: Person[] = [
  person({
    id: admin.account.id,
    display_name: "Yousef Haddad",
    email: "yousef@example.com",
    roles: ["Admin"],
    working_tokens: 1,
  }),
  person({ id: "p-omar", display_name: "Omar Khalil", roles: ["Developer"], working_tokens: 2 }),
  person({
    id: "p-lina",
    display_name: "Lina Farouk",
    roles: ["Legal reviewer"],
    has_password: false,
    sign_in_link_expires_at: "2026-10-18T05:05:00Z",
  }),
  person({
    id: "p-ahmed",
    display_name: "Ahmed Saleh",
    roles: ["Developer"],
    status: "deactivated",
    deactivated_at: "2026-10-02T09:00:00Z",
  }),
  person({
    id: "p-mcp",
    display_name: "MCP server",
    email: "mcp@surface.invalid",
    kind: "service_account",
    acts_for_others: true,
    working_tokens: 1,
  }),
];

export function role(fields: Partial<Role> & Pick<Role, "id" | "name">): Role {
  return {
    description: "",
    is_seeded: false,
    permissions: [],
    holders: [],
    revision: 1,
    created_at: "2026-09-02T08:00:00Z",
    updated_at: "2026-10-03T12:20:00Z",
    updated_by: null,
    ...fields,
  };
}

export const roles: Role[] = [
  role({
    id: "r-admin",
    name: "Admin",
    description: "Runs the instance: users, roles, settings and both logs",
    is_seeded: true,
    permissions: admin.permissions,
    holders: [
      { id: admin.account.id, display_name: "Yousef Haddad", kind: "person", status: "active" },
    ],
  }),
  role({
    id: "r-dpo",
    name: "DPO",
    description: "Owns the policies and reads the logs",
    is_seeded: true,
    permissions: [
      "documents.publish",
      "documents.read",
      "documents.upload",
      "governance.read",
      "queries.read_all",
      "settings.manage",
      "tokens.create",
    ],
    holders: [
      { id: "p-mariam", display_name: "Mariam Al Amiri", kind: "person", status: "active" },
    ],
    revision: 3,
    updated_by: "Yousef Haddad",
  }),
  role({
    id: "r-dev",
    name: "Developer",
    description: "Reads the library through an editor, and their own questions",
    is_seeded: true,
    permissions: ["documents.read", "queries.read_own", "tokens.create"],
  }),
];

export const catalog = {
  permissions: admin.permissions.map((key) => ({ key, description: key })),
};

export function token(fields: Partial<Token> & Pick<Token, "id" | "name">): Token {
  return {
    prefix: "dpol_Xk2fQ9",
    owner: { id: admin.account.id, display_name: "Yousef Haddad", kind: "person" },
    permissions: ["documents.read"],
    effective_permissions: ["documents.read"],
    trusted_surface: false,
    status: "active",
    created_at: "2026-09-10T08:00:00Z",
    last_used_at: null,
    expires_at: null,
    revoked_at: null,
    ...fields,
  };
}
