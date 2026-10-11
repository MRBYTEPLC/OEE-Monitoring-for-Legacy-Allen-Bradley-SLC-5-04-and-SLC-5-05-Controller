# OEE Monitoring for Legacy Allen-Bradley SLC 5/04 and SLC 5/05 Controllers
*Step-by-Step Implementation Guide - Version 1.0*

> **Scope.** This guide shows how to add standards-based Overall Equipment Effectiveness (OEE) monitoring, alarm logging, historical records and printable reports to a machine controlled by an SLC 5/04 or SLC 5/05 processor, using one small ladder subroutine and a free, open-source Python application. No PLC replacement is required. Estimated effort: 1-2 days for a controls technician; incremental hardware cost: $0 for an SLC 5/05, plus one protocol gateway for an SLC 5/04.

## 1. Solution overview

The PLC classifies the machine into exactly one of four states every scan, counts parts and rejects, and accumulates the time spent in each state. A PC reads this small data table over Ethernet every two seconds, computes OEE, stores the history in a local database and presents a dashboard and PDF reports.

```
  Machine I/O ---> SLC 5/04 or 5/05 (LAD 3 OEE_MON) ---> Ethernet ---> PC running Python
  run, fault,        states, counters, timers, alarms      (5/04 needs a     dashboard, SQLite history,
  part, reject       N7 and N10 data files                  PCCC gateway)     PDF reports, CSV export
```

**Design principles.** (1) The PLC only counts and classifies; all calculations are done on the PC, so the legacy program stays small and stable. (2) The PC reads data and issues at most one write (a reset request), so the control function of the machine is never affected. (3) Every quantity is a plain integer in an N-file, readable by any PCCC client.

## 2. Bill of materials and indicative cost

| Item | SLC 5/05 | SLC 5/04 | Indicative cost |
|---|---|---|---|
| Processor with Ethernet | Built in (Channel 1) | Not available | $0 for 5/05 |
| PCCC-capable serial-to-Ethernet gateway | Not needed | Required (Channel 0, DF1) | Typically a few hundred USD; verify current price |
| Windows 10/11 or Linux PC (existing office PC is sufficient) | Required | Required | $0 if existing |
| Python 3.9+, pylogix, matplotlib, reportlab | Required | Required | $0 (open source) |
| RSLogix 500 / Studio 500 licence to edit and download logic | Required | Required | Existing plant licence |
| Ethernet patch cable, switch port | Required | Required | Minimal |

> Prices are indicative only and change over time. Confirm gateway model compatibility with the supplier before purchase (see Section 7.3).

## 3. OEE methodology and applicable standards

### 3.1 Machine states

| State | Definition | Counts toward planned production time? |
|---|---|---|
| RUN | Machine is in automatic cycle, no alarm | Yes |
| IDLE | Powered and healthy but not producing (starved, blocked, waiting for operator or material) | Yes |
| FAULT | Any alarm bit active (breakdown) | Yes |
| PLANNED STOP | Scheduled break, planned maintenance, or other stop defined in your procedure | **No** |

### 3.2 Formulas

1. Planned Production Time (PPT) = Run + Idle + Fault
2. Availability (A) = Run time / PPT
3. Performance (P) = (Ideal cycle time x Total count) / Run time, limited to 100 %
4. Quality (Q) = Good count / Total count, where Good = Total - Scrap
5. **OEE = A x P x Q**, which is algebraically equal to (Good count x Ideal cycle time) / PPT when P is not limited
6. MTBF = Run time / Number of faults; MTTR = Fault time / Number of faults

### 3.3 Relationship to standards

