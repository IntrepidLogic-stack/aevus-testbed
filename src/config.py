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
    # Trio JR900 radios — leave blank until each unit has been console-configured
    # with an IP. When empty, the collector is skipped and the simulator covers
    # the asset. When set, a real SNMP collector overrides the sim entry.
    rad_01_ip: str = ""
    rad_02_ip: str = ""
    trio_radio_1_ip: str = "192.168.88.11"
    trio_radio_2_ip: str = "192.168.88.12"
    # SCADAPack 470 found at 172.16.1.200 (NOT the original .88.21 plan —
    # it lives on a different lab subnet). Task #198/#134. The Modbus
    # collector only registers when modbus_enabled=true AND scadapack_ip is
    # set — and it must run on the EDGE Pi (which is on the lab LAN), NOT on
    # EC2 (AWS can't route to a 172.16.x private IP). On EC2 leave
    # modbus_enabled unset/false so the asset stays on the simulator.
    scadapack_ip: str = "172.16.1.200"
    modbus_enabled: bool = False
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

    # ── Read source (edge→cloud convergence, Phase 2) ──
    # sqlite : serve assets from local SQLite (default — current behavior)
    # dynamo : overlay live vitals/state from the DynamoDB latest-state store
    # dual   : serve SQLite but log per-field divergence vs Dynamo (soak/validate)
    read_source: str = "sqlite"
    dynamo_latest_state_table: str = "aevus-latest-state"
    aws_region: str = "us-east-1"

    # ── FastAPI ──
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_reload: bool = True
    cors_origins: str = "https://aevus.intrepidlogic.io"
    deploy_secret: str = ""
    api_key: str = ""  # Set in .env — required for API access
    api_key_header: str = "X-API-Key"

    # ── MQTT — bridge to AWS IoT Core (or local Mosquitto in dev) ──
    mqtt_enabled: bool = False  # off by default until configured
    mqtt_broker_host: str = "localhost"  # IoT Core: <endpoint>-ats.iot.<region>.amazonaws.com
    mqtt_broker_port: int = 1883  # IoT Core MQTT-over-TLS: 8883
    mqtt_site_id: str = "lab"  # used in topic hierarchy
    mqtt_client_id: str = "aevus-edge-lab-01"  # must be unique per device
    mqtt_tls_enabled: bool = False  # true for IoT Core
    mqtt_ca_cert_path: str = ""  # Amazon root CA for IoT Core
    mqtt_client_cert_path: str = ""  # X.509 device cert
    mqtt_client_key_path: str = ""  # X.509 device private key
    mqtt_username: str = ""  # only for local Mosquitto with auth
    mqtt_password: str = ""
    mqtt_qos: int = 1  # 1 = at-least-once (IoT Core max)
    mqtt_keepalive: int = 60
    mqtt_initial_backoff: float = 2.0
    mqtt_max_backoff: float = 60.0
    # Half-open detection (Task #151) — paho's TCP keepalive can succeed
    # while the MQTT session is dead (broker evicted us, NAT timeout,
    # silent close). After this many consecutive publish failures or
    # timeouts, force a reconnect cycle rather than logging hopelessly.
    mqtt_publish_failure_threshold: int = 5
    # Hard upper bound on a single publish call. Longer than the broker's
    # PUBACK round-trip but short enough that a wedged TCP socket can't
    # hang the scheduler. 5s is well above the p99 IoT Core PUBACK.
    mqtt_publish_timeout: float = 5.0

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
    # WARNING-level alerts batch into a digest sent every N seconds (Task #201).
    # Default hourly. CRITICAL alerts still email in real time.
    warning_digest_interval: int = 3600
    notification_sms_to: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    notifications_enabled: bool = False

    # ── SNMP Trap Receiver ──
    snmp_trap_port: int = 1162
    snmp_trap_enabled: bool = True

    # ── Weather + Daylight ──
    site_latitude: float = 29.3905
    site_longitude: float = -95.8375
    weather_poll_interval: int = 900

    # -- Supabase Auth --
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_jwt_secret: str = ""


# Singleton
settings = Settings()
