import { describe, it } from 'node:test';
import assert from 'node:assert';

describe('StageBadge', () => {
  it('should be importable', async () => {
    const { StageBadge } = await import('./stage-badge');
    assert.strictEqual(typeof StageBadge, 'function');
  });
});
