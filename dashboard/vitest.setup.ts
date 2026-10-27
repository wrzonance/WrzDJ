import { expect } from 'vitest';
import { configure } from '@testing-library/react';
import * as domMatchers from '@testing-library/jest-dom/matchers';
import type { TestingLibraryMatchers } from '@testing-library/jest-dom/matchers';

expect.extend(domMatchers);

// #870: findBy*/waitFor default to a 1000 ms budget. Under `--coverage` on a
// shared CI runner a post-click render can take longer than that (a 133 ms
// test was seen failing at 1144 ms), so the whole suite gets a larger budget.
// Assertions are unchanged: a wrong render still fails, it just waits longer.
configure({ asyncUtilTimeout: 4000 });

// Regression at a236d0c7: jest-dom 7's Vitest entry point still assumes the
// old single-parameter Assertion interface. Use Vitest 5's public extension API.
declare module 'vitest' {
  interface Matchers<R extends void | Promise<void> = void | Promise<void>, T = unknown>
    extends TestingLibraryMatchers<T, R> {}
}
