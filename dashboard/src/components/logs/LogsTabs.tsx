import { useTranslation } from "react-i18next";

import { SectionTabs } from "@/components/Segmented";
import { formatNumber } from "@/lib/format";
import { GOVERNANCE_READ, QUERIES_READ_ALL, QUERIES_READ_OWN } from "@/lib/permissions";
import { usePermitted } from "@/session";

/** Questions and Governance, each for whoever may read it. */
export function LogsTabs({ questions, governance }: { questions?: number; governance?: number }) {
  const { t } = useTranslation();
  const can = usePermitted();
  const readsQuestions = can.has(QUERIES_READ_ALL) || can.has(QUERIES_READ_OWN);
  const items = [
    ...(readsQuestions
      ? [
          {
            to: "/logs",
            end: true,
            label:
              questions === undefined
                ? t("logs.questions")
                : can.has(QUERIES_READ_ALL)
                  ? t("logs.questionsCount", { number: formatNumber(questions) })
                  : t("logs.yourQuestions"),
          },
        ]
      : []),
    ...(can.has(GOVERNANCE_READ)
      ? [
          {
            to: "/logs/governance",
            end: true,
            label:
              governance === undefined
                ? t("logs.governance")
                : t("logs.governanceCount", { number: formatNumber(governance) }),
          },
        ]
      : []),
  ];
  return <SectionTabs label={t("logs.sections")} items={items} />;
}
