import { describe, it } from 'node:test';
import assert from 'node:assert';

describe('PageContainer', () => {
  it('should be importable', async () => {
    const { PageContainer } = await import('./page-container');
    assert.strictEqual(typeof PageContainer, 'function');
  });
});
