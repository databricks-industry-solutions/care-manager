import { useState } from "react";
import { Moon, Sun } from "lucide-react";

const KEY = "cm-theme";

// Reflects and controls the `dark` class on <html>. The initial class is set by
// the inline script in index.html (pre-paint), so this just mirrors it.
export function useTheme() {
  const [dark, setDark] = useState(() =>
    typeof document !== "undefined" ? document.documentElement.classList.contains("dark") : false
  );
  const toggle = () => {
    setDark((prev) => {
      const next = !prev;
      document.documentElement.classList.toggle("dark", next);
      try {
        localStorage.setItem(KEY, next ? "dark" : "light");
      } catch {
        /* ignore private-mode storage errors */
      }
      return next;
    });
  };
  return { dark, toggle };
}

// Compact icon toggle. `variant="full"` shows a label (sidebar); `icon` is a
// bare circular button (mobile header).
export function ThemeToggle({ variant = "icon" }: { variant?: "icon" | "full" }) {
  const { dark, toggle } = useTheme();
  const label = dark ? "Light mode" : "Dark mode";
  if (variant === "full") {
    return (
      <button
        onClick={toggle}
        aria-label={label}
        className="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-clinical-muted transition hover:bg-clinical-bg hover:text-clinical-ink"
      >
        {dark ? <Sun size={20} className="shrink-0" /> : <Moon size={20} className="shrink-0" />}
        {label}
      </button>
    );
  }
  return (
    <button
      onClick={toggle}
      aria-label={label}
      title={label}
      className="flex h-9 w-9 items-center justify-center rounded-full border border-clinical-line text-clinical-muted transition hover:bg-clinical-bg hover:text-clinical-ink"
    >
      {dark ? <Sun size={18} /> : <Moon size={18} />}
    </button>
  );
}
