import { ArrowUpRight, Check, Copy } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate } from "react-router";

import { useVerification } from "@/api/logs";
import { useSettings } from "@/api/settings";
import { PageHeading } from "@/components/Page";
import { Chip, Failed, Loading, Panel } from "@/components/States";
import { Button } from "@/components/ui/button";
import { copyText } from "@/lib/copy";
import { formatDate, formatNumber } from "@/lib/format";
import { GOVERNANCE_READ, SETTINGS_MANAGE } from "@/lib/permissions";
import { usePermitted } from "@/session";

const HOW_TO_CHANGE = "https://dpolens.com/docs/configuration";

const KINDS = ["email", "phone", "card", "iban", "emirates_id"] as const;

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap justify-between gap-x-4 gap-y-1.5 border-b border-line py-3 last:border-b-0">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="min-w-0 text-end text-[15px] font-medium">{children}</dd>
    </div>
  );
}

function Group({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section className="min-w-0 flex-[1_1_420px] rounded-[20px] bg-white px-5 pt-5 pb-3 sm:px-6">
      <h2 className="text-lg font-semibold">{title}</h2>
      <dl className="mt-1.5">{children}</dl>
      {note ? <p className="pb-2 text-[13px] leading-relaxed text-muted">{note}</p> : null}
    </section>
  );
}

function CopyUrl({ value }: { value: string }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) {
      return;
    }
    const timer = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(timer);
  }, [copied]);
  return (
    <button
      type="button"
      aria-label={copied ? t("common.copied") : t("settings.copyUrl")}
      onClick={() => void copyText(value).then(() => setCopied(true))}
      className="grid size-9 shrink-0 place-items-center rounded-[10px] bg-field text-ink-2 hover:bg-line"
    >
      {copied ? <Check aria-hidden className="size-4" /> : <Copy aria-hidden className="size-4" />}
    </button>
  );
}

export function SettingsPage() {
  const { t } = useTranslation();
  const can = usePermitted();
  const permitted = can.has(SETTINGS_MANAGE);
  const settings = useSettings(permitted);
  const reads = permitted && can.has(GOVERNANCE_READ);
  const chain = useVerification(reads);

  if (!permitted) {
    return <Navigate to="/" replace />;
  }

  const kindName = (kind: string) =>
    (KINDS as readonly string[]).includes(kind)
      ? t(`settings.kinds.${kind as (typeof KINDS)[number]}`)
      : kind;

  return (
    <Panel>
      <PageHeading
        title={t("settings.title")}
        subtitle={t("settings.subtitle")}
        action={
          <Button asChild variant="quiet" size="sm">
            <a href={HOW_TO_CHANGE} target="_blank" rel="noreferrer">
              {t("settings.howTo")}
              <ArrowUpRight aria-hidden className="size-4" />
            </a>
          </Button>
        }
      />
      {settings.isPending ? <Loading /> : null}
      {settings.error ? <Failed onRetry={() => void settings.refetch()} /> : null}
      {settings.data ? (
        <div className="flex flex-wrap gap-4">
          <Group title={t("settings.questionsLog")}>
            <Row label={t("settings.keptFor")}>
              {settings.data.questions_log.retention_days === null
                ? t("settings.noLimit")
                : t("settings.days", { count: settings.data.questions_log.retention_days })}
            </Row>
            <Row label={t("settings.takenOut")}>
              <span className="flex flex-wrap justify-end gap-1.5">
                {settings.data.questions_log.redacted.map((kind) => (
                  <Chip key={kind} tone="quiet">
                    {kindName(kind)}
                  </Chip>
                ))}
              </span>
            </Row>
            <Row label={t("settings.added")}>
              {settings.data.questions_log.added_patterns.length ? (
                <span className="font-mono text-[13px]">
                  {settings.data.questions_log.added_patterns.join(", ")}
                </span>
              ) : (
                t("settings.none")
              )}
            </Row>
          </Group>

          <Group title={t("settings.signingIn")}>
            <Row label={t("settings.idle")}>
              {t("settings.idleValue", { count: settings.data.sign_in.idle_minutes })}
            </Row>
            <Row label={t("settings.lifetime")}>
              {t("settings.hours", { count: settings.data.sign_in.lifetime_hours })}
            </Row>
            <Row label={t("settings.wrongPasswords")}>
              {t("settings.wrongPasswordsValue", {
                count: settings.data.sign_in.wrong_passwords,
                minutes: settings.data.sign_in.wrong_password_window_minutes,
              })}
            </Row>
          </Group>

          <Group title={t("settings.assistants")}>
            <Row label={t("settings.mcpUrl")}>
              <span className="inline-flex max-w-full items-center justify-end gap-2">
                <code className="min-w-0 font-mono text-[13px] break-all">
                  {settings.data.assistants.mcp_url}
                </code>
                <CopyUrl value={settings.data.assistants.mcp_url} />
              </span>
            </Row>
            <Row label={t("settings.perToken")}>
              {t("settings.perTokenValue", {
                count: settings.data.assistants.requests_per_minute,
              })}
            </Row>
          </Group>

          <Group
            title={t("settings.ai")}
            note={settings.data.ai_provider ? undefined : t("settings.nothingSent")}
          >
            <Row label={t("settings.inUse")}>{settings.data.ai_provider ?? t("settings.none")}</Row>
            <Row label={t("settings.runsOn")}>{t("settings.ownModel")}</Row>
          </Group>

          <Group title={t("settings.instance")}>
            <Row label={t("settings.version")}>{settings.data.instance.version}</Row>
            <Row label={t("settings.id")}>
              <code className="font-mono text-xs break-all text-ink-2">
                {settings.data.instance.id}
              </code>
            </Row>
            <Row label={t("settings.since")}>{formatDate(settings.data.instance.created_at)}</Row>
            {reads ? (
              <Row label={t("settings.governance")}>
                {chain.data
                  ? chain.data.ok
                    ? t("settings.intact", {
                        count: chain.data.entries,
                        number: formatNumber(chain.data.entries),
                      })
                    : t("settings.broken")
                  : null}
                {chain.data ? " · " : null}
                <Link
                  to="/logs/governance"
                  className="text-brand-dark underline underline-offset-2"
                >
                  {t("settings.open")}
                </Link>
              </Row>
            ) : null}
          </Group>
        </div>
      ) : null}
    </Panel>
  );
}
