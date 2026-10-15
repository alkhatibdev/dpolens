import { useQueryClient } from "@tanstack/react-query";
import { Eye, EyeOff } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useLocation, useNavigate, useSearchParams } from "react-router";

import { ApiError, type SignedIn } from "@/api/client";
import { lawsQuery, neverChosen } from "@/api/laws";
import { Waves } from "@/components/Waves";
import { Wordmark } from "@/components/Wordmark";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SETTINGS_MANAGE } from "@/lib/permissions";
import { useSession, useSignIn } from "@/session";

const ENDINGS = ["expired", "idle", "owner_inactive"] as const;
type Ending = (typeof ENDINGS)[number];

function isEnding(value: string | null): value is Ending {
  return ENDINGS.includes(value as Ending);
}

export function SignInPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const client = useQueryClient();
  const session = useSession();
  const signIn = useSignIn();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [shown, setShown] = useState(false);
  const [arriving, setArriving] = useState(false);

  const from = (location.state as { from?: { pathname: string; search: string } } | null)?.from;
  // Without a page to return to, the home route picks where this person starts.
  const destination = from ? `${from.pathname}${from.search}` : "/";

  // Only a session the API has just confirmed counts: a failed check keeps the
  // answer from before it, which must not send anyone back to the page they left.
  // A sign-in made on this page decides for itself where it goes next.
  if (session.status === "success" && signIn.isIdle) {
    return <Navigate to={destination} replace />;
  }

  /** Until somebody has chosen which laws apply, whoever may choose is asked first. */
  async function arrive(signedIn: SignedIn) {
    setArriving(true);
    if (signedIn.permissions.includes(SETTINGS_MANAGE)) {
      try {
        if (neverChosen(await client.fetchQuery({ ...lawsQuery, retry: false }))) {
          void navigate("/setup", { replace: true, state: { then: destination } });
          return;
        }
      } catch {
        // The question can wait for the next sign-in rather than stand in the way.
      }
    }
    void navigate(destination, { replace: true });
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    signIn.mutate({ email, password }, { onSuccess: (signedIn) => void arrive(signedIn) });
  }

  const reason = params.get("reason");
  const failure = signIn.error;
  let message: string | null = null;
  if (failure instanceof ApiError && failure.kind === "sign-in-refused") {
    message = t("signIn.refused");
  } else if (failure instanceof ApiError && failure.kind === "too-many-attempts") {
    message = t("signIn.tooMany", {
      count: Math.max(1, Math.ceil((failure.retryAfter ?? 60) / 60)),
    });
  } else if (failure) {
    message = t("signIn.failed");
  }

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
        <form onSubmit={submit} className="flex w-full max-w-[400px] flex-col gap-5" noValidate>
          <div>
            <h2 className="text-[30px] font-semibold tracking-[-0.02em] sm:text-[34px]">
              {t("signIn.title")}
            </h2>
            <p className="mt-2 text-[15px] text-muted">{t("signIn.subtitle")}</p>
          </div>

          {isEnding(reason) && !failure ? (
            <p role="status" className="rounded-[14px] bg-field px-4 py-3 text-sm text-ink-2">
              {t(`signIn.ended.${reason}`)}
            </p>
          ) : null}

          <div className="flex flex-col gap-2">
            <Label htmlFor="email">{t("signIn.email")}</Label>
            <Input
              id="email"
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              aria-invalid={message ? true : undefined}
            />
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="password">{t("signIn.password")}</Label>
            <div className="relative">
              <Input
                id="password"
                type={shown ? "text" : "password"}
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                aria-invalid={message ? true : undefined}
                className="pe-14"
              />
              <button
                type="button"
                onClick={() => setShown((now) => !now)}
                aria-label={shown ? t("signIn.hidePassword") : t("signIn.showPassword")}
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
            disabled={signIn.isPending || arriving}
          >
            {signIn.isPending || arriving ? t("signIn.submitting") : t("signIn.submit")}
          </Button>
        </form>
      </main>
    </div>
  );
}
