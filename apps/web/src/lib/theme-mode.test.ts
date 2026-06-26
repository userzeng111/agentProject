import { describe, it } from 'node:test';
import assert from 'node:assert';

describe('theme-mode utilities', () => {
  it('getInitialMode should default to system when window is undefined', async () => {
    const { getInitialMode } = await import('./theme-mode.ts');
    assert.strictEqual(getInitialMode(), 'system');
  });
});
