import { expect } from 'vitest';
import * as domMatchers from '@testing-library/jest-dom/matchers';
import type { TestingLibraryMatchers } from '@testing-library/jest-dom/matchers';

expect.extend(domMatchers);

// Regression at a236d0c7: jest-dom 7's Vitest entry point still assumes the
// old single-parameter Assertion interface. Use Vitest 5's public extension API.
declare module 'vitest' {
  interface Matchers<R extends void | Promise<void> = void | Promise<void>, T = unknown>
    extends TestingLibraryMatchers<T, R> {}
}
