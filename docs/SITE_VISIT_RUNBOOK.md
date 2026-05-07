# Aevus Lab Testbed -- Site Visit Runbook

**Date prepared:** 2026-05-06
**Location:** Lab cabinet, Katy TX
**Estimated time:** 2-3 hours
**Prerequisites:** USB-to-serial adapter (DB9), USB-to-RJ45 Cisco console cable (already connected to SHOP-01 COM6), laptop or SHOP-01 with PuTTY, small Phillips screwdriver for SD card

---

## Current Lab State (verified remotely 2026-05-06)

| Device | Status | Notes |
|---|---|---|
| MikroTik L009 | ONLINE | Fully configured, 192.168.88.1 |
| SHOP-01 (Windows PC) | ONLINE | 192.168.88.253, RustDesk accessible |
| Raspberry Pi | ONLINE | 192.168.88.254, ping OK, SSH disabled |
| Cisco Catalyst 2960 | ONLINE | Console responds as `router_a>`, enable password UNKNOWN |
| Trio JR900 #1 | LINK UP | MAC 00:1F:EB:00:75:6F on MikroTik ether4, no IP |
| Trio JR900 #2 | NO LINK | Not powered on or not connected |
| SCADAPack 470 | NO RESPONSE | Was on 192.168.1.201, likely powered off |
| Uplogix 5000 | UNKNOWN | No visibility |

---

## PHYSICAL CABLING DIAGRAM

```
Internet (Spectrum cable modem)
    |
    v
[MikroTik L009 -- 192.168.88.1]
    |
    |-- ether1 = WAN (DHCP from cable modem) -- DO NOT TOUCH
    |
    |-- ether3 --> SHOP-01 (Windows PC) -- EXISTING, LEAVE IN PLACE
    |
    |-- ether4 --> Trio JR900 #1 (RAD-01) -- EXISTING, LEAVE IN PLACE
    |
    |-- ether5 --> Cisco Catalyst 2960 port Gi0/1 (uplink) -- EXISTING, LEAVE IN PLACE
    |
    |-- ether6 --> (available)
    |-- ether7 --> (available)
    |-- ether8 --> (available)


[Cisco Catalyst 2960 -- WS-C2960-24TC-L]
    |
    |-- Gi0/1 (uplink) <-- from MikroTik ether5 -- EXISTING
    |
    |-- Fa0/1 --> Trio JR900 #2 (RAD-02) -- PLUG IN (Ethernet cable to radio)
    |
    |-- Fa0/2 --> SCADAPack 470 (RTU-01) -- PLUG IN (Ethernet cable to RTU)
    |
    |-- Fa0/3 --> Uplogix 5000 -- PLUG IN (Ethernet cable to Uplogix mgmt port)
    |
    |-- Fa0/4 --> Raspberry Pi -- VERIFY (Pi is currently getting DHCP,
    |                              may already be plugged in here or via MikroTik)
    |
    |-- Fa0/5-24 --> available
    |
    |-- Gi0/2 --> available (second uplink)
    |
    |-- CONSOLE (RJ45) <-- USB console cable to SHOP-01 COM6 -- EXISTING


[Uplogix 5000]
    |
    |-- MGMT (Ethernet) <-- from Catalyst Fa0/3
    |
    |-- Serial Port 1 --> Catalyst 2960 console (RJ45-to-DB9)
    |         (This lets Uplogix manage the switch remotely in the future)
    |
    |-- Serial Port 2 --> (available for future SCADAPack console)
```

### Cable Shopping List (if not already in the cabinet)

- [ ] 3x short Ethernet patch cables (Cat5e/Cat6, 1-3ft) for Trio #2, SCADaPack, Uplogix
- [ ] 1x RJ45-to-DB9 serial cable (for Uplogix to Catalyst console -- optional, future use)
- [ ] 1x USB-to-DB9 serial adapter (for Trio radio serial config -- if not already available)

---

## TASK 1: Raspberry Pi -- Enable SSH (5 minutes)

**Goal:** Enable SSH so EC2 can reach it as the edge collector.

