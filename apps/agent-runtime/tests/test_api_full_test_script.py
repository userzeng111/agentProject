from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_api_full_test_module():
    root = Path(__file__).resolve().parents[3]
    script_path = root / ".agents" / "skills" / "api-full-test" / "scripts" / "run_full_test.py"
    spec = importlib.util.spec_from_file_location("api_full_test_script", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gateway_unavailable_warning_requires_flag_and_wrapped_upstream_error() -> None:
    module = _load_api_full_test_module()

    wrapped_upstream_error = {
        "detail": '流式调用失败，状态码 401，响应：{"error":{"message":"Invalid API Key","type":"invalid_key"}}'
    }

    assert module.should_warn_gateway_unavailable(502, wrapped_upstream_error, allow_gateway_unavailable=False) is False
    assert module.should_warn_gateway_unavailable(502, wrapped_upstream_error, allow_gateway_unavailable=True) is True
    assert module.should_warn_gateway_unavailable(401, {"detail": "Unauthorized API Key"}, allow_gateway_unavailable=True) is False


def test_cors_mismatch_is_recorded_as_failure() -> None:
    module = _load_api_full_test_module()
    stats = module.Stats()

    module.record_cors_result(stats, "https://example.com", "")

    assert stats.ok == 0
    assert stats.warn == 0
    assert stats.failed == 1
