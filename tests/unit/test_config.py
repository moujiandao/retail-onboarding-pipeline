"""
Tests for configuration management.

Testing Philosophy:
-------------------
1. Configuration code must be thoroughly tested because it affects everything
2. Use mocking to avoid depending on actual .env files
3. Test both success and failure cases
4. Verify error messages are helpful (they'll be seen by operators)

Key Testing Patterns Demonstrated:
-----------------------------------
- patch.dict() for mocking environment variables
- pytest.raises() for testing exceptions
- Fixture isolation (each test gets clean environment)
- Testing cached singletons (reload parameter)
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.utils.config import (
    Config,
    ConfigurationError,
    get_config,
    require_aws_config,
    require_snowflake_config,
)


class TestGetConfig:
    """
    Tests for the get_config function.

    Why group tests in classes?
    - Logical organization
    - Shared setup/teardown if needed
    - Clear test naming with TestClass::test_method
    """

    def test_returns_config_with_defaults(self):
        """
        Config loads successfully with minimal environment.

        This tests the "happy path" for local development where
        cloud services aren't configured.
        """
        # patch.dict() temporarily modifies os.environ
        # clear=True removes all existing env vars for isolation
        with patch.dict(os.environ, {}, clear=True):
            config = get_config(reload=True)

            # Verify defaults are applied
            assert config.log_level == "INFO"
            assert config.environment == "development"
            assert config.aws_region == "us-west-2"
            assert config.tesseract_lang == "eng"
            assert config.ge_failure_threshold == 0.95

    def test_reads_environment_variables(self):
        """Config picks up values from environment."""
        test_env = {
            "LOG_LEVEL": "DEBUG",
            "ENVIRONMENT": "production",
            "SNOWFLAKE_ACCOUNT": "test-account",
            "GE_FAILURE_THRESHOLD": "0.85",
        }

        with patch.dict(os.environ, test_env, clear=True):
            config = get_config(reload=True)

            assert config.log_level == "DEBUG"
            assert config.environment == "production"
            assert config.snowflake_account == "test-account"
            assert config.ge_failure_threshold == 0.85

    def test_caches_config_by_default(self):
        """
        Config is cached to avoid repeated parsing.

        Why cache?
        - Performance: Don't re-parse env vars on every call
        - Consistency: Config doesn't change during app lifecycle
        """
        with patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"}, clear=True):
            config1 = get_config(reload=True)

        # Change environment, but don't reload
        with patch.dict(os.environ, {"LOG_LEVEL": "ERROR"}, clear=True):
            config2 = get_config(reload=False)

        # Should still be the cached value
        assert config2.log_level == "DEBUG"
        # Both calls should return the same object
        assert config1 is config2

    def test_reload_refreshes_config(self):
        """reload=True forces re-reading from environment."""
        with patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"}, clear=True):
            config1 = get_config(reload=True)

        with patch.dict(os.environ, {"LOG_LEVEL": "ERROR"}, clear=True):
            config2 = get_config(reload=True)

        assert config1.log_level == "DEBUG"
        assert config2.log_level == "ERROR"

    def test_data_dir_converted_to_path(self):
        """
        DATA_DIR string is converted to Path object.

        Why Path objects?
        - Cross-platform path handling (Windows vs Unix)
        - Rich API for path operations (.exists(), .glob(), etc.)
        - Type safety (can't accidentally do string operations)
        """
        with patch.dict(os.environ, {"DATA_DIR": "/custom/data"}, clear=True):
            config = get_config(reload=True)

            assert isinstance(config.data_dir, Path)
            assert config.data_dir == Path("/custom/data")

    def test_ge_failure_threshold_parsed_as_float(self):
        """GE_FAILURE_THRESHOLD is parsed as float."""
        with patch.dict(os.environ, {"GE_FAILURE_THRESHOLD": "0.85"}, clear=True):
            config = get_config(reload=True)

            assert config.ge_failure_threshold == 0.85
            assert isinstance(config.ge_failure_threshold, float)

    def test_invalid_float_raises_error(self):
        """
        Invalid float values raise ConfigurationError with clear message.

        Why test error cases?
        - Operators will see these errors
        - Error messages must be actionable
        """
        with patch.dict(os.environ, {"GE_FAILURE_THRESHOLD": "not-a-number"}, clear=True):
            with pytest.raises(ConfigurationError) as exc_info:
                get_config(reload=True)

            # Verify error message is helpful
            assert "GE_FAILURE_THRESHOLD" in str(exc_info.value)
            assert "not-a-number" in str(exc_info.value)


class TestConfigProperties:
    """Tests for Config computed properties."""

    def test_is_production_true_for_production(self):
        """is_production returns True when environment is production."""
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}, clear=True):
            config = get_config(reload=True)
            assert config.is_production is True

    def test_is_production_false_for_development(self):
        """is_production returns False for non-production environments."""
        with patch.dict(os.environ, {"ENVIRONMENT": "development"}, clear=True):
            config = get_config(reload=True)
            assert config.is_production is False

    def test_is_production_case_insensitive(self):
        """is_production check is case-insensitive."""
        with patch.dict(os.environ, {"ENVIRONMENT": "PRODUCTION"}, clear=True):
            config = get_config(reload=True)
            assert config.is_production is True

    def test_is_development_true_for_development(self):
        """is_development returns True when environment is development."""
        with patch.dict(os.environ, {"ENVIRONMENT": "development"}, clear=True):
            config = get_config(reload=True)
            assert config.is_development is True

    def test_data_directory_properties(self):
        """
        Data directory properties return correct paths.

        These computed properties provide convenient access to
        common directories without repeating path logic.
        """
        with patch.dict(os.environ, {"DATA_DIR": "/data"}, clear=True):
            config = get_config(reload=True)

            assert config.raw_data_dir == Path("/data/raw")
            assert config.processed_data_dir == Path("/data/processed")
            assert config.staging_data_dir == Path("/data/staging")
            assert config.quarantine_data_dir == Path("/data/quarantine")


class TestRequireSnowflakeConfig:
    """
    Tests for Snowflake configuration validation.

    Why validate in a separate function?
    - Not all code needs Snowflake (e.g., local dev with mock data)
    - Fail fast when we DO need it
    - Clear error messages about what's missing
    """

    def test_passes_with_complete_config(self):
        """No error when all required Snowflake config is present."""
        test_env = {
            "SNOWFLAKE_ACCOUNT": "test-account",
            "SNOWFLAKE_USER": "test-user",
            "SNOWFLAKE_PASSWORD": "test-password",
            "SNOWFLAKE_DATABASE": "test-db",
        }

        with patch.dict(os.environ, test_env, clear=True):
            config = get_config(reload=True)
            # Should not raise
            require_snowflake_config(config)

    def test_fails_with_missing_account(self):
        """Raises ConfigurationError when account is missing."""
        test_env = {
            "SNOWFLAKE_USER": "test-user",
            "SNOWFLAKE_PASSWORD": "test-password",
            "SNOWFLAKE_DATABASE": "test-db",
        }

        with patch.dict(os.environ, test_env, clear=True):
            config = get_config(reload=True)

            with pytest.raises(ConfigurationError) as exc_info:
                require_snowflake_config(config)

            assert "SNOWFLAKE_ACCOUNT" in str(exc_info.value)

    def test_fails_with_multiple_missing(self):
        """
        Error message lists all missing config.

        Why list all missing items?
        - User can fix everything at once
        - Avoids "fix one, run again, see next error" loop
        """
        with patch.dict(os.environ, {}, clear=True):
            config = get_config(reload=True)

            with pytest.raises(ConfigurationError) as exc_info:
                require_snowflake_config(config)

            error_msg = str(exc_info.value)
            assert "SNOWFLAKE_ACCOUNT" in error_msg
            assert "SNOWFLAKE_USER" in error_msg
            assert "SNOWFLAKE_PASSWORD" in error_msg
            assert "SNOWFLAKE_DATABASE" in error_msg


class TestRequireAwsConfig:
    """Tests for AWS configuration validation."""

    def test_passes_with_complete_config(self):
        """No error when all required AWS config is present."""
        test_env = {
            "AWS_ACCESS_KEY_ID": "test-key",
            "AWS_SECRET_ACCESS_KEY": "test-secret",
            "S3_BUCKET": "test-bucket",
        }

        with patch.dict(os.environ, test_env, clear=True):
            config = get_config(reload=True)
            # Should not raise
            require_aws_config(config)

    def test_fails_with_missing_credentials(self):
        """Raises ConfigurationError when credentials are missing."""
        test_env = {
            "S3_BUCKET": "test-bucket",
        }

        with patch.dict(os.environ, test_env, clear=True):
            config = get_config(reload=True)

            with pytest.raises(ConfigurationError) as exc_info:
                require_aws_config(config)

            error_msg = str(exc_info.value)
            assert "AWS_ACCESS_KEY_ID" in error_msg
            assert "AWS_SECRET_ACCESS_KEY" in error_msg

    def test_fails_with_missing_bucket(self):
        """Raises ConfigurationError when S3 bucket is missing."""
        test_env = {
            "AWS_ACCESS_KEY_ID": "test-key",
            "AWS_SECRET_ACCESS_KEY": "test-secret",
        }

        with patch.dict(os.environ, test_env, clear=True):
            config = get_config(reload=True)

            with pytest.raises(ConfigurationError) as exc_info:
                require_aws_config(config)

            assert "S3_BUCKET" in str(exc_info.value)


class TestConfigImmutability:
    """
    Tests that Config objects cannot be modified.

    Why immutability?
    - Prevents bugs from accidental modification
    - Config shouldn't change during app lifecycle
    - Thread-safe by default
    """

    def test_cannot_modify_attributes(self):
        """Config attributes are frozen (immutable)."""
        with patch.dict(os.environ, {}, clear=True):
            config = get_config(reload=True)

            # Attempting to modify should raise an error
            with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
                config.log_level = "DEBUG"

    def test_cannot_add_attributes(self):
        """Cannot add new attributes to Config."""
        with patch.dict(os.environ, {}, clear=True):
            config = get_config(reload=True)

            with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
                config.new_attribute = "value"