### Option A: Create SSH flag file (no reimage)

1. Power off the Pi (unplug power)
2. Remove the microSD card
3. Insert into SHOP-01's SD card reader (or use a USB adapter)
4. Open File Explorer, find the **boot** partition (usually drive D: or E:)
5. Right-click in the boot partition > New > Text Document
6. Rename it to `ssh` (no extension -- not `ssh.txt`)
   - If Windows hides extensions: View > Show > File name extensions, then rename
7. Eject the SD card safely
8. Reinsert into Pi, power on
9. Wait 60 seconds, then from SHOP-01 command prompt:
   ```
   ssh pi@192.168.88.254
   ```
   Default password: `raspberry`

### Option B: Full reimage (if Option A fails)

1. Download Raspberry Pi Imager on SHOP-01: https://www.raspberrypi.com/software/
2. Flash **Raspberry Pi OS Lite (64-bit)** to the SD card
3. In Imager settings (gear icon), enable:
   - SSH (password authentication)
   - Username: `pi`, Password: `Aevus2026!`
   - Hostname: `aevus-edge`
   - WiFi: skip (wired only)
4. Flash, eject, reinsert into Pi, power on
5. SSH in: `ssh pi@192.168.88.254`

### After SSH works:

From SHOP-01 or via EC2 tunnel, run:
```bash
ssh pi@192.168.88.254
sudo apt update && sudo apt install -y snmpd snmp python3-pip
```

---

## TASK 2: Cisco Catalyst 2960 -- Password Recovery (15 minutes)

**Goal:** Reset enable password, assign management IP 192.168.88.2, enable SNMP.

### Step 1: Password Recovery

1. On SHOP-01, have PuTTY open on COM6 at 9600 baud (already connected)
2. Locate the **Mode** button on the front of the Catalyst 2960 (small recessed button, front-left)
3. Unplug the Catalyst power cable
4. **Press and hold the Mode button**
5. Plug the power cable back in **while holding Mode**
6. Watch PuTTY -- release Mode when you see:
   ```
   The system has been interrupted prior to initializing the flash filesystem.
   ```
   or the `switch:` prompt appears
7. At the `switch:` prompt, type:
   ```
   flash_init
   rename flash:config.text flash:config.old
   boot
   ```
8. The switch will boot with no config. When prompted:
   ```
   Would you like to enter the initial configuration dialog? [yes/no]: no
   ```
9. Press Enter, you should get `Switch>`
10. Type `enable` (no password needed now)
11. You should get `Switch#`

### Step 2: Configure the Switch

At the `Switch#` prompt, paste these commands ONE LINE AT A TIME in PuTTY (right-click to paste each line):

```
configure terminal
hostname Aevus-SW1
enable secret Aevus2026!
no ip domain-lookup
!
interface vlan 1
 ip address 192.168.88.2 255.255.255.0
 no shutdown
!
ip default-gateway 192.168.88.1
!
snmp-server community aevus_ro RO
snmp-server location Lab Cabinet
snmp-server contact woody@intrepidlogic.io
!
line console 0
 password Aevus2026!
 login
 logging synchronous
!
line vty 0 15
 password Aevus2026!
 login
!
end
```

### Step 3: Save and Verify

```
copy running-config startup-config
```
Press Enter to confirm filename.

```
show ip interface brief
show snmp
```

Verify VLAN1 shows `192.168.88.2` with status `up/up`.

### Step 4: Test from SHOP-01

Open a new command prompt:
```
ping 192.168.88.2
```
Should get replies.

---

## TASK 3: Trio JR900 #1 (RAD-01) -- Serial Config (15 minutes)

**Goal:** Assign IP 192.168.88.11, enable SNMP community `aevus_ro`.

### Prerequisites
- USB-to-DB9 serial adapter plugged into SHOP-01
- DB9 serial cable connected to the Trio JR900 #1 serial/console port
- Note: This is a DIFFERENT cable than the Cisco RJ45 console cable

### Step 1: Find the COM Port

1. On SHOP-01, open Device Manager (right-click Start > Device Manager)
2. Expand "Ports (COM & LPT)"
3. Note the COM port number for the USB-to-Serial adapter (e.g., COM3)

