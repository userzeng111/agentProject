import { describe, it, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert';

describe('theme-mode utilities', () => {
  let originalLocalStorage: Storage | undefined;
  let store: Record<string, string>;

  beforeEach(() => {
    store = {};
    originalLocalStorage = globalThis.window?.localStorage;
    Object.defineProperty(globalThis, 'window', {
      value: {
        localStorage: {
          getItem: (key: string) => store[key] ?? null,
          setItem: (key: string, value: string) => { store[key] = value; },
          removeItem: (key: string) => { delete store[key]; },
          clear: () => { store = {}; },
        },
      },
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    if (originalLocalStorage === undefined) {
      // @ts-expect-error 清理测试注入的 window
      delete globalThis.window;
    } else {
      Object.defineProperty(globalThis, 'window', {
        value: { localStorage: originalLocalStorage },
        writable: true,
        configurable: true,
      });
    }
  });

  it('getInitialMode should default to system when window is undefined', async () => {
    // @ts-expect-error 模拟 SSR 环境
    delete globalThis.window;
    const { getInitialMode } = await import('./theme-mode.ts');
    assert.strictEqual(getInitialMode(), 'system');
  });

  it('getInitialMode should return light when localStorage has light', async () => {
    store['theme-mode'] = 'light';
    const { getInitialMode } = await import('./theme-mode.ts');
    assert.strictEqual(getInitialMode(), 'light');
  });

  it('getInitialMode should return dark when localStorage has dark', async () => {
    store['theme-mode'] = 'dark';
    const { getInitialMode } = await import('./theme-mode.ts');
    assert.strictEqual(getInitialMode(), 'dark');
  });

  it('getInitialMode should return system when localStorage has system', async () => {
    store['theme-mode'] = 'system';
    const { getInitialMode } = await import('./theme-mode.ts');
    assert.strictEqual(getInitialMode(), 'system');
  });

  it('getInitialMode should fallback to system when localStorage has invalid value', async () => {
    store['theme-mode'] = 'invalid-value';
    const { getInitialMode } = await import('./theme-mode.ts');
    assert.strictEqual(getInitialMode(), 'system');
  });

  it('getInitialMode should fallback to system when localStorage is empty', async () => {
    const { getInitialMode } = await import('./theme-mode.ts');
    assert.strictEqual(getInitialMode(), 'system');
  });
});
