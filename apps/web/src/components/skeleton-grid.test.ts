import { describe, it } from 'node:test';
import assert from 'node:assert';

describe('SkeletonGrid', () => {
  it('should be importable', async () => {
    const { SkeletonGrid } = await import('./skeleton-grid');
    assert.strictEqual(typeof SkeletonGrid, 'function');
  });
});
