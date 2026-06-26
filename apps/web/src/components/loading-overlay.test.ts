import { describe, it } from 'node:test';
import assert from 'node:assert';

describe('LoadingOverlay', () => {
  it('should be importable', async () => {
    const { LoadingOverlay } = await import('./loading-overlay');
    assert.strictEqual(typeof LoadingOverlay, 'function');
  });
});
