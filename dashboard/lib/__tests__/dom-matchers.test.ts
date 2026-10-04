import { expect, expectTypeOf, it } from 'vitest';

it('preserves synchronous and asynchronous DOM matcher return types', async () => {
  // Regression for the Vitest 5 migration from a236d0c7.
  const element = document.createElement('div');
  document.body.append(element);
  try {
    const syncResult = expect(element).toBeInTheDocument();
    expectTypeOf(syncResult).toEqualTypeOf<void>();
    const asyncResult = expect(Promise.resolve(element)).resolves.toBeInTheDocument();
    expectTypeOf(asyncResult).toEqualTypeOf<Promise<void>>();
    await asyncResult;
  } finally {
    element.remove();
  }
});
