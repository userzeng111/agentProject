import { describe, it } from 'node:test';
import assert from 'node:assert';

describe('NotificationCenter', () => {
  it('should be importable', async () => {
    const { NotificationProvider, useNotification } = await import('./notification-center');
    assert.strictEqual(typeof NotificationProvider, 'function');
    assert.strictEqual(typeof useNotification, 'function');
  });
});
