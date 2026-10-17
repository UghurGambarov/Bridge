// Demo mode (?demo=1): a caption bar driven by window.__demoCaption(text), used by the autopilot.
import { useEffect, useState } from "react";

declare global {
  interface Window {
    __demoCaption?: (text: string) => void;
  }
}

export function isDemo(): boolean {
  const on = new URLSearchParams(window.location.search).get("demo");
  try {
    if (on === "1") sessionStorage.setItem("bridge.demo", "1");
    if (on === "0") sessionStorage.removeItem("bridge.demo");
    return sessionStorage.getItem("bridge.demo") === "1";
  } catch {
    return on === "1";
  }
}

export function useDemoCaption(): string {
  const [caption, setCaption] = useState("");
  useEffect(() => {
    window.__demoCaption = (text: string) => setCaption(text);
    return () => {
      delete window.__demoCaption;
    };
  }, []);
  return caption;
}

// Minimal client-side routing (no router dependency).
export function navigate(path: string) {
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function usePath(): string {
  const [path, setPath] = useState(window.location.pathname);
  useEffect(() => {
    const on = () => setPath(window.location.pathname);
    window.addEventListener("popstate", on);
    return () => window.removeEventListener("popstate", on);
  }, []);
  return path;
}
