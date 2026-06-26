import { describe, it } from 'node:test';
import assert from 'node:assert';

describe('ConfirmDialog', () => {
  it('should be importable', async () => {
    const { ConfirmDialog } = await import('./confirm-dialog');
    assert.strictEqual(typeof ConfirmDialog, 'function');
  });
});
