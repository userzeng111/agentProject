import { describe, it } from 'node:test';
import assert from 'node:assert';

describe('ModelSelect', () => {
  it('should be importable', async () => {
    const { ModelSelect } = await import('./model-select');
    assert.strictEqual(typeof ModelSelect, 'function');
  });
});
