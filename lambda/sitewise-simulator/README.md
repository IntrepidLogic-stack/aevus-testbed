# aevus-sitewise-simulator

Generates synthetic IoT telemetry every minute for the Aevus SCADA platform demo.

- **Trigger:** EventBridge (every 1 minute)
- **Action:** boto3 `iotsitewise.batch_put_asset_property_value` calls with sinusoidal + jitter values
- **Assets:** 3 site IDs × 5 properties each — see `lambda_function.py` ASSETS dict
- **Region:** us-east-1

## Captured: 2026-05-20
