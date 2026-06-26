import { describe, it } from 'node:test';
import assert from 'node:assert';

describe('ProgressBar', () => {
  it('should be importable', async () => {
    const { ProgressBar } = await import('./progress-bar');
    assert.strictEqual(typeof ProgressBar, 'function');
  });
});
