// 小说创作应用语义化颜色 Design Token 扩展
// 扩展 MUI Palette 类型以支持自定义主题色板字段
import '@mui/material/styles';

declare module '@mui/material/styles' {
  interface Palette {
    custom: {
      bgDefault: string;
      bgPaper: string;
      bgElevated: string;
      textPrimary: string;
      textSecondary: string;
      border: string;
    };
  }

  interface PaletteOptions {
    custom?: {
      bgDefault?: string;
      bgPaper?: string;
      bgElevated?: string;
      textPrimary?: string;
      textSecondary?: string;
      border?: string;
    };
  }
}
