import { NavLink } from "react-router-dom";
import {
  DashboardIcon,
  LogsIcon,
  PlayIcon,
  ReportIcon,
} from "../ui/icons";

const NAV = [
  { to: "/", label: "Dashboard", icon: DashboardIcon, end: true },
  { to: "/run", label: "Run validation", icon: PlayIcon, end: false },
  { to: "/reports", label: "Reports", icon: ReportIcon, end: false },
  { to: "/logs", label: "Logs", icon: LogsIcon, end: false },
];

export function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar__brand">
        <div className="sidebar__logo">MV</div>
        <div className="sidebar__brand-text">
          <strong>Migration</strong>
          <span>Validator</span>
        </div>
      </div>
      <nav className="sidebar__nav">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              `sidebar__link ${isActive ? "sidebar__link--active" : ""}`
            }
          >
            <Icon size={18} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
      <div className="sidebar__footer">
        <span className="sidebar__muted">Validation platform · v0.1</span>
      </div>
    </aside>
  );
}
