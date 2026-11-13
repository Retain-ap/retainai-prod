// jest-dom adds custom jest matchers for asserting on DOM nodes.
// allows you to do things like:
// expect(element).toHaveTextContent(/react/i)
// learn more: https://github.com/testing-library/jest-dom
import '@testing-library/jest-dom/vitest';
import { vi } from 'vitest';
import { TextDecoder, TextEncoder } from 'util';

// Keep the browser encoders used by React Router 7 available in the test DOM.
global.TextEncoder = TextEncoder;
global.TextDecoder = TextDecoder;

// Testing Library 10/16 detects fake clocks through this one Jest API before
// draining waitFor/findBy microtasks. Keep that integration with Vitest's clock;
// do not alias other Jest APIs (unported mocks should still fail explicitly).
global.jest = Object.freeze({ advanceTimersByTime: vi.advanceTimersByTime });
