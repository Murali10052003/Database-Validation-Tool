import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { ToastHost } from "../ui/ToastHost";

export function AppLayout() {
  return (
    <div className="app-shell">
      <Sidebar />
      <main className="app-main">
        <Outlet />
      </main>
      <ToastHost />
    </div>
  );
}
