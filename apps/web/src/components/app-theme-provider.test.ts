import { describe, it } from 'node:test';
import assert from 'node:assert';

describe('AppThemeProvider', () => {
  it('should be importable', async () => {
    const { AppThemeProvider } = await import('./app-theme-provider');
    assert.strictEqual(typeof AppThemeProvider, 'function');
  });
});

describe('getDesignTokens', () => {
  it('light mode palette.mode is light', async () => {
    const { getDesignTokens } = await import('./app-theme-provider');
    const tokens = getDesignTokens('light');
    assert.strictEqual(tokens.palette.mode, 'light');
  });

  it('dark mode palette.mode is dark', async () => {
    const { getDesignTokens } = await import('./app-theme-provider');
    const tokens = getDesignTokens('dark');
    assert.strictEqual(tokens.palette.mode, 'dark');
  });

  it('shadows array length is 25', async () => {
    const { getDesignTokens } = await import('./app-theme-provider');
    const lightTokens = getDesignTokens('light');
    const darkTokens = getDesignTokens('dark');
    assert.strictEqual(lightTokens.shadows.length, 25);
    assert.strictEqual(darkTokens.shadows.length, 25);
  });

  it('light mode custom.bgDefault is correct', async () => {
    const { getDesignTokens } = await import('./app-theme-provider');
    const tokens = getDesignTokens('light');
    assert.strictEqual(tokens.palette.custom.bgDefault, '#F7EFE2');
  });

  it('dark mode custom.bgDefault is correct', async () => {
    const { getDesignTokens } = await import('./app-theme-provider');
    const tokens = getDesignTokens('dark');
    assert.strictEqual(tokens.palette.custom.bgDefault, '#0F1412');
  });
});
