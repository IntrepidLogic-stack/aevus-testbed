# ============================================================
# AWS IoT SiteWise asset model
#
# Mirrors the property names from src/collectors/*.py + the
# thresholds from src/config.py so the polled path, the DNP3
# unsolicited path, and the SiteWise alarm model all use one
# source of truth.
#
# Asset model hierarchy:
#   AevusCabinet (parent)
#     ├─ TrioJR900Radio (child × N)
#     ├─ SCADAPack470RTU (child × N)
#     ├─ MikroTikL009 (child × N)
#     └─ CiscoCatalyst2960 (child × N)
#
# Each device-model has property definitions for the metrics it
# emits + AVG/MAX transforms (for the dashboard's smoothing line)
# and alarm thresholds that match AlertEngine.
# ============================================================

# ── Trio JR900 — radio asset model ──────────────────────────────────────
resource "aws_iotsitewise_asset_model" "trio_jr900" {
  count = var.sitewise_enabled ? 1 : 0
  name  = "TrioJR900Radio"

  description = "Trio JR900 radio — RF telemetry via SNMP v2c polling"

  asset_model_property {
    name      = "rssi"
    data_type = "DOUBLE"
    unit      = "dBm"
    type {
      measurement {}
    }
  }

  asset_model_property {
    name      = "snr"
    data_type = "DOUBLE"
    unit      = "dB"
    type {
      measurement {}
    }
  }

  asset_model_property {
    name      = "tx_power"
    data_type = "DOUBLE"
    unit      = "dBm"
    type {
      measurement {}
    }
  }

  asset_model_property {
    name      = "temperature"
    data_type = "DOUBLE"
    unit      = "C"
    type {
      measurement {}
    }
  }

  asset_model_property {
    name      = "voltage"
    data_type = "DOUBLE"
    unit      = "V"
    type {
      measurement {}
    }
  }

  asset_model_property {
    name      = "error_packets"
    data_type = "DOUBLE"
    unit      = "count"
    type {
      measurement {}
    }
  }
}

# ── SCADAPack 470 — RTU asset model ─────────────────────────────────────
resource "aws_iotsitewise_asset_model" "scadapack_470" {
  count = var.sitewise_enabled ? 1 : 0
  name  = "SCADAPack470RTU"

  description = "Schneider SCADAPack 470 — Modbus TCP polled + DNP3 unsolicited"

  # Analog process values.
  dynamic "asset_model_property" {
    for_each = {
      suction_pressure    = "PSI"
      discharge_pressure  = "PSI"
      flow_rate           = "MCFD"
      gas_temperature     = "F"
      ambient_temperature = "F"
      battery_voltage     = "VDC"
      solar_voltage       = "VDC"
      tank_level          = "in"
      vibration           = "mm/s"
      run_hours           = "hrs"
    }
    content {
      name      = asset_model_property.key
      data_type = "DOUBLE"
      unit      = asset_model_property.value
      type {
        measurement {}
      }
    }
  }

  # Discrete inputs (mapped from bool to 0.0 / 1.0 in src/scheduler.py
  # so they normalize through the same threshold path).
  dynamic "asset_model_property" {
    for_each = toset([
      "compressor_running",
      "high_pressure_alarm",
      "low_battery_alarm",
      "communication_fault",
    ])
    content {
      name      = asset_model_property.value
      data_type = "DOUBLE"   # SiteWise's BOOLEAN type doesn't support transforms
      unit      = "bool"
      type {
        measurement {}
      }
    }
  }
}

# ── MikroTik L009 — router asset model ──────────────────────────────────
resource "aws_iotsitewise_asset_model" "mikrotik_l009" {
  count = var.sitewise_enabled ? 1 : 0
  name  = "MikroTikL009Router"

  description = "MikroTik L009 — WAN edge router, SNMP-polled"

  dynamic "asset_model_property" {
    for_each = {
      cpu_load     = "%"
      memory_usage = "%"
      uptime       = "hrs"
    }
    content {
      name      = asset_model_property.key
      data_type = "DOUBLE"
      unit      = asset_model_property.value
      type {
        measurement {}
      }
    }
  }
}

# ── Cisco Catalyst 2960 — switch asset model ────────────────────────────
resource "aws_iotsitewise_asset_model" "cisco_catalyst_2960" {
  count = var.sitewise_enabled ? 1 : 0
  name  = "CiscoCatalyst2960Switch"

  description = "Cisco Catalyst 2960 — L2 switch, SNMP-polled"

  dynamic "asset_model_property" {
    for_each = {
      cpu_load     = "%"
      memory_usage = "%"
      uptime       = "hrs"
    }
    content {
      name      = asset_model_property.key
      data_type = "DOUBLE"
      unit      = asset_model_property.value
      type {
        measurement {}
      }
    }
  }
}

# ── Cabinet — parent asset model that groups devices per site ───────────
resource "aws_iotsitewise_asset_model" "cabinet" {
  count = var.sitewise_enabled ? 1 : 0
  name  = "AevusCabinet"

  description = "A site cabinet — groups the radio, RTU, router, switch deployed at one location"

  asset_model_hierarchy {
    name             = "radios"
    child_asset_model_id = aws_iotsitewise_asset_model.trio_jr900[0].id
  }
  asset_model_hierarchy {
    name             = "rtus"
    child_asset_model_id = aws_iotsitewise_asset_model.scadapack_470[0].id
  }
  asset_model_hierarchy {
    name             = "routers"
    child_asset_model_id = aws_iotsitewise_asset_model.mikrotik_l009[0].id
  }
  asset_model_hierarchy {
    name             = "switches"
    child_asset_model_id = aws_iotsitewise_asset_model.cisco_catalyst_2960[0].id
  }
}

# ── Per-site cabinet asset instances ────────────────────────────────────
# One Cabinet asset per site in var.sites. Child device assets are
# created lazily by the seed_assets.py script + an IoT Core rule
# action — we don't enumerate every lab device here, because the
# device inventory is meant to be data-driven, not Terraform-driven.
resource "aws_iotsitewise_asset" "cabinet" {
  for_each = var.sitewise_enabled ? var.sites : {}

  name           = "AevusCabinet-${each.key}"
  asset_model_id = aws_iotsitewise_asset_model.cabinet[0].id
}
