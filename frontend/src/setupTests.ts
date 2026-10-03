import "@testing-library/jest-dom/vitest";

// recharts measures its container; jsdom has no ResizeObserver
globalThis.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};
