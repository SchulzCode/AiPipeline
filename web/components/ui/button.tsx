import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent-solid text-accent-fg hover:bg-accent-solid-hover active:scale-[0.98]",
  secondary: "border border-border-strong bg-surface-raised text-fg hover:border-fg-faint active:scale-[0.98]",
  ghost: "text-fg-muted hover:bg-surface-raised hover:text-fg active:scale-[0.98]",
  danger: "border border-status-failed/40 bg-status-failed/10 text-status-failed hover:bg-status-failed/20 active:scale-[0.98]",
};

export function Button({
  variant = "secondary",
  className = "",
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-1.5 rounded-md px-3.5 py-2 text-sm font-medium transition-[transform,background-color,border-color] duration-150 ease-out disabled:pointer-events-none disabled:opacity-50 ${VARIANTS[variant]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}
