"""
Configuration Management

Centralized configuration loading from environment variables following
the 12-factor app methodology.

Key Design Decisions:
---------------------
1. All config from environment variables (never hardcode credentials)
2. Fail fast on missing required config (discover at startup, not runtime)
3. Type conversion happens here (env vars are always strings)
4. Immutable config object (prevents accidental modification)
5. Validation helpers for optional services (Snowflake, AWS)

Usage:
------
    from src.utils.config import get_config

    config = get_config()
    print(config.snowflake_account)  # Type-safe, validated access
    print(config.log_level)
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    """
    Immutable configuration object.

    Using a frozen dataclass provides:
    - Type hints for IDE autocompletion
    - Immutability (can't accidentally modify config at runtime)
    - Clear documentation of all configuration options
    - Automatic __init__, __repr__, __eq__ methods
    """

    # Application settings
    log_level: str
    data_dir: Path
    environment: str

    # Snowflake (optional for local development)
    snowflake_account: Optional[str]
    snowflake_user: Optional[str]
    snowflake_password: Optional[str]
    snowflake_warehouse: Optional[str]
    snowflake_database: Optional[str]
    snowflake_schema: Optional[str]
    snowflake_role: Optional[str]

    # AWS (optional for local development)
    aws_access_key_id: Optional[str]
    aws_secret_access_key: Optional[str]
    aws_region: str
    s3_bucket: Optional[str]
    s3_prefix: str

    # OCR
    tesseract_cmd: Optional[str]
    tesseract_lang: str

    # Data Quality
    ge_failure_threshold: float
    ge_root_dir: Path

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment.lower() == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.environment.lower() == "development"

    @property
    def raw_data_dir(self) -> Path:
        """Path to raw data directory."""
        return self.data_dir / "raw"

    @property
    def processed_data_dir(self) -> Path:
        """Path to processed data directory."""
        return self.data_dir / "processed"

    @property
    def staging_data_dir(self) -> Path:
        """Path to staging data directory."""
        return self.data_dir / "staging"

    @property
    def quarantine_data_dir(self) -> Path:
        """Path to quarantine directory for failed records."""
        return self.data_dir / "quarantine"


class ConfigurationError(Exception):
    """
    Raised when configuration is invalid or missing.

    This is a custom exception to distinguish configuration errors
    from other types of errors (ValueError, KeyError, etc.).
    """

    pass


def _get_required(key: str) -> str:
    """
    Get a required environment variable.

    Raises ConfigurationError with clear message if missing.
    This fails at startup, not when you first use the value.

    Why this matters: Better to fail during app initialization than
    halfway through processing when you try to connect to Snowflake.
    """
    value = os.environ.get(key)
    if value is None:
        raise ConfigurationError(
            f"Required environment variable '{key}' is not set. "
            f"Check your .env file or environment configuration."
        )
    return value


def _get_optional(key: str, default: Optional[str] = None) -> Optional[str]:
    """
    Get an optional environment variable with default.

    Returns the value if set, otherwise returns the default.
    """
    return os.environ.get(key, default)


def _get_float(key: str, default: float) -> float:
    """
    Parse float from environment variable.

    Environment variables are always strings, so we need explicit
    type conversion with proper error handling.
    """
    value = os.environ.get(key)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        raise ConfigurationError(
            f"Environment variable '{key}' has invalid float value: '{value}'. "
            f"Expected a number."
        )


# Module-level cache for config singleton
# This ensures we only parse environment variables once
_config: Optional[Config] = None


def get_config(reload: bool = False) -> Config:
    """
    Load and return configuration.

    Configuration is loaded once and cached (singleton pattern).
    Use reload=True to force re-reading from environment.

    Why singleton?
    - Performance: Don't re-parse env vars on every function call
    - Consistency: Same config throughout application lifecycle
    - Testing: reload=True lets tests modify config between test cases

    Args:
        reload: Force reload from environment variables

    Returns:
        Validated Config object

    Raises:
        ConfigurationError: If required config is missing or invalid

    Example:
        config = get_config()
        print(config.log_level)  # "INFO"
        print(config.raw_data_dir)  # Path object
    """
    global _config

    if _config is not None and not reload:
        return _config

    # Load .env file if it exists (no error if missing)
    # In production, env vars typically come from the deployment platform
    # (Kubernetes secrets, AWS Parameter Store, etc.)
    env_path = Path(__file__).parent.parent.parent / ".env"
    load_dotenv(env_path)

    # Build config with validation and type conversion
    _config = Config(
        # Application settings with sensible defaults for local dev
        log_level=_get_optional("LOG_LEVEL", "INFO"),
        data_dir=Path(_get_optional("DATA_DIR", "./data")),
        environment=_get_optional("ENVIRONMENT", "development"),
        # Snowflake (all optional - not needed for local development)
        snowflake_account=_get_optional("SNOWFLAKE_ACCOUNT"),
        snowflake_user=_get_optional("SNOWFLAKE_USER"),
        snowflake_password=_get_optional("SNOWFLAKE_PASSWORD"),
        snowflake_warehouse=_get_optional("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
        snowflake_database=_get_optional("SNOWFLAKE_DATABASE"),
        snowflake_schema=_get_optional("SNOWFLAKE_SCHEMA", "RAW"),
        snowflake_role=_get_optional("SNOWFLAKE_ROLE"),
        # AWS (optional - not needed for local development)
        aws_access_key_id=_get_optional("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=_get_optional("AWS_SECRET_ACCESS_KEY"),
        aws_region=_get_optional("AWS_REGION", "us-west-2"),
        s3_bucket=_get_optional("S3_BUCKET"),
        s3_prefix=_get_optional("S3_PREFIX", "retail-pipeline"),
        # OCR
        tesseract_cmd=_get_optional("TESSERACT_CMD"),
        tesseract_lang=_get_optional("TESSERACT_LANG", "eng"),
        # Data Quality
        ge_failure_threshold=_get_float("GE_FAILURE_THRESHOLD", 0.95),
        ge_root_dir=Path(_get_optional("GE_ROOT_DIR", "./great_expectations")),
    )

    return _config


def require_snowflake_config(config: Config) -> None:
    """
    Validate that Snowflake configuration is complete.

    Call this at the start of any code that needs Snowflake access.
    Fails fast with a clear message if config is incomplete.

    Why this pattern?
    - Explicit dependencies: Code declares what it needs
    - Clear error messages: User knows exactly what's missing
    - Optional services: Snowflake isn't required for local dev

    Args:
        config: Config object to validate

    Raises:
        ConfigurationError: If Snowflake config is incomplete

    Example:
        config = get_config()
        require_snowflake_config(config)  # Fails if SF not configured
        # If we get here, safe to use Snowflake
        conn = snowflake.connector.connect(...)
    """
    missing = []
    if not config.snowflake_account:
        missing.append("SNOWFLAKE_ACCOUNT")
    if not config.snowflake_user:
        missing.append("SNOWFLAKE_USER")
    if not config.snowflake_password:
        missing.append("SNOWFLAKE_PASSWORD")
    if not config.snowflake_database:
        missing.append("SNOWFLAKE_DATABASE")

    if missing:
        raise ConfigurationError(
            f"Snowflake configuration incomplete. Missing: {', '.join(missing)}. "
            f"Set these in your .env file or environment."
        )


def require_aws_config(config: Config) -> None:
    """
    Validate that AWS configuration is complete.

    Call this at the start of any code that needs S3 access.

    Args:
        config: Config object to validate

    Raises:
        ConfigurationError: If AWS config is incomplete
    """
    missing = []
    if not config.aws_access_key_id:
        missing.append("AWS_ACCESS_KEY_ID")
    if not config.aws_secret_access_key:
        missing.append("AWS_SECRET_ACCESS_KEY")
    if not config.s3_bucket:
        missing.append("S3_BUCKET")

    if missing:
        raise ConfigurationError(
            f"AWS configuration incomplete. Missing: {', '.join(missing)}. "
            f"Set these in your .env file or environment."
        )
