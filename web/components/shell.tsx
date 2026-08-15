"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { ChartBar, GithubLogo, House, ListChecks } from "@phosphor-icons/react";
import { api, loginUrl } from "@/lib/api";
import type { User } from "@/lib/types";

const NAV = [
  { href: "/", label: "Overview", icon: House, exact: true },
  { href: "/tasks", label: "Tasks", icon: ListChecks },
  { href: "/diagnostics", label: "Diagnostics", icon: ChartBar },
];

function isActive(pathname: string, href: string, exact?: boolean): boolean {
  if (exact) return pathname === href;
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function Shell({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const pathname = usePathname();

  useEffect(() => {
    api.me().then(setUser).catch(() => setUser(null));
  }, []);

  if (user === undefined) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-fg-muted">
        Loading AIpipe…
      </div>
    );
  }

  if (user === null) {
    return (
      <div className="flex min-h-screen items-center justify-center px-6">
        <div className="w-full max-w-sm rounded-lg border border-border bg-surface p-8 text-center">
          <p className="text-lg font-semibold text-fg">AIpipe Control Center</p>
          <p className="mt-2 text-sm text-fg-muted">Sign in to manage autonomous engineering tasks across your projects.</p>
          <a
            href={loginUrl()}
            className="mt-6 inline-flex w-full items-center justify-center gap-2 rounded-md bg-accent-solid px-4 py-2.5 text-sm font-medium text-accent-fg transition-colors duration-150 hover:bg-accent-solid-hover"
          >
            <GithubLogo size={18} weight="fill" aria-hidden="true" />
            Sign in with GitHub
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#main-content"
        className="sr-only focus-visible:not-sr-only focus-visible:fixed focus-visible:left-4 focus-visible:top-4 focus-visible:z-50 focus-visible:rounded-md focus-visible:bg-accent-solid focus-visible:px-4 focus-visible:py-2 focus-visible:text-accent-fg"
      >
        Skip to content
      </a>
      <header className="sticky top-0 z-40 border-b border-border bg-canvas/95 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1400px] items-center gap-3 px-4 sm:gap-6 sm:px-6">
          <Link href="/" className="shrink-0 text-sm font-semibold tracking-tight text-fg">
            AIpipe
          </Link>
          <nav className="flex h-full min-w-0 items-center gap-0.5 sm:gap-1" aria-label="Primary">
            {NAV.map((item) => {
              const active = isActive(pathname, item.href, item.exact);
              const ItemIcon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  title={item.label}
                  className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors duration-150 sm:px-3 ${
                    active ? "bg-surface-raised text-fg" : "text-fg-muted hover:text-fg"
                  }`}
                >
                  <ItemIcon size={16} weight={active ? "fill" : "regular"} aria-hidden="true" />
                  <span className="hidden md:inline">{item.label}</span>
                </Link>
              );
            })}
          </nav>
          <div className="ml-auto flex shrink-0 items-center gap-2 text-sm text-fg-muted">
            {user.avatar_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={user.avatar_url} alt={user.login} className="h-6 w-6 rounded-full" />
            ) : null}
            <span className="hidden sm:inline">{user.login}</span>
          </div>
        </div>
      </header>
      <main id="main-content" className="mx-auto w-full max-w-[1400px] flex-1 px-6 py-8">
        {children}
      </main>
    </div>
  );
}
