import { ArrowUpRight, Search } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Logo } from "@/components/Logo";
import { MovingOutlines } from "@/components/Outlines";
import { formatDate } from "@/lib/format";
import { SIGN_IN_CLAUSES } from "@/lib/signInClauses";
import { cn } from "@/lib/utils";

// The mark's four corners, in its colours for a dark ground, each closing in
// from its own side as the page opens. A frame is the same either way round, so
// the corners sit left and right whichever way the page reads.
const CORNERS = [
  {
    at: "left-0 top-0",
    path: "M3 43V17A14 14 0 0 1 17 3H43",
    colour: "#6fd3a4",
    from: "-22px -22px",
  },
  {
    at: "right-0 top-0",
    path: "M3 3H29A14 14 0 0 1 43 17V43",
    colour: "#2e9e6b",
    from: "22px -22px",
  },
  {
    at: "right-0 bottom-0",
    path: "M43 3V29A14 14 0 0 1 29 43H3",
    colour: "#c9f2dd",
    from: "22px 22px",
  },
  {
    at: "left-0 bottom-0",
    path: "M43 43H17A14 14 0 0 1 3 29V3",
    colour: "#3fae7a",
    from: "-22px 22px",
  },
] as const;

/** The logo's viewfinder around the one clause: a lens on the exact words. */
function Lens({ children }: { children: ReactNode }) {
  return (
    <div className="relative p-[18px]">
      {CORNERS.map((corner) => (
        <svg
          key={corner.path}
          aria-hidden
          width="46"
          height="46"
          viewBox="0 0 46 46"
          className={cn("animate-focus absolute", corner.at)}
          style={{ "--focus-from": corner.from } as CSSProperties}
        >
          <path
            d={corner.path}
            stroke={corner.colour}
            strokeWidth="6"
            fill="none"
            strokeLinecap="round"
          />
        </svg>
      ))}
      {children}
    </div>
  );
}

/** A citation's parts, each kept whole, so a line breaks between them and never inside a date. */
function Parts({ items }: { items: string[] }) {
  return items.map((item, index) => (
    <span key={item}>
      {index ? " · " : null}
      <span className="whitespace-nowrap">{item}</span>
    </span>
  ));
}

const REPOSITORY = "https://github.com/alkhatibdev/dpolens";

/**
 * Beside every sign-in page: the logo, what DPOLens is for, and one question
 * answered word for word from both laws. On a phone, and on a screen too short
 * for all of it, the logo and the headline are enough.
 */
function Story() {
  const { t } = useTranslation();
  const { gdpr, uae } = SIGN_IN_CLAUSES;

  return (
    <section className="relative isolate flex flex-col overflow-hidden rounded-[24px] bg-deep px-6 pt-8 pb-9 text-white sm:px-12 sm:pt-11 lg:flex-[1.12_1_0] lg:pb-13">
      <div
        aria-hidden
        className="bg-glow pointer-events-none absolute bottom-[-60px] left-1/2 h-[760px] w-[980px] -translate-x-1/2"
      />
      <MovingOutlines />

      <div className="relative flex flex-1 flex-col">
        <Logo onDark className="h-[30px] sm:h-[34px]" />
        <h1 className="mt-10 max-w-[560px] text-[30px] leading-[1.12] font-semibold tracking-[-0.03em] text-balance sm:text-[40px] lg:mt-14 lg:text-[38px] with-both:mt-[72px] with-both:text-[44px] with-both:leading-[1.1]">
          {t("signIn.headline")}
        </h1>
        <p className="mt-4 hidden max-w-[500px] text-[17px] leading-relaxed text-deep-muted sm:block">
          {t("signIn.promise")}
        </p>

        <div className="mt-auto hidden flex-col gap-3.5 pt-10 with-clause:flex with-both:pt-14">
          <p className="flex max-w-full items-center gap-2.5 self-start rounded-full bg-white/8 py-2.5 ps-3 pe-4 text-[14.5px] leading-snug text-white/90 backdrop-blur-[6px]">
            <Search aria-hidden className="size-4 shrink-0 text-mint" strokeWidth={2.4} />
            {t("signIn.question")}
          </p>

          <Lens>
            <figure className="animate-sharpen flex flex-col gap-3 rounded-2xl bg-white px-[22px] py-5 text-ink shadow-[0_18px_40px_rgb(0_0_0/0.22)]">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <code className="rounded-lg bg-brand-soft px-2 py-[3px] font-mono text-[12.5px] text-brand-dark">
                  {gdpr.key}
                </code>
                <span className="text-[12.5px] font-semibold text-brand-dark">
                  {t("signIn.inForce")}
                </span>
              </div>
              <blockquote lang="en" className="text-[17px] leading-[1.55] font-medium">
                {gdpr.text}
              </blockquote>
              <figcaption className="text-[13px] leading-normal text-muted">
                <Parts
                  items={[
                    t("signIn.gdprWhere"),
                    t("signIn.version", { label: gdpr.version }),
                    t("signIn.since", { date: formatDate(gdpr.effective) }),
                  ]}
                />
              </figcaption>
            </figure>
          </Lens>

          <figure
            dir="rtl"
            className="mx-[18px] hidden flex-col gap-2.5 rounded-2xl border border-white/12 bg-white/6 px-5 py-4 with-both:flex"
          >
            <div>
              <code
                dir="ltr"
                className="inline-block rounded-lg bg-white/10 px-2 py-[3px] font-mono text-[12.5px] text-mint"
              >
                {uae.key}
              </code>
            </div>
            <blockquote lang="ar" className="text-[17px] text-white/95">
              {uae.text}
            </blockquote>
            <figcaption dir="ltr" className="text-end text-[13px] leading-normal text-deep-muted">
              <Parts
                items={[
                  t("signIn.uaeWhere"),
                  t("signIn.since", { date: formatDate(uae.effective) }),
                  t("signIn.arabicPrevails"),
                ]}
              />
            </figcaption>
          </figure>
        </div>
      </div>
    </section>
  );
}

/** The two halves every sign-in page shares: the story, and a white panel for the page's own form. */
export function SignInFrame({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-dvh flex-col gap-2 p-2 sm:gap-4 sm:p-4 lg:flex-row">
      <Story />
      <main className="flex flex-1 flex-col gap-8 rounded-[24px] bg-white px-6 pt-10 pb-6 sm:px-12 lg:flex-[1_1_0] lg:pb-8">
        <div className="flex flex-1 items-start justify-center lg:items-center">{children}</div>
        <p className="flex flex-wrap items-center justify-center gap-x-2.5 gap-y-1 text-[13.5px] text-muted">
          {t("signIn.openSource")}
          <a
            href={REPOSITORY}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 font-medium text-ink-2 underline underline-offset-3 hover:text-ink"
          >
            {t("signIn.viewOnGitHub")}
            <ArrowUpRight aria-hidden className="size-3.5" />
          </a>
        </p>
      </main>
    </div>
  );
}
