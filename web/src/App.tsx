import { Suspense, useEffect, useRef, useState } from "react";
import { Link, Navigate, Route, Routes, useLocation, useNavigate } from "react-router";
import { AuthProvider } from "./auth/AuthProvider";
import { RoleSwitcher } from "./auth/RoleSwitcher";
import { useAuth } from "./auth/context";
import { useTheme } from "./hooks/useTheme";
import { ROLES } from "./lib/labels";
import { HOME, PAGES, type Page, isDemoRole, pagesFor } from "./pages";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { ErrorBoundary } from "./ui/ErrorBoundary";
import { Icon } from "./ui/Icon";
import { PageHeader } from "./ui/PageHeader";
import { EmptyState, Loading } from "./ui/States";

function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button type="button" className="btn btn-ghost btn-icon" onClick={toggle} title={`Switch to the ${next} theme`}>
      <Icon name={theme === "dark" ? "sun" : "moon"} label={`Switch to the ${next} theme`} />
    </button>
  );
}

/** The width from which the menu sits beside the page; it matches the breakpoint in components.css. */
const WIDE_SCREEN = "(min-width: 60.01rem)";

/**
 * The pages, as buttons and not links: a link would make the browser show its address at the
 * bottom of the window whenever the pointer rests on it.
 */
function Navigation({ open, onNavigate }: { open: boolean; onNavigate: () => void }) {
  const { user } = useAuth();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const pages = pagesFor(user.role);
  return (
    <nav id="site-nav" className="sidenav" aria-label="Pages" data-open={open}>
      <ul>
        {pages.map((page) => (
          <li key={page.path}>
            <button
              type="button"
              className="sidenav-item"
              aria-current={pathname === page.path ? "page" : undefined}
              title={page.title}
              onClick={() => {
                void navigate(page.path);
                onNavigate();
              }}
            >
              <Icon name={page.icon} />
              <span className="sidenav-label">{page.title}</span>
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}

/** Shows a page to the roles that may use it; anyone else is offered the right demo sign-in. */
function RoleGate({ page }: { page: Page }) {
  const { user, users, signIn, switchingTo } = useAuth();
  const PageComponent = page.component;
  if (isDemoRole(user.role) && page.roles.includes(user.role)) return <PageComponent />;
  const candidates = users.filter((candidate) => isDemoRole(candidate.role) && page.roles.includes(candidate.role));
  return (
    <div className="page">
      <PageHeader title={page.title} />
      <EmptyState
        icon="lock"
        title={`This page is for the ${candidates.map((candidate) => ROLES[candidate.role].toLowerCase()).join(" or the ")}`}
        action={
          <div className="row">
            {candidates.map((candidate) => (
              <Button key={candidate.user_id} variant="primary" busy={switchingTo === candidate.user_id} onClick={() => void signIn(candidate.user_id)}>
                Continue as {ROLES[candidate.role].toLowerCase()}
              </Button>
            ))}
          </div>
        }
      >
        You are signed in as {ROLES[user.role].toLowerCase()}. This is a demo, so you can switch role with one click.
      </EmptyState>
    </div>
  );
}

function NotFound() {
  const { user } = useAuth();
  return (
    <div className="page">
      <PageHeader title="Page not found" />
      <EmptyState title="There is nothing at this address" action={<Link className="btn" to={isDemoRole(user.role) ? HOME[user.role] : "/"}>Go to the start page</Link>} />
    </div>
  );
}

function Shell() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { pathname } = useLocation();
  // Open on a wide screen, where a closed menu is a rail of icons; closed on a narrow one, where it is hidden.
  const [navOpen, setNavOpen] = useState(() => window.matchMedia(WIDE_SCREEN).matches);
  const main = useRef<HTMLElement>(null);
  const shownPath = useRef(pathname);

  // After a navigation, keyboard and screen-reader users continue from the new page's content.
  useEffect(() => {
    if (shownPath.current === pathname) return;
    shownPath.current = pathname;
    main.current?.focus();
  }, [pathname]);

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="topbar">
        <button
          type="button"
          className="btn btn-ghost btn-icon nav-toggle"
          aria-expanded={navOpen}
          aria-controls="site-nav"
          onClick={() => setNavOpen((open) => !open)}
        >
          <Icon name="menu" label={navOpen ? "Collapse the menu" : "Expand the menu"} />
        </button>
        <button type="button" className="brand" onClick={() => void navigate("/chat")}>
          <span className="brand-mark" />
          A.S.P.I.D.A.
        </button>
        {__MOCK_API__ && (
          <Badge hue="violet" title="This build has no backend: every number and record on screen is built-in sample data.">
            Sample data
          </Badge>
        )}
        <span className="topbar-spacer" />
        <div className="topbar-tools">
          <RoleSwitcher />
          <ThemeToggle />
        </div>
      </header>
      <Navigation open={navOpen} onNavigate={() => setNavOpen(window.matchMedia(WIDE_SCREEN).matches && navOpen)} />
      <main id="main" className="main" tabIndex={-1} ref={main}>
        <ErrorBoundary resetKey={`${pathname}:${user.user_id}`}>
          <Suspense fallback={<Loading label="Loading page" />}>
            {/* Keyed by user, so a role switch reloads the page's data under the new session. */}
            <Routes key={user.user_id}>
              <Route path="/" element={<Navigate to={isDemoRole(user.role) ? HOME[user.role] : "/chat"} replace />} />
              {PAGES.map((page) => (
                <Route key={page.path} path={page.path} element={<RoleGate page={page} />} />
              ))}
              <Route path="*" element={<NotFound />} />
            </Routes>
          </Suspense>
        </ErrorBoundary>
      </main>
    </div>
  );
}

export function App() {
  return (
    <AuthProvider>
      <Shell />
    </AuthProvider>
  );
}
