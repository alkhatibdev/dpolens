import { useMutation } from "@tanstack/react-query";
import { Eye, EyeOff } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router";

import { ApiError, api, unwrap } from "@/api/client";
import { Waves } from "@/components/Waves";
import { Wordmark } from "@/components/Wordmark";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatDeadline } from "@/lib/format";
import { useSpendLink } from "@/session";

/** The secret travels after `#`, which no server sees; it is read once and kept in memory. */
function useSecret(): string {
  const [secret] = useState(() => globalThis.location.hash.slice(1));
  useEffect(() => {
    if (globalThis.location.hash) {
      globalThis.history.replaceState(null, "", globalThis.location.pathname);
    }
  }, []);
  return secret;
}

/** Where a sign-in link lands: the person chooses a password and is signed in. */
export function WelcomePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const secret = useSecret();
  const [password, setPassword] = useState("");
  const [shown, setShown] = useState(false);
  const spend = useSpendLink();
  const lookup = useMutation({
    mutationFn: () => unwrap(api.POST("/v1/sign-in-links/lookup", { body: { secret } })),
  });
  const { mutate: look } = lookup;
  useEffect(() => {
    if (secret) {
      look();
    }
  }, [secret, look]);

  function submit(event: FormEvent) {
    event.preventDefault();
    spend.mutate({ secret, password }, { onSuccess: () => void navigate("/", { replace: true }) });
  }

  const unusable =
    !secret ||
    (lookup.error instanceof ApiError && lookup.error.kind === "sign-in-link-unusable") ||
    (spend.error instanceof ApiError && spend.error.kind === "sign-in-link-unusable");
  let message: string | null = null;
  if (spend.error instanceof ApiError && spend.error.kind === "weak-password") {
    message = t("welcome.short");
  } else if (spend.error && !unusable) {
    message = t("common.failed");
  }
  const details = lookup.data;

  return (
    <div className="flex min-h-dvh flex-col gap-2 p-2 sm:gap-4 sm:p-4 lg:flex-row">
      <section className="relative flex min-h-[260px] flex-col overflow-hidden rounded-[24px] bg-brand px-6 pt-8 pb-28 text-white sm:px-12 sm:pt-11 lg:min-h-0 lg:flex-1 lg:pb-12">
        <Wordmark className="relative text-[26px]" />
        <h1 className="relative mt-10 max-w-[560px] text-[30px] leading-[1.12] font-semibold tracking-[-0.03em] sm:text-[40px] lg:mt-20 lg:text-[46px]">
          {t("signIn.headline")}
        </h1>
        <p className="relative mt-4 max-w-[500px] text-base leading-relaxed text-brand-soft sm:text-[17px]">
          {t("signIn.promise")}
        </p>
        <Waves />
      </section>

      <main className="flex flex-1 items-center justify-center rounded-[24px] bg-white px-6 py-10 sm:px-12">
        {unusable ? (
          <div className="flex w-full max-w-[400px] flex-col gap-4">
            <h2 className="text-[30px] font-semibold tracking-[-0.02em] sm:text-[34px]">
              {t("welcome.unusableTitle")}
            </h2>
            <p className="text-[15px] leading-relaxed text-muted">{t("welcome.unusableBody")}</p>
            <Button asChild variant="dark" className="self-start">
              <Link to="/sign-in">{t("welcome.toSignIn")}</Link>
            </Button>
          </div>
        ) : (
          <form onSubmit={submit} className="flex w-full max-w-[400px] flex-col gap-5" noValidate>
            <div>
              <h2 className="text-[30px] font-semibold tracking-[-0.02em] sm:text-[34px]">
                {details
                  ? t("welcome.title", { name: details.display_name.split(/\s+/)[0] ?? "" })
                  : " "}
              </h2>
              <p className="mt-2 text-[15px] break-all text-muted">
                {details ? t("welcome.subtitle", { email: details.email }) : " "}
              </p>
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="new-password">{t("welcome.password")}</Label>
              <div className="relative">
                <Input
                  id="new-password"
                  type={shown ? "text" : "password"}
                  autoComplete="new-password"
                  required
                  minLength={12}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  aria-invalid={message ? true : undefined}
                  aria-describedby="new-password-hint"
                  className="pe-14"
                />
                <button
                  type="button"
                  onClick={() => setShown((now) => !now)}
                  aria-label={shown ? t("password.hide") : t("password.show")}
                  aria-pressed={shown}
                  className="absolute inset-y-1.5 end-1.5 grid w-11 place-items-center rounded-[10px] bg-field text-ink-2 hover:bg-line"
                >
                  {shown ? (
                    <EyeOff aria-hidden className="size-5" />
                  ) : (
                    <Eye aria-hidden className="size-5" />
                  )}
                </button>
              </div>
              <span id="new-password-hint" className="text-[13px] text-muted">
                {t("welcome.hint")}
              </span>
            </div>
            {message ? (
              <p
                role="alert"
                className="rounded-[14px] bg-danger-soft px-4 py-3 text-sm text-danger-ink"
              >
                {message}
              </p>
            ) : null}
            <Button
              type="submit"
              className="h-[54px] text-base"
              disabled={spend.isPending || !details || password.length < 12}
            >
              {spend.isPending ? t("welcome.submitting") : t("welcome.submit")}
            </Button>
            {details ? (
              <p className="text-[13px] text-muted">
                {t("welcome.until", { date: formatDeadline(details.expires_at) })}
              </p>
            ) : null}
          </form>
        )}
      </main>
    </div>
  );
}
