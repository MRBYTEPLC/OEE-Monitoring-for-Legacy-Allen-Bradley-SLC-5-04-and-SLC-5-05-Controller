# 🏭 Open-Source OEE & Analytics for Legacy Allen-Bradley SLC 500 PLCs

[![License: MIT](https://shields.io)](https://opensource.org)
[![Python Version](https://shields.io)](https://python.org)

**Modernize U.S. manufacturing lines without the multi-thousand-dollar price tag of proprietary industrial software.** 

Millions of dollars in American production lines still run on legacy **Allen-Bradley SLC 5/04 and SLC 5/05 controllers**. They are absolute tanks—incredibly reliable and built to last. However, they lack a native way to report the live metrics (OEE, precise downtime reasons, and digital alarm history) that modern Continuous Improvement (CI) and Quality programs demand.

This project provides a **100% Python-based, open-source architecture** to extract data from legacy SLC PLCs, compute OEE, and host a lightweight Web Dashboard accessible across your **Plant Network**. No hardware replacement required. No licensing fees.

---

## The Mission: Modernizing  Factories
Our goal is to support the revitalization and efficiency of manufacturing plants across the United States. Many small-to-medium enterprises (SMEs) cannot afford expensive MES/SCADA upgrades. 
By providing a free, robust, and easily deployable software stack, we help local plants keep their reliable machines running while gaining 21st-century data insights.

---

## Key Features (What It Does)
- **100% Python-Based:** Simple to deploy, modify, and scale. Runs on any local server or an inexpensive Edge device (like a Raspberry Pi) connected to the plant network.
- **Real-Time OEE Web Dashboard:** A clean browser interface built entirely in Python (Flask/FastAPI) to monitor Availability, Performance, and Quality.
- **Downtime & Alarm Logging:** Automatically captures and logs fault codes into a lightweight local SQLite database.
- **Plant-Wide Remote Access:** Designed to be securely accessed by managers, supervisors, and operators from any device on the local network.
- **Non-Invasive Integration:** Requires only a tiny ladder logic subroutine in your existing RSLogix 500 project. Your main machine control remains completely untouched.

---

## The Proposed Tech Stack
- **Backend/Frontend:** Python 3 (Flask or FastAPI for server and UI generation).
- **PLC Communication:** Python libraries (`pycomm3` or `pylogix`) over Ethernet.
- **Database:** SQLite (Zero-configuration, lightweight, and local).

---

## We Need Your Help! (How to Collaborate)
This is a community-driven project aimed at helping real manufacturing floors. We are currently building our **Minimal Viable Product (MVP)** and looking for contributors to help with:
- Structuring the main Python polling loop safely to avoid PLC CPU overhead.
- Designing a beautiful, simple HTML/CSS/JS frontend using pure Python components.
- Testing connection scripts with real or emulated SLC 500 processors.

If you want to contribute to the future of open-source industrial automation, check out our active [Issues][(https://github.com/MRBYTEPLC) or open a Pull Request!

---

## Did This Help Your Plant? (Show & Tell!)
**We want to hear from you!** If you successfully deploy this architecture, download our scripts, or use this idea to improve efficiency on your factory floor:
1. **Leave a comment** in our Discussions section.
2. **Open an issue** with feedback, feature requests, or suggestions.
3. **Share a screenshot** or a story about how much your plant saved.

Your real-world feedback is what motivates the community to keep refining and optimizing this project. Let's build a stronger, more efficient manufacturing ecosystem together!

---
*Disclaimer: This project is an independent open-source initiative and is not affiliated with, authorized, or endorsed by Rockwell Automation or Allen-Bradley.*
* **Liability & Safety Disclaimer:** This software and its documentation are provided "as is" for educational and informational purposes only. Industrial automation involving live machinery carries inherent risks of property damage, production downtime, physical injury, or loss of life. The creators, contributors, and maintainers of this repository assume absolutely no responsibility or liability for any errors, malfunctioning, damages, or financial losses resulting from the use or misuse of this code. Any implementation on a live production floor is done completely at the user's own risk, and the final engineer or technician deploying this system is solely responsible for verifying its safety, accuracy, and compliance with local industrial regulations.*
