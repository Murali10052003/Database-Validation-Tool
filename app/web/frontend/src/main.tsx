import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";
import { App } from "./App";
import { ThemeProvider } from "./state/ThemeContext";
import { ToastProvider } from "./state/ToastContext";
import { ActivityProvider } from "./state/ActivityContext";
import { SettingsProvider } from "./state/SettingsContext";
import "./styles/theme.css";
import "./styles/app.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <SettingsProvider>
        <ActivityProvider>
          <ToastProvider>
            <HashRouter>
              <App />
            </HashRouter>
          </ToastProvider>
        </ActivityProvider>
      </SettingsProvider>
    </ThemeProvider>
  </StrictMode>,
);
