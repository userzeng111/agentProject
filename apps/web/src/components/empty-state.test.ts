import { describe, it } from 'node:test';
import assert from 'node:assert';

describe('EmptyState', () => {
  it('should be importable', async () => {
    const { EmptyState } = await import('./empty-state');
    assert.strictEqual(typeof EmptyState, 'function');
  });
});