- **ISO 22400-2:2014** (Automation systems and integration - Key performance indicators for manufacturing operations management) defines Availability, Effectiveness, Quality ratio and OEE as manufacturing KPIs. This guide uses the multiplicative A x P x Q structure and the widely used Total Productive Maintenance (TPM) form of the performance term. If your customer requires formal conformance to the exact ISO 22400-2 wording, verify the definitions against the published standard.
- **IATF 16949:2016** requires a documented total productive maintenance system with maintenance objectives (clause 8.5.1.5) and monitoring of manufacturing process performance (clause 9.1.1.1). OEE, MTBF and MTTR records produced by this system can serve as objective evidence; confirm the specific measures with your certification body.
- **ISO 9001:2015**, clause 9.1 (monitoring, measurement, analysis and evaluation), supports the use of these indicators.
- **Six Big Losses (Nakajima, TPM):** breakdowns and setup map to Availability; minor stops and reduced speed map to Performance; process defects and start-up rejects map to Quality.
- **Benchmark.** An OEE of 85 % (for example A = 90 %, P = 95 %, Q = 99 %, which multiply to 84.6 %) is commonly cited as world class. The application uses this as the default target; change it in Settings to match your own objective.

## 4. Prerequisites and safety

1. Obtain written authorization from the plant manager and controls owner (management of change).
2. **Back up the existing program:** go online with RSLogix 500 and save the .RSS file, then upload from the processor and store a dated copy.
3. Apply lockout/tagout when connecting cables or installing hardware. Never work on live control cabinets without qualified personnel.
4. Schedule the program download during a planned stop; a download stops the processor.
5. Confirm free program memory (the subroutine uses about 36 rungs) and unused data files N7 and N10, timers T4:0 and T4:1, and bit file B3 (words 0-2). Use other file numbers if these are already in use and edit the addresses consistently.
6. Alarm inputs in this example are for **monitoring only**. They never replace hardwired safety circuits or safety PLC functions.

## 5. Data table

Create the following files in RSLogix 500 if they do not exist: **B3** (bit, 3 words), **N7** (integer, 16 elements), **N10** (integer, 1 element), **T4** (timer, 2 elements). The complete address map is in Appendix A. The most important addresses are:

| Address | Meaning |
|---|---|
| N7:0, N7:1 | Total parts, scrap parts |
| N7:2 to N7:5 and N7:6 to N7:9 | Seconds and minutes for Run, Idle, Fault, Planned stop |
| N7:10 | Fault events |
| N7:11 | Reset request written by the PC |
| N7:12 | Heartbeat (stopped-PLC detection) |
| N7:13 | State code: 0 Idle, 1 Run, 2 Fault, 3 Planned |
| N10:0 | Alarm word (16 bits) |

Time is stored as seconds (0-59) plus whole minutes to avoid the 32,767 limit of a signed 16-bit integer, which a seconds-only counter would reach after about 9 hours.

## 6. Build the ladder logic (identical for 5/04 and 5/05)

1. In RSLogix 500, create a new subroutine file: right-click **Program Files > New**, choose LAD, number **3**, name it **OEE_MON**.
2. Enter the 36 rungs from Appendix B into LAD 3. Alternatively, in a new *offline* project try **File > Import > ASCII** with `plc/OEE_MON_LAD3_rungs.asc` (see the repository README; verify every rung after import).
3. In the main program (LAD 2), add an unconditional rung: `JSR U:3`. Place it after your machine logic so that the I/O states are current.
4. **Edit the input addresses** in the eight rungs marked EDIT ADDRESS (four process inputs and four alarm inputs) so that they point to your machine signals (run contact or cycle-active bit, planned-stop selector, part sensor, reject sensor, alarm inputs). Use normally-closed, fail-safe signals for alarms: the alarm is raised when the input is OFF.
5. Verify the project (**Edit > Verify Project**). Correct any error before downloading.
6. Set the timer in the simulator rung (T4:1 preset = 5) to your machine's ideal cycle time only if you intend to test with the simulator.

## 7. Configure communications

### 7.1 Common network preparation

1. Assign a static IP address from your control network plan (example: 192.168.1.10 / 255.255.255.0). Do not use DHCP for a PLC.
2. Place the PC and PLC on the same isolated control VLAN or a dedicated switch. See Section 11 for cybersecurity.

