# Reference Datasets — real recorded industrial data for Aevus

Aevus ingests three honestly-distinct classes of data:

| Class | What | Examples |
|---|---|---|
| **live** | Real telemetry from the lab hardware | Trio JR900 ×2 (SNMP), Cisco Catalyst (SNMP), MikroTik (SNMP), SCADAPack 470 (Modbus) |
| **simulated** | Demo-only, facility-gated synthetic process model | the Killdeer / BlueJay #1 twin `/process` values |
| **reference** | **Real recorded** public lab/testbed datasets, replayed | Morris gas-pipeline Modbus, CWRU bearing vibration |

`reference` exists so the platform also processes **genuine recorded industrial
data** without faking it as field-live.

## ⚠️ Honesty rules (do not break)

1. Reference readings are tagged `source="reference"` — **never** `live` or `simulated`.
2. Reference data is **not a Killdeer twin node** and must **never** be shown as
   Killdeer field-live or as a customer feed. Attribute it to its source dataset.
3. Values come only from `scripts/prep_reference_data.py` run against the **real
   downloads** — nothing here is fabricated.
4. Raw datasets are **not committed** (size + license). Fetch them yourself.

## The datasets

### Morris ICS gas-pipeline (Mississippi State / UAH — T. Morris)
Real lab-scale gas-pipeline ICS testbed: a PLC/RTU holds pipe pressure to a
setpoint, polled over **Modbus**; rows carry pressure (PV), setpoint, pump/
solenoid state, control mode, and a normal/attack label. Closest match to our
SCADAPack-470 Modbus path. *Research-use; cite the source. Verify current hosting.*

### CWRU Bearing Data Center (Case Western Reserve University)
Real motor-rig **vibration** (accelerometer @ 12 kHz) for healthy vs. seeded
inner-race / outer-race / ball faults. We derive an ISO-10816-style **RMS
velocity (mm/s)** per window → drives the compressor vibration point (reg 40017)
with real bearing-fault physics. *Freely available for research; cite the source.*

## Prep + replay

```bash
# 1. download the raw files into reference_data/raw/ (see source sites)
# 2. convert to the normalized replay CSV (real values, no fabrication):
python scripts/prep_reference_data.py morris reference_data/raw/Gas_Pipeline.arff
python scripts/prep_reference_data.py cwru   reference_data/raw/IR007_0.mat --label inner_race
# 3. replay through the platform (tagged source="reference"):
#    ReferenceReplayCollector("REF-CWRU", "reference_data/prepped/cwru_bearing.csv")
```

Replay CSV format (`reference_data/prepped/*.csv`):

```
frame,metric,value,unit,group
0,vibration,1.82,mm/s,reference:cwru
0,vibration_accel,0.061,g,reference:cwru
0,fault,1,state,reference:cwru
```

`reference_data/raw/` and `reference_data/prepped/` are gitignored.
