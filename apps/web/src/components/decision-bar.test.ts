import { describe, it } from 'node:test';
import assert from 'node:assert';

describe('DecisionBar', () => {
  it('should be importable', async () => {
    const { DecisionBar } = await import('./decision-bar');
    assert.strictEqual(typeof DecisionBar, 'function');
  });
});