### 7.2 SLC 5/05 (native Ethernet)

1. Connect RSLogix 500 to the processor through Channel 0 (serial) or an existing Ethernet connection.
2. Open **Channel Configuration**, select the **Chan. 1 - System** tab.
3. Clear **BOOTP Enable**. Enter the IP address, subnet mask and gateway (if required).
4. Download the program to the processor and return it to RUN (or REM as your procedure requires).
5. From the PC, run `ping 192.168.1.10`. Replies confirm the network path.

### 7.3 SLC 5/04 (serial DF1 or DH+ to Ethernet)

The SLC 5/04 has no Ethernet port. It has Channel 0 (RS-232, DF1) and Channel 1 (DH+). The Python library speaks PCCC over EtherNet/IP, so a gateway that converts this to DF1 or DH+ is required.

1. Select a gateway that explicitly supports **PCCC (CSP) over EtherNet/IP** to the SLC 5/04 on the interface you will use. Legacy Allen-Bradley Ethernet-to-DF1 interfaces (for example the 1761-NET-ENI family, subject to availability) and current third-party gateways are candidates; confirm compatibility in the manufacturer datasheet.
2. In RSLogix 500 open **Channel Configuration > Channel 0**. Set the driver to **DF1 Full-Duplex** with the baud rate, parity and error checking recommended by the gateway manual (a typical starting point is 19,200 baud, no parity, CRC).
3. Connect Channel 0 to the gateway with the cable specified by the manufacturer (some devices require a null-modem style crossover).
4. Configure the gateway IP address with the manufacturer's utility, and set its serial port to match Channel 0.
5. Download the program if the channel settings changed, then verify with `ping` and with the connection test in Section 8.4.

## 8. Install and configure the PC software

1. Install Python 3.9 or later from python.org. On Windows, select **Add Python to PATH**. On Linux install `python3-tk`.
2. Download the repository (ZIP or `git clone`) and open a terminal in the project folder.
3. Install dependencies: `python -m pip install -r requirements.txt`
4. Start the application: `python oee_monitor.py`. It starts in **Demo mode** with simulated data so you can explore the screens first.
5. Open the **Settings** tab. Enter the machine name, the PLC (or gateway) IP address, the **ideal cycle time** in seconds per part, the OEE target and the alarm names for N10:0 bits. Clear **Demo mode** and click **Save & apply**. The status badge turns green and shows the IP address.
6. **Ideal cycle time.** Use the rated speed from engineering data, or the fastest cycle time that the machine sustains over at least 100 consecutive good parts. Do not use an average that already includes slow cycles. If the report shows Performance marked as capped at 100 %, the ideal cycle time is too long.

## 9. Commissioning and validation

Perform these tests during a planned stop. Set B3:1/15 (SIM_ENABLE) = 1 and use the simulator rungs; set the ideal cycle time in Settings to 5 s.

| Test | Action | Expected result |
|---|---|---|
| T1 Communication | Save settings with Demo mode off | Green LIVE badge; counters visible |
| T2 Run and timers | Force B3:1/10 = 1 for exactly 60 s | Run time about 0:01:00; state RUNNING |
| T3 Parts | Continue the run above | About 12 parts; 1 scrap after the 10th part |
| T4 KPI check | Read the dashboard after 60 s | Availability 100 %, Performance about 100 %, Quality about 91.7 %, OEE about 91.7 % |
| T5 Planned stop | Release B3:1/10; force B3:1/1 = 1 for 30 s | Planned stop +30 s; Idle, Fault and Availability unchanged |
| T6 Fault | Release B3:1/1; force N10:0/1 = 1 for 30 s | State FAULT; Fault time +30 s; Fault events = 1; alarm text shown and logged |
| T7 Idle | Release all forces | State IDLE; Idle time increases |
| T8 Heartbeat | Place processor in PROG mode (with permission) | Red badge "PLC not scanning" within about 10 s |
| T9 Reset | Click **Close shift & reset** | Counters return to 0; PDF report created; shift stored in History |
| T10 Real signals | Set B3:1/15 = 0; run the machine | State and counts follow real signals; compare 20 parts against a manual count |