### Step 2: Connect via PuTTY

1. Open PuTTY
2. Connection type: Serial
3. Serial line: COM# (from step 1)
4. Speed: 9600 (Trio default)
5. Click Open
6. Press Enter a few times to get a prompt

### Step 3: Configure Network

Trio JR900 serial commands (may vary by firmware version -- consult the Trio manual if these don't work):

```
# Enter configuration mode
configure

# Set static IP
ip address 192.168.88.11
ip netmask 255.255.255.0
ip gateway 192.168.88.1

# Enable SNMP
snmp enable
snmp community read aevus_ro

# Save and apply
save
reboot
```

**Alternative:** If the Trio has a web UI, it may come up on a default IP after serial config. Check the Trio JR900 Quick Start Guide for the exact CLI syntax. Common alternatives:

```
# Some Trio firmware uses:
set ip addr 192.168.88.11
set ip mask 255.255.255.0
set ip gw 192.168.88.1
set snmp community aevus_ro
write
reload
```

### Step 4: Verify

After reboot, from SHOP-01:
```
ping 192.168.88.11
snmpwalk -v2c -c aevus_ro 192.168.88.11 1.3.6.1.2.1.1.1.0
```

If snmpwalk returns sysDescr, the radio is fully online.

---

## TASK 4: Trio JR900 #2 (RAD-02) -- Power On + Serial Config (15 minutes)

**Goal:** Power on, assign IP 192.168.88.12, enable SNMP.

1. Locate Trio JR900 #2 in the cabinet
2. Plug in power (DC power supply or PoE -- check the unit)
3. Connect Ethernet cable from Trio #2 to **Catalyst 2960 Fa0/1**
4. Wait 60 seconds for boot
5. Move the serial cable from Trio #1 to Trio #2
6. Open PuTTY on the same COM port, 9600 baud
7. Follow the same serial config as Task 3, but use:
   - IP: `192.168.88.12`
   - Everything else same

### Verify:
```
ping 192.168.88.12
snmpwalk -v2c -c aevus_ro 192.168.88.12 1.3.6.1.2.1.1.1.0
```

---

## TASK 5: SCADAPack 470 (RTU-01) -- Power On + Reconfigure IP (20 minutes)

**Goal:** Power on, change IP from 192.168.1.201 to 192.168.88.21, verify Modbus TCP.

### Step 1: Physical

1. Locate SCADaPack 470 in the cabinet (Schneider Electric, labeled Serial# 410021)
2. Plug in power (check if it needs 12/24VDC or AC -- the unit label will say)
3. Connect Ethernet cable from SCADaPack to **Catalyst 2960 Fa0/2**
4. Wait 2 minutes for full boot

### Step 2: Access via Old IP

The MikroTik already has a secondary IP on the 192.168.1.x subnet (192.168.1.100/24, added remotely). From SHOP-01:

```
ping 192.168.1.201
```

If it responds, open a web browser on SHOP-01 and go to:
```
http://192.168.1.201
```

The SCADaPack should have a web configuration interface (SCADAPack Configurator or built-in web server).

### Step 3: Reconfigure IP

**Option A: Web UI**
1. Navigate to Network Settings
2. Change IP to: `192.168.88.21`
3. Subnet: `255.255.255.0`
4. Gateway: `192.168.88.1`
5. Save and reboot

**Option B: SCADaPack Configurator Software (if installed on SHOP-01)**
1. Open SCADAPack Workbench or Control Expert (icons visible on SHOP-01 desktop)
2. Connect to 192.168.1.201
3. Change IP settings
4. Download to controller

**Option C: Serial Console**
1. Connect USB-to-serial to the SCADaPack serial port
2. Use SCADAPack Configurator to connect via serial
3. Change IP settings

### Step 4: Verify Modbus TCP

After IP change, from SHOP-01:
```
ping 192.168.88.21
```

To test Modbus TCP (port 502), from SHOP-01 command prompt:
```
curl -v telnet://192.168.88.21:502
```
If it connects (doesn't say "Connection refused"), Modbus TCP is listening.

### Step 5: Verify DNP3

```
curl -v telnet://192.168.88.21:20000
```
If it connects, DNP3 is listening on the expected port.

---

## TASK 6: Uplogix 5000 -- Power On + Configure (10 minutes)

**Goal:** Get basic connectivity for future out-of-band management.

1. Locate Uplogix 5000 in the cabinet
2. Plug in power
3. Connect Ethernet cable from Uplogix management port to **Catalyst 2960 Fa0/3**
4. Wait 3 minutes for boot
5. The Uplogix may have a default IP. Common defaults:
   - `169.254.x.x` (link-local)
   - `192.168.1.1`
   - Check the label on the unit
6. If it gets DHCP from the MikroTik, check the lease table:
   - From SHOP-01: open WinBox > IP > DHCP Server > Leases
7. Once you find the IP, open a browser to `https://<ip>` for the web UI
8. Default credentials are typically: `admin` / `password` or `admin` / blank
9. Set a static IP: `192.168.88.5`

---

## POST-VISIT VERIFICATION CHECKLIST

After all tasks are complete, run these from SHOP-01 command prompt:

```
echo === Connectivity Test ===
ping -n 2 192.168.88.1    & REM MikroTik
ping -n 2 192.168.88.2    & REM Catalyst 2960
ping -n 2 192.168.88.5    & REM Uplogix 5000
ping -n 2 192.168.88.11   & REM Trio JR900 #1
ping -n 2 192.168.88.12   & REM Trio JR900 #2
ping -n 2 192.168.88.21   & REM SCADaPack 470
ping -n 2 192.168.88.254  & REM Raspberry Pi

echo === SNMP Test ===
snmpwalk -v2c -c aevus_ro 192.168.88.2  1.3.6.1.2.1.1.1.0
snmpwalk -v2c -c aevus_ro 192.168.88.11 1.3.6.1.2.1.1.1.0
snmpwalk -v2c -c aevus_ro 192.168.88.12 1.3.6.1.2.1.1.1.0
```

Once all devices respond, notify Dave/Claude. The collectors on EC2 will automatically start polling via the WireGuard tunnel (MikroTik routes 192.168.88.0/24 traffic through wg-aevus to EC2 at 10.99.0.1).

---

## IP ADDRESS REFERENCE

| Device | IP | MAC | Purpose |
|---|---|---|---|
| MikroTik L009 | 192.168.88.1 | 78:9A:18:B9:B8:4C | Router/WAN/WireGuard |
| Catalyst 2960 | 192.168.88.2 | 68:BD:AB:61:AA:00 | L2 Switch |
| Uplogix 5000 | 192.168.88.5 | TBD | OOB Management |
| Trio JR900 #1 | 192.168.88.11 | 00:1F:EB:00:75:6F | Radio (RAD-01) |
| Trio JR900 #2 | 192.168.88.12 | TBD | Radio (RAD-02) |
| SCADaPack 470 | 192.168.88.21 | TBD | RTU (RTU-01) |
| Raspberry Pi | 192.168.88.254 | 2C:CF:67:34:E1:92 | Edge Collector |
| SHOP-01 | 192.168.88.253 | 84:47:09:42:40:EC | Windows PC |

## CREDENTIALS REFERENCE

| Device | Username | Password | Notes |
|---|---|---|---|
| MikroTik L009 | admin | MBHPTAFRIY | WinBox + SSH |
| Catalyst 2960 | (enable) | Aevus2026! | After password recovery |
| Raspberry Pi | pi | raspberry (or Aevus2026!) | Depends on Option A vs B |
| SCADaPack 470 | - | - | Check unit documentation |
| Uplogix 5000 | admin | (check label) | Default varies |

## EMERGENCY CONTACTS

- **Woody:** woody@intrepidlogic.io
- **EC2 Dashboard:** https://aevus.intrepidlogic.io (aevus / Intrepid!Aevus2026)
- **EC2 SSH:** `ssh -i aevus-testbed.pem ubuntu@54.211.59.53`
