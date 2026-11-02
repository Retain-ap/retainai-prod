// jest-dom adds custom jest matchers for asserting on DOM nodes.
// allows you to do things like:
// expect(element).toHaveTextContent(/react/i)
// learn more: https://github.com/testing-library/jest-dom
import '@testing-library/jest-dom';
import { TextDecoder, TextEncoder } from 'util';

// CRA's jsdom environment lacks these browser APIs required by React Router 7.
global.TextEncoder = TextEncoder;
global.TextDecoder = TextDecoder;
