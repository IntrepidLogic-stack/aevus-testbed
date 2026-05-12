"""
Aevus Testbed — Configuration
Loads all settings from .env via pydantic-settings.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from .env file."""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # ── Lab Network ──
    lab_subnet: str = "192.168.88.0/24"
    mikrotik_ip: str = "192.168.88.1"
    catalyst_ip: str = "192.168.88.2"
    uplogix_ip: str = "192.168.88.5"
    trio_radio_1_ip: str = "192.168.88.11"
    trio_radio_2_ip: str = "192.168.88.12"
    scadapack_ip: str = "192.168.88.21"
    edge_collector_ip: str = "192.168.88.254"
    snmp_community: str = "aevus_ro"
    snmp_version: str = "2c"

    # ── SCADAPack 470 Protocols ──
    modbus_port: int = 502
    modbus_slave_id: int = 1

    # DNP3
    dnp3_host: str = "127.0.0.1"
    dnp3_port: int = 20000
    dnp3_master_addr: int = 1
    dnp3_outstation_addr: int = 10
    poll_interval_dnp3: int = 10
    dnp3_port: int = 20000
    dnp3_outstation_addr: int = 10
    dnp3_master_addr: int = 1

    # ── InfluxDB ──
    influx_url: str = "http://localhost:8086"
    influx_token: str = "your-influx-token-here"
    influx_org: str = "intrepid-logic"
    influx_bucket: str = "aevus_telemetry"
    influx_retention: str = "90d"

    # ── SQLite ──
    sqlite_path: str = "./data/aevus.db"

    # ── FastAPI ──
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_reload: bool = True
    cors_origins: str = "https://aevus.intrepidlogic.io"
    deploy_secret: str = ""
    api_key: str = ""  # Set in .env — required for API access
    api_key_header: str = "X-API-Key"

    # ── Polling Intervals (seconds) ──
    poll_interval_radio: int = 30
    poll_interval_rtu: int = 5
    poll_interval_switch: int = 30
    poll_interval_router: int = 30

    # ── Alert Thresholds — Radio (Trio JR900) ──
    threshold_health_warn: int = 80
    threshold_health_crit: int = 50
    threshold_rssi_warn: float = -80.0
    threshold_rssi_crit: float = -90.0
    threshold_snr_warn: float = 15.0
    threshold_snr_crit: float = 10.0
    threshold_radio_temp_warn: float = 60.0
    threshold_radio_temp_crit: float = 75.0
    threshold_error_rate_warn: float = 1.0
    threshold_error_rate_crit: float = 5.0

    # ── Alert Thresholds — RTU (SCADAPack 470) ──
    threshold_battery_warn: float = 12.0
    threshold_battery_crit: float = 11.5
    threshold_suction_warn: float = 800.0
    threshold_suction_crit: float = 900.0
    threshold_discharge_warn: float = 1200.0
    threshold_discharge_crit: float = 1400.0
    threshold_vibration_warn: float = 4.5
    threshold_vibration_crit: float = 7.1

    # ── Alert Thresholds — Network ──
    threshold_cpu_warn: float = 70.0
    threshold_cpu_crit: float = 90.0
    threshold_if_errors_warn: float = 100.0
    threshold_if_errors_crit: float = 1000.0

    # ── IL-9000 Safety Interlock ──
    il_9000_enforced: bool = True  # NEVER set to False

    # ── Notification Engine ──
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "aevus@intrepidlogic.io"
    notification_email_to: str = ""
    notification_sms_to: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    notifications_enabled: bool = False

    # ── Weather + Daylight ──
    site_latitude: float = 29.3905
    site_longitude: float = -95.8375
    weather_poll_interval: int = 900


# Singleton
settings = Settings()
