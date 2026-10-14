import { BookOpen, LogOut, Menu, Search, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet, useLocation, useNavigate, useSearchParams } from "react-router";

import { Wordmark } from "@/components/Wordmark";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Sheet, SheetClose, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { useSession, useSignOut } from "@/session";

/** The sections this release has. Each later slice adds its own here. */
const SECTIONS = [{ to: "/library", label: "nav.library", icon: BookOpen }] as const;

function Navigation({ onNavigate }: { onNavigate?: () => void }) {
  const { t } = useTranslation();
  return (
    <ul className="flex flex-col gap-1.5">
      {SECTIONS.map(({ to, label, icon: Icon }) => (
        <li key={to}>
          <NavLink
            to={to}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                "flex min-h-12 items-center gap-3 rounded-[14px] px-3 text-base text-ink-2 hover:bg-field",
                isActive && "bg-brand-soft font-semibold text-brand-dark hover:bg-brand-soft",
              )
            }
          >
            <Icon aria-hidden className="size-5" />
            {t(label)}
          </NavLink>
        </li>
      ))}
    </ul>
  );
}

function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const first = parts[0]?.[0] ?? "";
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? "") : "";
  return (first + last).toUpperCase() || "?";
}

function AccountMenu() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const session = useSession();
  const signOut = useSignOut();
  const account = session.data?.account;
  if (!account) {
    return null;
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label={t("account.open")}
        className="grid size-11 shrink-0 place-items-center rounded-full bg-brand-soft text-[15px] font-semibold text-brand-dark hover:bg-brand-mid/40"
      >
        {initialsOf(account.display_name)}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>
          <div className="text-[15px] font-semibold">{account.display_name}</div>
          <div className="text-[13px] text-muted">{account.roles.join(", ")}</div>
          <div className="mt-1 text-[13px] break-all text-muted">{account.email}</div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={() =>
            signOut.mutate(undefined, { onSettled: () => navigate("/sign-in", { replace: true }) })
          }
        >
          <LogOut aria-hidden />
          {t("account.signOut")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function SearchBox() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [query, setQuery] = useState(params.get("q") ?? "");

  function submit(event: FormEvent) {
    event.preventDefault();
    const asked = query.trim();
    if (asked) {
      navigate(`/search?q=${encodeURIComponent(asked)}`);
    }
  }

  return (
    <form role="search" onSubmit={submit} className="min-w-0 flex-1 sm:max-w-[560px]">
      <label className="flex h-12 items-center gap-2.5 rounded-full bg-field px-4">
        <Search aria-hidden className="size-[18px] shrink-0 text-muted" />
        <span className="sr-only">{t("search.label")}</span>
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("search.placeholder")}
          dir="auto"
          className="min-w-0 flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-muted"
        />
      </label>
    </form>
  );
}

export function Shell() {
  const { t } = useTranslation();
  const [menuOpen, setMenuOpen] = useState(false);
  const onSearch = useLocation().pathname === "/search";

  return (
    <div className="flex min-h-dvh gap-4 p-2 sm:p-4">
      <nav
        aria-label={t("nav.label")}
        className="hidden w-[260px] shrink-0 flex-col gap-2 self-start rounded-[24px] bg-white px-4 py-7 lg:sticky lg:top-4 lg:flex"
      >
        <Wordmark className="px-3 pb-6" />
        <Navigation />
      </nav>

      <div className="flex min-w-0 flex-1 flex-col gap-2 sm:gap-4">
        <header className="flex items-center gap-2 rounded-[20px] bg-white p-2 sm:gap-3 sm:rounded-[24px] sm:p-3.5 sm:ps-5">
          <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
            <SheetTrigger
              aria-label={t("nav.open")}
              className="grid size-11 shrink-0 place-items-center rounded-full bg-field lg:hidden"
            >
              <Menu aria-hidden className="size-5" />
            </SheetTrigger>
            <SheetContent>
              <div className="flex items-center justify-between pb-6">
                <SheetTitle asChild>
                  <Wordmark className="px-3" />
                </SheetTitle>
                <SheetClose
                  aria-label={t("nav.close")}
                  className="grid size-11 place-items-center rounded-full bg-field"
                >
                  <X aria-hidden className="size-5" />
                </SheetClose>
              </div>
              <nav aria-label={t("nav.label")}>
                <Navigation onNavigate={() => setMenuOpen(false)} />
              </nav>
            </SheetContent>
          </Sheet>
          {onSearch ? (
            <span className="ps-1 text-[15px] font-medium text-ink-2">{t("search.label")}</span>
          ) : (
            <SearchBox />
          )}
          <div className="ms-auto">
            <AccountMenu />
          </div>
        </header>

        <main className="min-w-0 flex-1">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
