import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { TokenMade } from "@/api/client";
import { useInstance } from "@/api/tokens";
import { CopyField } from "@/components/CopyField";
import { Notice } from "@/components/Notice";
import { SegmentedChoice } from "@/components/Segmented";
import { Button } from "@/components/ui/button";
import { Dialog, DialogActions, DialogClose, DialogContent } from "@/components/ui/dialog";

type Assistant = "claude" | "cursor" | "vscode";

const FALLBACK_URL = "http://localhost:8765/mcp";

function Snippet({ children }: { children: string }) {
  return (
    <pre className="overflow-x-auto rounded-[14px] bg-[#222924] p-3.5 font-mono text-[13px] leading-7 whitespace-pre text-[#e4e9e5]">
      {children}
    </pre>
  );
}

/** The token, the one time it can be seen, and how to put it in each assistant. */
export function TokenShownDialog({
  token,
  onClose,
}: {
  token: TokenMade | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const instance = useInstance();
  const [assistant, setAssistant] = useState<Assistant>("claude");
  if (!token) {
    return null;
  }
  const url = instance.data?.mcp_url ?? FALLBACK_URL;
  const cursor = JSON.stringify(
    { mcpServers: { dpolens: { url, headers: { Authorization: "Bearer ${env:DPOLENS_TOKEN}" } } } },
    null,
    2,
  );
  const vscode = JSON.stringify(
    {
      inputs: [
        {
          type: "promptString",
          id: "dpolens-token",
          description: "Your DPOLens token",
          password: true,
        },
      ],
      servers: {
        dpolens: {
          type: "http",
          url,
          headers: { Authorization: "Bearer ${input:dpolens-token}" },
        },
      },
    },
    null,
    2,
  );

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent title={t("tokens.shownTitle")} className="w-[min(600px,calc(100vw-24px))]">
        <Notice tone="warn">{t("tokens.shownWarning")}</Notice>
        <CopyField value={token.secret} label={t("tokens.copyToken")} emphasis />
        <div className="flex flex-col gap-3 border-t border-line pt-5">
          <h3 className="font-semibold">{t("tokens.connect")}</h3>
          <SegmentedChoice
            label={t("tokens.assistants")}
            value={assistant}
            onChange={setAssistant}
            options={[
              { value: "claude", label: t("tokens.claude") },
              { value: "cursor", label: t("tokens.cursor") },
              { value: "vscode", label: t("tokens.vscode") },
            ]}
          />
          {assistant === "claude" ? (
            <>
              <p className="text-sm leading-relaxed text-ink-2">{t("tokens.claudeFirst")}</p>
              <Snippet>
                {
                  "claude plugin marketplace add alkhatibdev/dpolens\nclaude plugin install dpolens@dpolens"
                }
              </Snippet>
              <p className="text-sm leading-relaxed text-ink-2">
                {t("tokens.claudeThen", { command: "/plugin configure dpolens@dpolens" })}
              </p>
              <CopyField value={url} label={t("tokens.copyAddress")} />
            </>
          ) : null}
          {assistant === "cursor" ? (
            <>
              <p className="text-sm leading-relaxed text-ink-2">{t("tokens.cursorFirst")}</p>
              <Snippet>{cursor}</Snippet>
              <p className="text-sm leading-relaxed text-ink-2">{t("tokens.cursorThen")}</p>
              <CopyField
                value={`export DPOLENS_TOKEN=${token.secret}`}
                label={t("tokens.copySnippet")}
              />
            </>
          ) : null}
          {assistant === "vscode" ? (
            <>
              <p className="text-sm leading-relaxed text-ink-2">{t("tokens.vscodeFirst")}</p>
              <Snippet>{vscode}</Snippet>
              <p className="text-sm leading-relaxed text-ink-2">{t("tokens.vscodeThen")}</p>
            </>
          ) : null}
        </div>
        <DialogActions>
          <DialogClose asChild>
            <Button variant="dark">{t("common.done")}</Button>
          </DialogClose>
        </DialogActions>
      </DialogContent>
    </Dialog>
  );
}
