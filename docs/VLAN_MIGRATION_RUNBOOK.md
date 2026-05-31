# VLAN Migration Runbook — Lab Network → Segmented 10.50.x.0/24

**Status:** Planned (Task #134 unblocker)
**Target architecture:** per CLAUDE.md — three VLANs on MikroTik L009 + Catalyst 2960
**Risk:** medium — can lock yourself out if MikroTik changes happen in wrong order
**Backout:** documented in §8 — keeps old `192.168.88.0/24` flat path warm until verification

---

## 1. Why this migration

Today's lab runs flat `192.168.88.0/24`: router, switch, edge Pi, radios,
SCADAPack-simulator host, your laptop, and SHOP-01 all share one broadcast
domain. The SCADAPack 470 itself sits on a separate physical OT network at
`172.16.1.200` that nothing on the lab LAN can reach — blocking Task #134.

Target topology (per `CLAUDE.md`):

| VLAN | Subnet | Purpose | Members |
|---|---|---|---|
| 10 | `10.50.10.0/24` | Management | MikroTik mgmt, Catalyst mgmt, Uplogix |
| 20 | `10.50.20.0/24` | OT | Radios (RAD-01, RAD-02), SCADAPack (RTU-01), any sensors |
| 30 | `10.50.30.0/24` | Aevus | Edge Pi (EDGE-01), workstation (SHOP-01), laptops |

MikroTik does inter-VLAN routing. Catalyst is L2-only — it carries the
VLANs on access ports + a trunk back to MikroTik.

Resulting IEC 62443 segmentation:
- OT broadcast traffic doesn't leak to the Aevus VLAN
- A compromised laptop on VLAN 30 can only reach VLAN 20 through MikroTik
  ACLs you explicitly write
- Radios can't directly initiate connections to SHOP-01

---

## 2. Pre-flight (NO CHANGES yet)

Before any config change:

```bash
# 1. From your Mac: confirm Tailscale to Pi works
ssh admin@aevus-edge 'systemctl is-active aevus'
# Expected: active

# 2. RustDesk to SHOP-01 — verify you can console-into the Catalyst
#    from there via either web UI (http://catalyst-ip) or serial
#    (the blue cable to the Catalyst's console port should be reachable
#    via a USB-serial dongle on SHOP-01)

# 3. Back up MikroTik config
ssh admin@192.168.88.1 '/export file=premigration-2026-05-30'
ssh admin@192.168.88.1 '/file print where name~"premigration"'
# Then download via scp or WinBox: premigration-2026-05-30.rsc

# 4. Back up Catalyst config (via SHOP-01 console session)
#    Catalyst CLI:
en
copy running-config startup-config
copy startup-config flash:premigration-2026-05-30.cfg
show flash: | include premigration
```

Both backups exist on-device + downloaded locally. If anything breaks,
you can `/import` (MikroTik) or `copy flash:premigration-2026-05-30.cfg
running-config` (Catalyst) to restore.

---

## 3. Order of operations

The migration runs in 5 phases, each verifiable before the next. **Do NOT
skip verification** — each phase has a known-good rollback target.

| Phase | What changes | Risk | Rollback |
|---|---|---|---|
| A. Catalyst VLAN scaffolding | VLANs created, ports assigned, but old flat VLAN 1 still works | Low | Catalyst rollback |
| B. MikroTik subinterfaces | New VLAN subnets exist on MikroTik, but old `192.168.88.0/24` still works | Low | MikroTik rollback |
| C. Trunk port between MikroTik and Catalyst | Both speak VLAN tags; flat traffic still flows | Low | MikroTik+Catalyst rollback |
| D. Per-device IP migration (one at a time) | Each device moves to its VLAN | Medium per device | Re-DHCP back to .88.0/24 |
| E. Decommission old flat path | Remove VLAN 1 bridge from MikroTik | High | Both rollbacks |

---

## 4. Phase A — Catalyst VLAN scaffolding (via RustDesk → SHOP-01 → console)

```
en
conf t
vlan 10
 name MGMT
vlan 20
 name OT
vlan 30
 name AEVUS
exit

! Define which physical ports go to which VLAN
! (Use `show cdp neighbors` first to identify which port has what)
! Suggested assignments — adjust per your physical layout:

interface range FastEthernet0/1 - 4
 description Management ports (MikroTik, future Uplogix)
 switchport mode access
 switchport access vlan 10
 spanning-tree portfast

interface range FastEthernet0/5 - 12
 description OT — radios, RTU
 switchport mode access
 switchport access vlan 20
 spanning-tree portfast

interface range FastEthernet0/13 - 24
 description Aevus — edge Pi, workstation
 switchport mode access
 switchport access vlan 30
 spanning-tree portfast

! Trunk port to MikroTik (which physical port is your blue cable on?)
interface GigabitEthernet0/1
 description Trunk to MikroTik
 switchport trunk encapsulation dot1q
 switchport mode trunk
 switchport trunk allowed vlan 10,20,30
 ! Keep native vlan 1 for now — Phase E retires this

end
write memory
```

**Verify Phase A:**
- `show vlan brief` — VLANs 10/20/30 listed, ports assigned
- `show interfaces trunk` — trunk port shows VLANs 10,20,30 allowed
- Existing lab LAN connectivity still works (Pi still reachable from MikroTik)

If anything's broken: `copy flash:premigration-2026-05-30.cfg running-config`

---

## 5. Phase B — MikroTik subinterfaces (via WinBox or SSH)

```routeros
# Create VLAN sub-interfaces on the trunk port (assume ether2 is the
# physical port plugged into the Catalyst's Gi0/1 trunk)
/interface vlan add interface=ether2 name=vlan10-mgmt vlan-id=10
/interface vlan add interface=ether2 name=vlan20-ot vlan-id=20
/interface vlan add interface=ether2 name=vlan30-aevus vlan-id=30

# Assign IP addresses (MikroTik is the gateway for each VLAN)
/ip address add address=10.50.10.1/24 interface=vlan10-mgmt comment="MGMT VLAN gateway"
/ip address add address=10.50.20.1/24 interface=vlan20-ot comment="OT VLAN gateway"
/ip address add address=10.50.30.1/24 interface=vlan30-aevus comment="Aevus VLAN gateway"

# DHCP pools per VLAN (so devices can grab an IP on the new networks)
/ip pool add name=pool-aevus ranges=10.50.30.100-10.50.30.200
/ip pool add name=pool-mgmt  ranges=10.50.10.100-10.50.10.200
/ip pool add name=pool-ot    ranges=10.50.20.100-10.50.20.200

/ip dhcp-server add interface=vlan10-mgmt address-pool=pool-mgmt name=dhcp-mgmt disabled=no
/ip dhcp-server add interface=vlan20-ot   address-pool=pool-ot   name=dhcp-ot disabled=no
/ip dhcp-server add interface=vlan30-aevus address-pool=pool-aevus name=dhcp-aevus disabled=no

/ip dhcp-server network add address=10.50.10.0/24 gateway=10.50.10.1 dns-server=10.50.10.1
/ip dhcp-server network add address=10.50.20.0/24 gateway=10.50.20.1 dns-server=10.50.20.1
/ip dhcp-server network add address=10.50.30.0/24 gateway=10.50.30.1 dns-server=10.50.30.1

# Firewall — default-deny between VLANs, with explicit allows for
# the Aevus VLAN to reach OT for polling. ISA-101/IEC 62443 alignment.
/ip firewall filter add chain=forward action=accept connection-state=established,related
/ip firewall filter add chain=forward action=drop  in-interface=vlan20-ot out-interface=vlan30-aevus comment="OT cannot initiate to Aevus"
/ip firewall filter add chain=forward action=accept in-interface=vlan30-aevus out-interface=vlan20-ot \
    protocol=tcp dst-port=502,20000 comment="Aevus->OT: Modbus + DNP3 only"
/ip firewall filter add chain=forward action=accept in-interface=vlan30-aevus out-interface=vlan20-ot \
    protocol=udp dst-port=161,162 comment="Aevus->OT: SNMP poll + traps"
/ip firewall filter add chain=forward action=accept in-interface=vlan30-aevus out-interface=vlan20-ot \
    protocol=icmp comment="Aevus->OT: ICMP for reachability probe"
/ip firewall filter add chain=forward action=drop  in-interface=vlan20-ot out-interface=any comment="OT default-deny outbound"
```

**Verify Phase B:**
- `/ip address print` — three new subnets listed
- `/ip dhcp-server print` — three new pools active
- `/ip firewall filter print` — new rules in place, in correct order
- `ping 10.50.10.1` from MikroTik itself — works (it's the gateway)
- Existing `192.168.88.0/24` still works for all devices

Rollback: `/import premigration-2026-05-30.rsc`

---

## 6. Phase C — Trunk port + verification

Trunk is already configured in Phase A (Catalyst side) and Phase B (MikroTik
side — `ether2` carries the VLANs because the sub-interfaces are on it).

**Verify Phase C** by tagging a test packet from each side:
- From Catalyst: `show interfaces trunk` → STP forwarding state on Gi0/1 for VLANs 10/20/30
- From MikroTik: `/interface vlan print stats` → counters incrementing on each vlan-N interface

Then physically plug a laptop into a port assigned to VLAN 30 on the
Catalyst (e.g. Fa0/13). The laptop should DHCP a `10.50.30.x` address.
**If the laptop gets `192.168.88.x` instead, the port isn't actually in
VLAN 30 — re-check Phase A** before proceeding.

---

## 7. Phase D — Per-device migration (one at a time, with verification)

Migrate in this order so you keep your remote-access path warm:

### D.1 — SHOP-01 (you're using this for console access) — **DO LAST in this list, but verify VLAN 30 with a laptop first**

### D.2 — Edge Pi (`aevus-edge`, currently `192.168.88.254`)

Risk: if this breaks, you lose SSH-via-Tailscale but Tailscale itself
shouldn't care about subnet changes. Still — do this when you can be
physically at the Pi or have RustDesk to SHOP-01 ready.

```bash
# On the Pi via Tailscale:
sudo nano /etc/dhcpcd.conf
# Change static IP block to:
#   interface eth0
#   static ip_address=10.50.30.254/24
#   static routers=10.50.30.1
#   static domain_name_servers=10.50.30.1
sudo systemctl restart dhcpcd
# OR if using DHCP: just `sudo dhclient -r eth0 && sudo dhclient eth0`
```

Then move the Pi's physical cable from the current Catalyst port to one
on VLAN 30 (Fa0/13–24).

Verify: `ping 10.50.30.1` (gateway), `ping 10.50.20.11` (RAD-01 after D.3),
Tailscale still works, MQTT-to-IoT still flowing.

### D.3 — Radios (RAD-01, RAD-02) — currently `192.168.88.11`, `.12`

Via radio web UI (browser to `http://192.168.88.11` while still on flat):
- Change IP to `10.50.20.11` (RAD-01) / `10.50.20.12` (RAD-02)
- Change gateway to `10.50.20.1`
- Save + Activate Configuration

Then physically move the radio cables to a port on VLAN 20 (Fa0/5–12).

Verify from Pi (now on 10.50.30.254):
```bash
ping 10.50.20.11
snmpget -v2c -c aevus_ro 10.50.20.11 1.3.6.1.4.1.5727.1.1.1.0
```

### D.4 — SCADAPack 470 — currently `172.16.1.200` → **`10.50.20.21`**

This is the whole point of #134. Console into SCADAPack via Schneider
DTM/ClearSCADA/whatever you used originally. Set:
- IP: `10.50.20.21`
- Netmask: `255.255.255.0`
- Gateway: `10.50.20.1`
- Modbus TCP :502 still listening
- DNP3 :20000 still listening

Plug into VLAN 20 (Fa0/5–12).

Update `src/config.py` on the Pi:
```python
scadapack_ip: str = "10.50.20.21"  # was 192.168.88.21
```
(Commit + push + pull on Pi + restart.)

Verify:
```bash
ssh admin@aevus-edge 'nc -zv 10.50.20.21 502 && nc -zv 10.50.20.21 20000'
```

### D.5 — SHOP-01

Static IP or DHCP, your choice. If DHCP, just unplug + replug into a
VLAN 30 port and Windows will re-DHCP onto `10.50.30.x`.

### D.6 — MikroTik mgmt + Catalyst mgmt → VLAN 10

```routeros
# MikroTik — add a mgmt IP on VLAN 10
/ip address add address=10.50.10.1/24 interface=vlan10-mgmt
# (Already done in Phase B — this is just the verification step)
```

Catalyst (`conf t`):
```
interface vlan 10
 ip address 10.50.10.2 255.255.255.0
 no shutdown
ip default-gateway 10.50.10.1
end
write memory
```

---

## 8. Phase E — Decommission old flat path

Only after **48 hours of stable operation on the VLANs** with no
unexpected pings to `192.168.88.x`:

```routeros
# MikroTik — remove the old bridge / DHCP / IP
/ip dhcp-server disable defconf
/ip address remove [find network=192.168.88.0]
# Verify nothing's relying on 192.168.88.x first:
# /ip arp print where interface=bridgeLocal
```

Catalyst — leave VLAN 1 in place (default) but unassign all ports from it.

Update `dashboard/Aevus_Console.html` + any docs that still mention
`192.168.88.x` to reference the new subnets.

---

## 9. Code/config changes needed

After Phase D completes, these need updating in the repo:

| File | Change |
|---|---|
| `src/config.py` | `scadapack_ip`, `mikrotik_ip`, `catalyst_ip`, radio IPs |
| `src/main.py` `LAB_ASSETS` | If any IPs are hardcoded (check first) |
| `src/register_writer.py` | `HOST = "10.50.20.21"` (was 172.16.1.200) |
| `docs/CLAUDE.md` | Update topology diagram |
| `docs/SITE_VISIT_RUNBOOK.md` | Note the new subnet layout |
| `dashboard/Aevus_Console.html` | Any hardcoded IPs in display strings |

I (Claude) will ship these as a follow-up PR after you confirm Phase D
complete.

---

## 10. Rollback (if anything goes wrong)

**MikroTik:** `/import premigration-2026-05-30.rsc` from WinBox file
manager or console.

**Catalyst:** From console:
```
en
copy flash:premigration-2026-05-30.cfg running-config
write memory
```

**SCADAPack:** Set IP back to `172.16.1.200` via DTM.

**Radios:** Web UI → IP back to `192.168.88.11` / `.12` → Activate.

**Pi:** `sudo nano /etc/dhcpcd.conf` → revert to `192.168.88.254` →
restart dhcpcd.

If you can't even reach the MikroTik to roll back: physical access required.
The MikroTik has a "Reset" button that, held during boot, reverts to
factory defaults. Then re-import the backup `.rsc` file.

---

## 11. Estimated time

| Phase | Time |
|---|---|
| Pre-flight + backups | 15 min |
| A. Catalyst VLAN scaffolding | 20 min |
| B. MikroTik subinterfaces + DHCP + firewall | 30 min |
| C. Trunk verification + test laptop | 15 min |
| D. Per-device migration (5 devices × ~10 min each) | 50 min |
| E. Decommission (after 48h soak) | 15 min |
| **Total active work** | **~2.5 hours, plus 48h soak before Phase E** |

Suggest doing Phases A–D in a single Saturday morning window. SHOP-01 +
RustDesk gives you remote console access to the Catalyst, so a physical
visit isn't strictly required — but be available at the lab in case the
trunk port needs a re-seat.

---

## 12. Open questions to confirm before you start

1. **Which Catalyst port is the blue cable from SHOP-01 plugged into?**
   That port becomes a VLAN 30 access port.
2. **Which Catalyst port is the cable to the MikroTik plugged into?**
   That port becomes the dot1q trunk.
3. **How many SCADAPack devices total?** Today the registry has just
   RTU-01 — confirm there isn't an RTU-02 lurking on the OT network
   that needs migrating too.
4. **What's the password for the Catalyst's `en` mode?** Need it for
   Phase A. If you don't remember, you'll need the password-recovery
   procedure (rommon boot + `confreg 0x2142`) which requires physical
   console access.
