"use client";

import {
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  type SelectChangeEvent,
} from "@mui/material";

interface ModelOption {
  value: string;
  label: string;
  disabled?: boolean;
}

interface ModelSelectProps {
  label: string;
  value: string;
  options: ModelOption[];
  onChange: (value: string) => void;
  disabled?: boolean;
  size?: "small" | "medium";
}

export function ModelSelect({
  label,
  value,
  options,
  onChange,
  disabled = false,
  size = "small",
}: ModelSelectProps) {
  const handleChange = (event: SelectChangeEvent<string>) => {
    onChange(event.target.value);
  };

  const labelId = `model-select-${label}`;

  return (
    <FormControl fullWidth size={size} disabled={disabled}>
      <InputLabel id={labelId}>{label}</InputLabel>
      <Select
        labelId={labelId}
        value={value}
        label={label}
        onChange={handleChange}
      >
        {options.map((option) => (
          <MenuItem key={option.value} value={option.value} disabled={option.disabled}>
            {option.label}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
}

export type { ModelOption };
