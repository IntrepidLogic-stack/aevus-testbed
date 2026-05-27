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
    edge_collector_ip: str = "192.168.88.252"
    snmp_community: str = "aevus_ro"
    snmp_version: str = "2c"

    # ── SCADAPack 470 Protocols ──
    modbus_port: int = 502
    modbus_slave_id: int = 1
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
    api_key: str = ""  # Set in .env — required for API access
    api_key_header: str = "X-API-Key"

    # ── Polling Intervals (seconds) ──
    poll_interval_radio: int = 30
    poll_interval_rtu: int = 5
    poll_interval_switch: int = 30
    poll_interval_router: int = 30

    # ── MQTT Publisher (Phase 4 — IoT Core / Mosquitto bridge) ──
    # Local Mosquitto in dev mode; AWS IoT Core with X.509 mutual TLS
    # in production. Per docs/AWS_LANDING_ZONE.md the edge keeps
    # sub-second alarming local — MQTT is the bridge to the cloud
    # fleet view, never on the critical path for local alarms.
    mqtt_enabled: bool = False  # off by default until configured
    mqtt_broker_host: str = "localhost"  # IoT Core: "<endpoint>-ats.iot.<region>.amazonaws.com"
    mqtt_broker_port: int = 1883  # IoT Core MQTT-over-TLS: 8883
    mqtt_site_id: str = "lab"  # used in topic hierarchy
    mqtt_client_id: str = "aevus-edge-lab-01"  # must be unique per Greengrass core
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

    # ── DNP3 Unsolicited Responses (Phase 3 — patent-relevant edge path) ──
    # SCADAPack 470 outstation pushes Class 1/2/3 events to us in
    # milliseconds without being polled. Beats Modbus discrete-input
    # polling for process alarms (high pressure, low battery, comm fault)
    # by 5+ seconds. This is the P-008 patent claim.
    dnp3_unsolicited_enabled: bool = True
    dnp3_reconnect_interval: float = 5.0  # seconds between TCP reconnect attempts
    dnp3_integrity_poll_interval: int = 300  # fallback Class 0 poll cadence (sec)
    dnp3_connect_timeout: float = 5.0
    dnp3_keep_alive_interval: int = 60  # DNP3 link-status keep-alive cadence

    # ── ICMP Layer-3 Probe (Phase 2) ──
    # Sub-second reachability check that runs independently of any
    # application-layer poll. Lets the dashboard distinguish "device
    # dead" from "agent dead" from "path broken".
    icmp_probe_interval: float = 1.0  # seconds between pings per asset
    icmp_timeout: float = 0.8  # per-ping timeout (must be < interval)
    icmp_window_size: int = 10  # rolling window of recent results
    icmp_loss_warn_pct: float = 10.0  # % loss → degraded warning
    icmp_consecutive_down: int = 3  # consecutive timeouts → critical down
    icmp_privileged: bool = False  # False = use unprivileged DGRAM socket
    # (requires net.ipv4.ping_group_range);
    # True = raw socket (needs CAP_NET_RAW)

    # ── Comms-Loss / Staleness Detection ──
    # An asset is flagged OFFLINE after this many consecutive missed poll
    # intervals. Tightened from the legacy "5x" rule so OT operators see
    # comms loss within ~3 poll cycles (15s for RTU @ 5s, 90s for radio @ 30s).
    missed_polls_offline: int = 3
    # Independent sweep loop tick. Even if a poll task hangs or dies, the
    # sweep evaluates staleness for every registered asset on this cadence.
    staleness_sweep_interval: int = 5

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

    # ── IL-009 Safety Interlock ──
    il_009_enforced: bool = True  # NEVER set to False


# Singleton
settings = Settings()
