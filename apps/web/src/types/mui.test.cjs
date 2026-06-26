const { describe, it } = require('node:test');
const assert = require('node:assert');
const { createTheme } = require('@mui/material/styles');

describe('MUI custom palette type extension', () => {
  it('should accept custom palette fields', () => {
    const theme = createTheme({
      palette: {
        custom: {
          bgDefault: '#F7EFE2',
          bgPaper: '#FFFAF2',
          bgElevated: '#FFFFFF',
          textPrimary: '#1A1612',
          textSecondary: '#5C5348',
          border: '#E5D9C8',
        },
      },
    });
    assert.strictEqual(theme.palette.custom.bgDefault, '#F7EFE2');
    assert.strictEqual(theme.palette.custom.bgPaper, '#FFFAF2');
    assert.strictEqual(theme.palette.custom.bgElevated, '#FFFFFF');
    assert.strictEqual(theme.palette.custom.textPrimary, '#1A1612');
    assert.strictEqual(theme.palette.custom.textSecondary, '#5C5348');
    assert.strictEqual(theme.palette.custom.border, '#E5D9C8');
  });
});
