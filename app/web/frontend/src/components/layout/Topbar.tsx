import { useTheme } from "../../state/ThemeContext";
import { MoonIcon, SunIcon } from "../ui/icons";

interface TopbarProps {
  title: string;
  subtitle?: string;
}

export function Topbar({ title, subtitle }: TopbarProps) {
  const { theme, toggle } = useTheme();
  return (
    <header className="topbar">
      <div className="topbar__titles">
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      <div className="topbar__actions">
        <button
          type="button"
          className="theme-toggle"
          onClick={toggle}
          aria-label={`Switch to ${theme === "light" ? "dark" : "light"} theme`}
          title={`Switch to ${theme === "light" ? "dark" : "light"} theme`}
        >
          {theme === "light" ? <MoonIcon size={18} /> : <SunIcon size={18} />}
        </button>
      </div>
    </header>
  );
}
