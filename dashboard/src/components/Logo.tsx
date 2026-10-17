import type { ComponentProps } from "react";
import { useTranslation } from "react-i18next";

import logoOnDark from "@/assets/brand/dpolens-logo-on-dark.svg";
import logo from "@/assets/brand/dpolens-logo.svg";
import { cn } from "@/lib/utils";

/** The logo as the brand kit draws it, the mark and the name; `onDark` for the deep green. */
export function Logo({
  onDark = false,
  className,
  ...props
}: ComponentProps<"img"> & { onDark?: boolean }) {
  const { t } = useTranslation();
  return (
    <img
      src={onDark ? logoOnDark : logo}
      alt={t("app.name")}
      width={146}
      height={32}
      className={cn("block h-8 w-fit", className)}
      {...props}
    />
  );
}
