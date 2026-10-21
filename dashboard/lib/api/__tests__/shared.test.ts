import { describe, expect, it } from 'vitest';

import { ApiError, apiErrorFromBody } from '../shared';

// Regression for #851: FastAPI returns request-validation failures (422) as a
// list of Pydantic items, which used to collapse to "Request failed".
describe('apiErrorFromBody', () => {
  it('uses a string detail verbatim', () => {
    const err = apiErrorFromBody({ detail: 'Incorrect verification code' }, 400);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toBe('Incorrect verification code');
    expect(err.status).toBe(400);
  });

  it('uses message and code from an object detail', () => {
    const err = apiErrorFromBody({ detail: { code: 'nickname_taken', message: 'Name is taken' } }, 409);
    expect(err.message).toBe('Name is taken');
    expect(err.code).toBe('nickname_taken');
  });

  it('surfaces the first Pydantic validation message without its "Value error, " prefix', () => {
    const err = apiErrorFromBody(
      {
        detail: [
          {
            type: 'value_error',
            loc: ['body', 'nickname'],
            msg: 'Value error, Please choose a different name',
            input: 'poopyfarty',
          },
        ],
      },
      422,
    );
    expect(err.message).toBe('Please choose a different name');
    expect(err.status).toBe(422);
  });

  it('names the field for generic Pydantic messages', () => {
    const err = apiErrorFromBody(
      {
        detail: [
          { type: 'string_too_short', loc: ['body', 'nickname'], msg: 'String should have at least 2 characters' },
          { type: 'missing', loc: ['body', 'email'], msg: 'Field required' },
        ],
      },
      422,
    );
    expect(err.message).toBe('nickname: String should have at least 2 characters');
  });

  it('falls back when the list carries no usable message', () => {
    expect(apiErrorFromBody({ detail: [] }, 422).message).toBe('Request failed');
    expect(apiErrorFromBody({ detail: [{ loc: ['body'] }] }, 422).message).toBe('Request failed');
    expect(apiErrorFromBody(null, 500).message).toBe('Request failed');
  });
});
