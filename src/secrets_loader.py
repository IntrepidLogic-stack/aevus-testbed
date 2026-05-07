"""
Aevus Testbed — AWS Secrets Manager Integration
Loads secrets from AWS Secrets Manager at startup, falling back to .env values.
"""

from __future__ import annotations

import json
import os
import structlog

logger = structlog.get_logger()

SECRET_ID = "aevus/prod/credentials"
AWS_REGION = "us-east-1"


def load_secrets() -> dict[str, str]:
    """
    Fetch secrets from AWS Secrets Manager.
    Falls back gracefully if boto3 is missing or not running on AWS.
    Returns a dict of secret key-value pairs.
    """
    try:
        import boto3
        client = boto3.client("secretsmanager", region_name=AWS_REGION)
        resp = client.get_secret_value(SecretId=SECRET_ID)
        secrets = json.loads(resp["SecretString"])
        logger.info("secrets_loaded", source="aws_secrets_manager", keys=list(secrets.keys()))
        return secrets
    except ImportError:
        logger.warning("secrets_fallback", reason="boto3 not installed")
        return {}
    except Exception as e:
        logger.warning("secrets_fallback", reason=str(e))
        return {}


def inject_secrets() -> None:
    """
    Load secrets from AWS and inject into environment variables
    if not already set. This allows .env overrides for local dev.
    """
    secrets = load_secrets()

    mapping = {
        "api_key": "API_KEY",
        "influxdb_token": "INFLUX_TOKEN",
        "dashboard_user": "DASHBOARD_USER",
        "dashboard_pass": "DASHBOARD_PASS",
    }

    for secret_key, env_var in mapping.items():
        if secret_key in secrets and not os.environ.get(env_var):
            os.environ[env_var] = secrets[secret_key]
            logger.debug("secret_injected", env_var=env_var)
