"""Tests for security utilities: SSRF protection, code sandbox, API key auth.
"""
import os

import pytest

from app.config import Settings
from app.security import (
    SandboxedRunner,
    SandboxTimeoutError,
    is_safe_url,
    require_api_key,
)

# ─── SSRF protection ─────────────────────────────────────────────────────


class TestSSRFProtection:
    def test_blocks_localhost(self, settings):
        ok, reason = is_safe_url("http://127.0.0.1:8000/api", settings)
        assert not ok
        assert "blocked" in reason.lower() or "private" in reason.lower()

    def test_blocks_private_ip(self, settings):
        ok, reason = is_safe_url("http://192.168.1.1/admin", settings)
        assert not ok

    def test_blocks_10_x(self, settings):
        ok, reason = is_safe_url("http://10.0.0.1/internal", settings)
        assert not ok

    def test_blocks_link_local(self, settings):
        # 169.254.169.254 is the AWS metadata endpoint
        ok, reason = is_safe_url("http://169.254.169.254/latest/meta-data/", settings)
        assert not ok

    def test_blocks_non_http_scheme(self, settings):
        ok, reason = is_safe_url("file:///etc/passwd", settings)
        assert not ok
        assert "scheme" in reason.lower()

    def test_allows_public_url(self, settings):
        ok, reason = is_safe_url("https://api.openai.com/v1/chat", settings)
        # May fail if no network — but should not be blocked by SSRF rules
        # If it can't resolve, that's also "not ok" but for a different reason
        if not ok:
            assert "resolve" in reason.lower() or "not in allowed" in reason.lower()

    def test_allowlist_enforced(self):
        s = Settings(http_allowed_hosts=["api.openai.com"])
        ok, reason = is_safe_url("https://api.openai.com/v1", s)
        # Should pass allowlist (may fail on resolve if no network)
        if not ok:
            assert "resolve" in reason.lower()

        ok2, reason2 = is_safe_url("https://evil.com/v1", s)
        assert not ok2
        assert "allowed" in reason2.lower()


# ─── Code sandbox ────────────────────────────────────────────────────────


class TestCodeSandbox:
    def test_basic_execution(self, settings):
        runner = SandboxedRunner(settings)
        result = runner.run("result = 1 + 2", {}, {})
        assert result == 3

    def test_access_inputs(self, settings):
        runner = SandboxedRunner(settings)
        result = runner.run("result = inputs['val'] * 2", {"val": 21}, {})
        assert result == 42

    def test_blocked_import_os(self, settings):
        runner = SandboxedRunner(settings)
        with pytest.raises((ImportError, RuntimeError)):
            runner.run("import os; result = os.listdir('/')", {}, {})

    def test_blocked_import_subprocess(self, settings):
        runner = SandboxedRunner(settings)
        with pytest.raises((ImportError, RuntimeError)):
            runner.run("import subprocess; result = subprocess.check_output(['id'])", {}, {})

    def test_allowed_import_json(self, settings):
        runner = SandboxedRunner(settings)
        result = runner.run("result = json.loads('{\"a\": 1}')", {}, {})
        assert result == {"a": 1}

    def test_main_function(self, settings):
        runner = SandboxedRunner(settings)
        result = runner.run("def main():\n    return [1, 2, 3]\n", {}, {})
        assert result == [1, 2, 3]

    def test_no_open_builtin(self, settings):
        runner = SandboxedRunner(settings)
        with pytest.raises((KeyError, NameError, RuntimeError)):
            runner.run("f = open('/etc/passwd'); result = f.read()", {}, {})

    def test_timeout(self, settings):
        runner = SandboxedRunner(settings)
        settings.code_max_cpu_seconds = 1
        with pytest.raises(SandboxTimeoutError):
            runner.run("while True:\n    pass\n", {}, {}, timeout=1)

    def test_output_size_limit(self, settings):
        runner = SandboxedRunner(settings)
        settings.max_code_output_bytes = 10
        with pytest.raises(ValueError, match="exceeds limit"):
            runner.run("result = 'x' * 1000", {}, {})


# ─── API key auth ────────────────────────────────────────────────────────


class TestAPIKeyAuth:
    @pytest.mark.asyncio
    async def test_no_key_in_dev_mode(self):
        """In development with no API key set, auth should be disabled."""
        os.environ["AITA_API_KEY"] = ""
        os.environ["AITA_ENV"] = "development"
        from app.config import get_settings
        get_settings.cache_clear()
        # Call directly with settings resolved (bypassing FastAPI Depends)
        settings = get_settings()
        user = await require_api_key(x_api_key=None, settings=settings)
        assert user == "anonymous"

    @pytest.mark.asyncio
    async def test_valid_key_accepted(self):
        os.environ["AITA_API_KEY"] = "test-secret-key"
        os.environ["AITA_ENV"] = "development"
        from app.config import get_settings
        get_settings.cache_clear()
        settings = get_settings()
        user = await require_api_key(x_api_key="test-secret-key", settings=settings)
        assert user == "test-secret-key"

    @pytest.mark.asyncio
    async def test_invalid_key_rejected(self):
        os.environ["AITA_API_KEY"] = "correct-key"
        os.environ["AITA_ENV"] = "development"
        from app.config import get_settings
        get_settings.cache_clear()
        from fastapi import HTTPException
        settings = get_settings()
        with pytest.raises(HTTPException) as exc:
            await require_api_key(x_api_key="wrong-key", settings=settings)
        assert exc.value.status_code == 401

    def teardown_method(self):
        """Reset env after each test."""
        os.environ["AITA_API_KEY"] = ""
        os.environ["AITA_ENV"] = "development"
        from app.config import get_settings
        get_settings.cache_clear()