**Acceptance criteria:** timers within +/-2 s per 10 minutes against a stopwatch; part count exact over 100 parts; all states reproduced. Remove all forces before returning the machine to production and record the test results in your quality system.

## 10. Daily operation

1. At the start of production, confirm the badge is green and the period start time is correct.
2. During the shift, operators use the state banner and the active-alarm panel. Supervisors review the trend chart.
3. At the end of each shift, click **Close shift & reset**. The system saves the period to the history database, creates a signed-off-ready PDF (Prepared by / Reviewed by lines) and clears the PLC counters.
4. Use **History & Reports** to reprint any earlier report and review the alarm log. Use **Export samples (CSV)** to analyze data in Excel or a BI tool.
5. Back up the folder `OEE_Monitor` (database, settings and reports) weekly. Retain records according to your quality-management procedure.
6. Document in a work instruction how your plant classifies changeovers, lunch breaks, no-material waits and quality holds, so that all shifts apply the same rules.

## 11. Cybersecurity

PCCC and EtherNet/IP provide no built-in authentication. Treat access to the PLC network as access to the machine.

1. Keep the PLC, gateway and monitoring PC on an isolated control network or VLAN with no direct internet route.
2. Use a firewall rule that allows only the monitoring PC to reach TCP port 44818 on the PLC or gateway.
3. Harden the PC: current patches, standard user account, disk encryption where appropriate, no remote-desktop exposure to the internet.
4. Untick **Allow Close shift & reset to write** if you prefer a strictly read-only connection; clear counters from the PLC instead.
5. Keep the SLC processor key switch in RUN when not editing. Follow the segmentation and zone concepts in IEC 62443 and NIST SP 800-82 for OT environments.

## 12. Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| "PLC COMMUNICATION LOST" | Wrong IP, cable, VLAN, firewall, or PLC channel not configured | Ping the IP; check Channel 1 settings; test with another PCCC tool |
| Read error for a specific address | Data file missing or too small | Create N7 (16 words) and N10 in the program and download |
| "PLC NOT SCANNING" | Processor in PROG mode, or LAD 3 not called | Switch to RUN; confirm `JSR U:3` rung |
| Performance shows 100 % with an asterisk | Ideal cycle time too long | Reduce the ideal cycle time in Settings |
| Availability always 100 % | No alarms mapped, or machine idle logic not wired | Verify RUN_IN and alarm input rungs |
| Counts jump or go negative | Counter exceeded 32,767 | Close shift more often; the PC already reads values as unsigned |
| 5/04 gateway silent | Serial parameters differ or wrong cable | Match Channel 0 and gateway settings; check pin-out |

## 13. Limitations and next steps

- One integer counter holds up to 65,535 parts as read by the PC (32,767 in the PLC arithmetic). Close the shift before this limit.
- One PC connection per processor is recommended, because the SLC has a limited number of simultaneous connections.
- The example handles one machine per PLC. For a full line, replicate the subroutine with separate files or read several PLCs from one PC.
- Possible extensions: publishing KPIs over MQTT, feeding a plant historian or BI dashboard, adding reason codes for downtime, and OEE targets by product.

## Appendix A and B - Data table and ladder listing
{{include:plc/SLC500_OEE_ladder_listing.md}}

## Appendix C - Trademarks and disclaimer
Allen-Bradley, SLC, RSLogix and Studio 5000 are trademarks of Rockwell Automation, Inc. This project is independent and is not affiliated with or endorsed by Rockwell Automation. The software and documentation are provided "as is" under the MIT licence, without warranty. The user is responsible for testing, validation, safety review and compliance with applicable regulations and plant procedures before use in production.
