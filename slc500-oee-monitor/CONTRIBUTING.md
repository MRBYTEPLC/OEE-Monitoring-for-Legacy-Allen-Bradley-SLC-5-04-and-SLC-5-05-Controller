# Contributing

Field reports are the most valuable contribution: PLC model and OS revision, gateway used (SLC 5/04), what worked, what did not.
Open an issue with the template "Field report", or a pull request. Please keep the PLC logic in `tools/build_plc.py` (single source of
truth for the ladder listing and ASCII rungs) and add a unit test for any change to the KPI maths in `src/oee_monitor/oee.py`.
Run `python -m unittest discover -s tests` before submitting.
