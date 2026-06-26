import { describe, it } from 'node:test';
import assert from 'node:assert';

describe('AppThemeProvider', () => {
  it('should be importable', async () => {
    const { AppThemeProvider } = await import('./app-theme-provider.tsx');
    assert.strictEqual(typeof AppThemeProvider, 'function');
  });
});
