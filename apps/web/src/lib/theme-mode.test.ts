import { describe, it } from 'node:test';
import assert from 'node:assert';

describe('theme-mode utilities', () => {
  it('只保留运行时仍使用的主题模式导出', async () => {
    const themeModeModule = await import('./theme-mode');
    assert.strictEqual(themeModeModule.STORAGE_KEY, 'theme-mode');
    assert.equal(Object.hasOwn(themeModeModule, 'getInitialMode'), false);
  });
});
