import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import "@/i18n";

afterEach(() => {
  cleanup();
  // A remembered reading language would carry from one test into the next.
  localStorage.clear();
});

// What jsdom leaves out and Radix's menus reach for.
class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserver as unknown as typeof globalThis.ResizeObserver;
Element.prototype.scrollIntoView ??= () => {};
Element.prototype.hasPointerCapture ??= () => false;
Element.prototype.releasePointerCapture ??= () => {};
