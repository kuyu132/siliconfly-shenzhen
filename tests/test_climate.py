import math
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from climate import PRESETS, SHANGHAI, controls, validated, fetch_weather

class ClimateTests(unittest.TestCase):
    def test_bad_sensor_values(self):
        for key,value in [('humidity',101),('temperature',float('nan')),('month',1.5),('wind',True)]:
            with self.subTest(key=key),self.assertRaises(ValueError): validated(dict(PRESETS['summer'],**{key:value}))

    def test_heat_suppresses_extreme_temperature(self):
        summer=PRESETS['summer']
        self.assertLess(controls(dict(summer,temperature=42))['activity'],controls(dict(summer,temperature=28))['activity'])

    def test_night_and_dry_air(self):
        noon=dict(PRESETS['summer'],hour=12)
        self.assertLess(controls(dict(noon,hour=23))['activity'],controls(noon)['activity'])
        self.assertGreater(controls(dict(noon,humidity=20))['thirst'],controls(dict(noon,humidity=90))['thirst'])

    def test_all_presets_bounded(self):
        for p in PRESETS.values():
            c=controls(p)
            self.assertTrue(.16<=c['activity']<=1.1)
            self.assertTrue(.42<=c['tempo']<=1.15)

    def test_stale_weather_not_live(self):
        now=datetime.now(SHANGHAI)
        payload={'current':{'time':(now-timedelta(days=1)).isoformat()},'daily':{}}
        with patch('climate.urlopen') as response,patch('json.load',return_value=payload):
            with self.assertRaisesRegex(ValueError,'两小时'): fetch_weather(now)

if __name__=='__main__': unittest.main()
