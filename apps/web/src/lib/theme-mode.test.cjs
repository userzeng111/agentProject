const { describe, it } = require('node:test');
const assert = require('node:assert');

describe('theme-mode utilities', () => {
  it('getInitialMode should default to system when window is undefined', async () => {
    const { getInitialMode } = await import('./theme-mode.ts');
    assert.strictEqual(getInitialMode(), 'system');
  });
});
