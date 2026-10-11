import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["OEE_HOME"] = tempfile.mkdtemp()

from oee_monitor.oee import Counters, compute_kpis, fmt_hms, to_unsigned16   # noqa: E402
from oee_monitor.plc import SimulatedPLC                                     # noqa: E402
from oee_monitor.storage import Storage                                      # noqa: E402
from oee_monitor import report                                               # noqa: E402


class TestOEE(unittest.TestCase):
    def test_worked_example_from_article(self):
        # 8 h planned production: 6 h run, 1 h idle, 1 h fault; 3000 parts, 60 scrap, ideal 6 s
        k = compute_kpis(Counters(21600, 3600, 3600, 1800, 3000, 60, 4), 6.0)
        self.assertAlmostEqual(k.availability, 0.75)
        self.assertAlmostEqual(k.performance, 18000 / 21600)
        self.assertAlmostEqual(k.quality, 0.98)
        self.assertAlmostEqual(k.oee, 0.6125)
        self.assertAlmostEqual(k.oee, k.fully_productive_s / k.ppt_s)      # identity: OEE = FPT / PPT
        self.assertAlmostEqual(k.mtbf_s, 5400)
        self.assertAlmostEqual(k.mttr_s, 900)

    def test_commissioning_simulation_check(self):
        # 60 s of simulated run at 5 s/part -> 12 parts, 1 scrap
        k = compute_kpis(Counters(60, 0, 0, 0, 12, 1, 0), 5.0)
        self.assertAlmostEqual(k.oee, 11 / 12)

    def test_edges(self):
        k = compute_kpis(Counters(0, 0, 0, 0, 0, 0), 5.0)
        self.assertEqual((k.oee, k.availability, k.performance), (0.0, 0.0, 0.0))
        k = compute_kpis(Counters(100, 0, 0, 0, 100, 0), 5.0)          # 500 s of work in 100 s -> capped
        self.assertTrue(k.performance_capped)
        self.assertEqual(k.performance, 1.0)
        k = compute_kpis(Counters(100, 0, 0, 0, 10, 50), 5.0)          # scrap > total is clamped
        self.assertEqual(k.quality, 0.0)
        with self.assertRaises(ValueError):
            compute_kpis(Counters(1, 1, 1, 1, 1, 1), 0)

    def test_helpers(self):
        self.assertEqual(to_unsigned16(-1), 65535)
        self.assertEqual(fmt_hms(3661), "1:01:01")
        self.assertEqual(fmt_hms(None), "--")


class TestSimAndStorage(unittest.TestCase):
    def test_simulator_and_history(self):
        sim = SimulatedPLC(5.0, speed=5000, seed=1)
        time.sleep(0.5)
        s = sim.read()
        self.assertGreater(s.run_s + s.idle_s + s.fault_s + s.planned_s, 0)
        k = compute_kpis(Counters(s.run_s, s.idle_s, s.fault_s, s.planned_s, s.total, s.scrap, s.fault_events), 5.0)
        self.assertTrue(0 <= k.oee <= 1)
        db = Storage(Path(os.environ["OEE_HOME"]) / "t.db")
        db.add_sample("M1", s, k)
        db.add_alarm_event(s.ts, "M1", 1, "Low air", True)
        sid = db.add_shift("M1", s.ts - 60, s.ts, 5.0, s, k)
        self.assertEqual(len(db.samples_between("M1", 0, 9e12)), 1)
        self.assertEqual(db.shift(sid)["total"], s.total)
        db.set_meta("a", "1")
        db.set_meta("a", "2")
        self.assertEqual(db.get_meta("a"), "2")
        csv_path = Path(os.environ["OEE_HOME"]) / "x.csv"
        self.assertEqual(db.export_samples_csv(csv_path, "M1", 0, 9e12), 1)
        c = Counters(s.run_s, s.idle_s, s.fault_s, s.planned_s, s.total, s.scrap, s.fault_events)
        out = report.build_report(Path(os.environ["OEE_HOME"]) / "r.pdf", "M1", s.ts - 60, s.ts, c, k, 5.0, 85.0,
                                  db.samples_between("M1", 0, 9e12), db.alarm_events("M1"))
        self.assertGreater(out.stat().st_size, 5000)


if __name__ == "__main__":
    unittest.main()
