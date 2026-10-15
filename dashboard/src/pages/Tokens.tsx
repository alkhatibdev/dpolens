import { KeyRound, Plus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { Token, TokenMade } from "@/api/client";
import { useTokens } from "@/api/tokens";
import { Avatar } from "@/components/Avatar";
import { FilterButton, FindBox } from "@/components/Filters";
import { PageHeading, TableCard, td, th } from "@/components/Page";
import { SegmentedChoice } from "@/components/Segmented";
import { Chip, Failed, Loading, Panel } from "@/components/States";
import { CreateTokenDialog } from "@/components/tokens/CreateTokenDialog";
import { RevokeDialog } from "@/components/tokens/RevokeDialog";
import { TokenShownDialog } from "@/components/tokens/TokenShownDialog";
import { Button } from "@/components/ui/button";
import { daysUntil, formatDate, formatSince } from "@/lib/format";
import { wordsFor } from "@/lib/permissionWords";
import { TOKENS_CREATE, USERS_MANAGE } from "@/lib/permissions";
import { usePermitted, useSession } from "@/session";

type Whose = "mine" | "everyone";
type State = "working" | "ended";

const SOON = 14;

function Expiry({ token }: { token: Token }) {
  const { t } = useTranslation();
  if (!token.expires_at) {
    return <span className="text-sm text-ink-2">{t("tokens.noExpiry")}</span>;
  }
  if (token.status === "expired") {
    return (
      <span className="text-sm text-ink-2">
        {t("tokens.expired", { date: formatDate(token.expires_at, "short") })}
      </span>
    );
  }
  const days = daysUntil(token.expires_at);
  if (days <= SOON) {
    return (
      <Chip tone="warn">{days <= 0 ? t("tokens.today") : t("tokens.inDays", { count: days })}</Chip>
    );
  }
  return (
    <span className="text-sm whitespace-nowrap text-ink-2">
      {formatDate(token.expires_at, "short")}
    </span>
  );
}

function Can({ token }: { token: Token }) {
  const { t } = useTranslation();
  const lost = token.permissions.filter((key) => !token.effective_permissions.includes(key));
  if (token.trusted_surface) {
    return <Chip tone="soft">{t("tokens.actsForOthers")}</Chip>;
  }
  return (
    <div>
      <div className="flex flex-wrap gap-1.5">
        {token.permissions.map((key) =>
          lost.includes(key) ? (
            <Chip key={key} tone="quiet">
              <span className="text-muted line-through">{wordsFor(t, key).short}</span>
            </Chip>
          ) : (
            <Chip key={key} tone="quiet">
              {wordsFor(t, key).short}
            </Chip>
          ),
        )}
      </div>
      {lost.length && token.status === "active" ? (
        <p className="mt-1.5 text-xs leading-relaxed text-muted">
          {t("tokens.notHeld", {
            name: token.owner.display_name,
            permissions: lost.map((key) => wordsFor(t, key).short).join(", "),
          })}
        </p>
      ) : null}
    </div>
  );
}

export function TokensPage() {
  const { t } = useTranslation();
  const can = usePermitted();
  const session = useSession();
  const seesEveryone = can.has(USERS_MANAGE);
  const [whose, setWhose] = useState<Whose>("mine");
  const [state, setState] = useState<State>("working");
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const [made, setMade] = useState<TokenMade | null>(null);
  const [revoking, setRevoking] = useState<Token | null>(null);
  const mine = useTokens(false);
  const everyone = useTokens(true, seesEveryone);

  const listed = whose === "everyone" && seesEveryone ? everyone : mine;
  const all = listed.data?.tokens ?? [];
  const working = all.filter((token) => token.status === "active");
  const ended = all.filter((token) => token.status !== "active");
  const wanted = query.trim().toLowerCase();
  const shown = (state === "working" ? working : ended).filter(
    (token) =>
      !wanted ||
      token.name.toLowerCase().includes(wanted) ||
      token.prefix.toLowerCase().includes(wanted) ||
      token.owner.display_name.toLowerCase().includes(wanted),
  );
  const count = (tokens: readonly Token[] | undefined) =>
    (tokens ?? []).filter((token) => token.status === "active").length;
  const withOwner = whose === "everyone" && seesEveryone;

  return (
    <Panel>
      <PageHeading
        title={t("tokens.title")}
        subtitle={t("tokens.subtitle")}
        action={
          can.has(TOKENS_CREATE) ? (
            <Button onClick={() => setCreating(true)}>
              <Plus aria-hidden className="size-4" />
              {t("tokens.create")}
            </Button>
          ) : null
        }
      />
      {seesEveryone ? (
        <SegmentedChoice
          label={t("tokens.whose")}
          value={whose}
          onChange={setWhose}
          options={[
            { value: "mine", label: t("tokens.yours", { count: count(mine.data?.tokens) }) },
            {
              value: "everyone",
              label: t("tokens.everyone", { count: count(everyone.data?.tokens) }),
            },
          ]}
        />
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <FindBox
          label={withOwner ? t("tokens.search") : t("tokens.searchYours")}
          value={query}
          onChange={setQuery}
        />
        <FilterButton pressed={state === "working"} onClick={() => setState("working")}>
          {t("tokens.working", { count: working.length })}
        </FilterButton>
        <FilterButton pressed={state === "ended"} onClick={() => setState("ended")}>
          {t("tokens.ended", { count: ended.length })}
        </FilterButton>
      </div>

      {listed.isPending ? <Loading /> : null}
      {listed.error ? <Failed onRetry={() => void listed.refetch()} /> : null}
      {listed.data && all.length === 0 && whose === "mine" ? (
        <div className="flex flex-col items-start gap-2.5 rounded-[20px] border-2 border-dashed border-line-strong p-6">
          <KeyRound aria-hidden className="size-8 text-brand-dark" />
          <h2 className="text-[19px] font-semibold">{t("tokens.emptyTitle")}</h2>
          <p className="max-w-[62ch] text-[15px] leading-relaxed text-muted">
            {t("tokens.emptyBody")}
          </p>
          {can.has(TOKENS_CREATE) ? (
            <Button size="sm" className="mt-1.5" onClick={() => setCreating(true)}>
              {t("tokens.create")}
            </Button>
          ) : null}
        </div>
      ) : listed.data ? (
        <TableCard footer={withOwner ? t("tokens.footEveryone") : t("tokens.footYours")}>
          <table className="w-full min-w-[760px] border-collapse">
            <thead>
              <tr>
                <th scope="col" className={th}>
                  {t("tokens.token")}
                </th>
                {withOwner ? (
                  <th scope="col" className={th}>
                    {t("tokens.owner")}
                  </th>
                ) : null}
                <th scope="col" className={th}>
                  {t("tokens.can")}
                </th>
                <th scope="col" className={th}>
                  {t("tokens.lastUsed")}
                </th>
                <th scope="col" className={th}>
                  {t("tokens.expires")}
                </th>
                <th scope="col" className={th}>
                  <span className="sr-only">{t("tokens.revoke")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {shown.map((token) => (
                <tr key={token.id}>
                  <td className={td}>
                    <div className="font-semibold">{token.name}</div>
                    <code className="font-mono text-xs text-muted">{token.prefix}…</code>
                  </td>
                  {withOwner ? (
                    <td className={td}>
                      <span className="flex items-center gap-2 text-sm whitespace-nowrap">
                        <Avatar
                          name={token.owner.display_name}
                          service={token.owner.kind === "service_account"}
                          size={28}
                        />
                        {token.owner.display_name}
                      </span>
                    </td>
                  ) : null}
                  <td className={`${td} min-w-[220px]`}>
                    <Can token={token} />
                  </td>
                  <td className={td}>
                    {token.last_used_at ? (
                      <span className="text-sm whitespace-nowrap text-ink-2">
                        {formatSince(token.last_used_at)}
                      </span>
                    ) : (
                      <Chip tone="quiet">{t("tokens.neverUsed")}</Chip>
                    )}
                  </td>
                  <td className={td}>
                    <Expiry token={token} />
                  </td>
                  <td className={`${td} py-2.5 text-end`}>
                    {token.status === "active" ? (
                      <Button
                        variant="danger-outline"
                        size="sm"
                        aria-label={t("tokens.revokeNamed", { name: token.name })}
                        onClick={() => setRevoking(token)}
                      >
                        {t("tokens.revoke")}
                      </Button>
                    ) : token.revoked_at ? (
                      <span className="text-sm whitespace-nowrap text-muted">
                        {t("tokens.revokedOn", { date: formatDate(token.revoked_at, "short") })}
                      </span>
                    ) : token.status === "owner_inactive" ? (
                      <span className="text-sm whitespace-nowrap text-muted">
                        {t("tokens.ownerInactive")}
                      </span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {shown.length === 0 ? <p className="px-4 py-5 text-muted">{t("tokens.none")}</p> : null}
        </TableCard>
      ) : null}

      <CreateTokenDialog
        open={creating}
        held={can}
        onClose={() => setCreating(false)}
        onMade={setMade}
      />
      <TokenShownDialog token={made} onClose={() => setMade(null)} />
      <RevokeDialog
        token={revoking}
        yours={revoking?.owner.id === session.data?.account.id}
        onClose={() => setRevoking(null)}
      />
    </Panel>
  );
}
