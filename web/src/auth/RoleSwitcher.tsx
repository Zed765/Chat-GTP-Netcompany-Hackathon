import { useLocation, useNavigate } from "react-router";
import { ROLES } from "../lib/labels";
import { HOME, isDemoRole, pagesFor } from "../pages";
import { Segmented } from "../ui/controls";
import { useAuth } from "./context";

/** The demo's stand-in for sign-in: one click to become the employee or the admin. */
export function RoleSwitcher() {
  const { user, users, signIn, switchingTo } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();

  async function onChange(userId: string) {
    const next = users.find((candidate) => candidate.user_id === userId);
    if (!next || next.user_id === user.user_id) return;
    await signIn(userId);
    const allowed = pagesFor(next.role).some((page) => page.path === pathname);
    if (!allowed && isDemoRole(next.role)) void navigate(HOME[next.role]);
  }

  return (
    <div className="signin">
      <span className="signin-label" aria-hidden="true">
        Demo sign-in
      </span>
      <Segmented
        legend="Demo sign-in"
        hideLegend
        options={users.map((candidate) => ({ value: candidate.user_id, label: ROLES[candidate.role] }))}
        value={switchingTo ?? user.user_id}
        onChange={(userId) => void onChange(userId)}
        disabled={switchingTo !== null}
      />
      <span className="signin-user" aria-live="polite">
        Signed in as {user.display_name}, {user.team}
      </span>
    </div>
  );
}
