"use client";

import ComputerOutlinedIcon from "@mui/icons-material/ComputerOutlined";
import { useEffect, useState } from "react";
import {
  Alert,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Snackbar,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import { getModelCatalog, getProtocolSettings, normalizeModelOptions, setModelProtocol } from "@/lib/api";
import { isGatewayBackedModel } from "@/lib/model-options.mjs";
import { ModelOption } from "@/lib/types";
import { SettingsShell } from "./settings-shell";

export default function ModelProtocolSettingsClient() {
  const [models, setModels] = useState<ModelOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [protocolMap, setProtocolMap] = useState<Record<string, string>>({});
  const [savingModelId, setSavingModelId] = useState<string | null>(null);
  const [snackbarMessage, setSnackbarMessage] = useState("");
  const [snackbarOpen, setSnackbarOpen] = useState(false);
  const theme = useTheme();
  const isDesktop = useMediaQuery(theme.breakpoints.up("md"));

  const loadModels = async () => {
    try {
      setLoading(true);
      setError("");
      const [catalog, settings] = await Promise.all([getModelCatalog(), getProtocolSettings()]);
      const gatewayModels = normalizeModelOptions(catalog.data ?? []).filter((model) => isGatewayBackedModel(model));
      setModels(gatewayModels);
      setProtocolMap(settings.overrides ?? {});
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "读取模型列表失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadModels();
  }, []);

  const handleProtocolChange = async (modelId: string, protocol: string) => {
    try {
      setSavingModelId(modelId);
      await setModelProtocol(modelId, protocol);
      setProtocolMap((previous) => ({ ...previous, [modelId]: protocol }));
      setSnackbarMessage(`已保存：${modelId} → ${protocol}`);
      setSnackbarOpen(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存协议失败");
    } finally {
      setSavingModelId(null);
    }
  };

  const getCurrentProtocol = (model: ModelOption) => protocolMap[model.id] || model.metadata?.protocol || "未配置";

  return (
    <SettingsShell section="models">
      <Card variant="outlined" sx={{ boxShadow: "none" }}>
        <CardContent sx={{ p: { xs: 1.75, sm: 2.5 }, "&:last-child": { pb: { xs: 1.75, sm: 2.5 } } }}>
          <Stack spacing={2}>
            <Stack direction="row" spacing={1} alignItems="center">
              <ComputerOutlinedIcon color="primary" aria-hidden="true" />
              <Stack spacing={0.25}>
                <Typography variant="h6">Gateway 模型协议</Typography>
                <Typography variant="body2" color="text.secondary">
                  仅显示 source 包含 gateway 的模型。修改后立即保存，并用于后续请求。
                </Typography>
              </Stack>
            </Stack>

            {loading ? (
              <Stack direction="row" spacing={1.5} alignItems="center" role="status" aria-live="polite">
                <CircularProgress size={20} />
                <Typography>正在读取模型列表…</Typography>
              </Stack>
            ) : error ? (
              <Alert severity="error" role="alert">{error}</Alert>
            ) : models.length === 0 ? (
              <Alert severity="info">暂无可配置的 Gateway 模型。</Alert>
            ) : isDesktop ? (
              <TableContainer component={Paper} variant="outlined" sx={{ maxWidth: "100%" }}>
                <Table size="small" aria-label="Gateway 模型协议列表" sx={{ minWidth: 660 }}>
                  <TableHead>
                    <TableRow>
                      <TableCell>显示名称</TableCell>
                      <TableCell>模型 ID</TableCell>
                      <TableCell>当前协议</TableCell>
                      <TableCell>修改协议</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {models.map((model) => {
                      const currentProtocol = getCurrentProtocol(model);
                      return (
                        <TableRow key={model.id}>
                          <TableCell sx={{ maxWidth: 220, overflowWrap: "anywhere" }}>{model.display_name || model.id}</TableCell>
                          <TableCell sx={{ maxWidth: 300, fontFamily: "monospace", fontSize: "0.8rem", overflowWrap: "anywhere" }}>{model.id}</TableCell>
                          <TableCell>
                            <Chip size="small" label={currentProtocol} color={currentProtocol === "openai" ? "primary" : currentProtocol === "anthropic" ? "secondary" : "default"} />
                          </TableCell>
                          <TableCell>
                            <FormControl size="small" sx={{ minWidth: 140 }} disabled={savingModelId === model.id}>
                              <InputLabel id={`protocol-label-${model.id}`}>协议</InputLabel>
                              <Select
                                labelId={`protocol-label-${model.id}`}
                                value={currentProtocol === "未配置" ? "" : currentProtocol}
                                label="协议"
                                onChange={(event) => void handleProtocolChange(model.id, event.target.value)}
                                endAdornment={savingModelId === model.id ? <CircularProgress size={16} sx={{ mr: 1 }} /> : null}
                              >
                                <MenuItem value="openai">OpenAI</MenuItem>
                                <MenuItem value="anthropic">Anthropic</MenuItem>
                              </Select>
                            </FormControl>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </TableContainer>
            ) : (
              <Stack spacing={1.5}>
                {models.map((model) => {
                  const currentProtocol = getCurrentProtocol(model);
                  return (
                    <Card key={model.id} variant="outlined" sx={{ boxShadow: "none" }}>
                      <CardContent sx={{ p: 1.75, "&:last-child": { pb: 1.75 } }}>
                        <Stack spacing={1.5}>
                          <Stack direction="row" justifyContent="space-between" spacing={1} alignItems="flex-start">
                            <Typography variant="subtitle2" sx={{ fontWeight: 600, overflowWrap: "anywhere", minWidth: 0 }}>{model.display_name || model.id}</Typography>
                            <Chip size="small" label={currentProtocol} color={currentProtocol === "openai" ? "primary" : currentProtocol === "anthropic" ? "secondary" : "default"} sx={{ flexShrink: 0 }} />
                          </Stack>
                          <Typography variant="caption" color="text.secondary" sx={{ fontFamily: "monospace", overflowWrap: "anywhere" }}>{model.id}</Typography>
                          <FormControl size="small" fullWidth disabled={savingModelId === model.id}>
                            <InputLabel id={`protocol-label-mobile-${model.id}`}>修改协议</InputLabel>
                            <Select
                              labelId={`protocol-label-mobile-${model.id}`}
                              value={currentProtocol === "未配置" ? "" : currentProtocol}
                              label="修改协议"
                              onChange={(event) => void handleProtocolChange(model.id, event.target.value)}
                              endAdornment={savingModelId === model.id ? <CircularProgress size={16} sx={{ mr: 1 }} /> : null}
                            >
                              <MenuItem value="openai">OpenAI</MenuItem>
                              <MenuItem value="anthropic">Anthropic</MenuItem>
                            </Select>
                          </FormControl>
                        </Stack>
                      </CardContent>
                    </Card>
                  );
                })}
              </Stack>
            )}
          </Stack>
        </CardContent>
      </Card>

      <Snackbar open={snackbarOpen} autoHideDuration={3000} onClose={() => setSnackbarOpen(false)} message={snackbarMessage} anchorOrigin={{ vertical: "bottom", horizontal: "center" }} />
    </SettingsShell>
  );
}
