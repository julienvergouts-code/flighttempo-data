import unittest
from pipeline.segmentation import segment_legs
class SegmentationTests(unittest.TestCase):
 def setUp(self):
  self.airports=[{"lat":50.9,"lon":4.5,"elevation_ft":50}]
 def point(self,t,lat=50.9,lon=4.5,gs=5,alt=50,elev=50):
  return {"timestamp":t,"lat":lat,"lon":lon,"ground_speed_kt":gs,"altitude_ft":alt,"airport_elevation_ft":elev}
 def test_turnaround_zero_gap_splits(self):
  pts=[self.point(t,lat=50.9+(t/100000),lon=4.5,gs=220,alt=30000) for t in range(0,600,60)]
  # 12 minutes of gate/ground observations, followed immediately by departure points.
  pts += [self.point(t,gs=5,alt=50) for t in range(600,1020,60)]
  pts += [self.point(t,lat=51.0+(t-1020)/100000,lon=4.5,gs=180,alt=12000) for t in range(1020,1620,60)]
  legs=segment_legs(pts,self.airports,min_ground_seconds=300)
  self.assertEqual(len(legs),2)
  self.assertEqual(legs[0]["split_reason"],"confirmed_ground_dwell")
 def test_short_ground_stop_not_split(self):
  pts=[self.point(t,gs=200,alt=25000) for t in range(0,600,60)]
  pts += [self.point(t,gs=5,alt=50) for t in range(600,840,60)]
  pts += [self.point(t,gs=200,alt=25000) for t in range(840,1440,60)]
  self.assertEqual(len(segment_legs(pts,self.airports,min_ground_seconds=300)),1)
 def test_ground_far_from_airport_not_split(self):
  pts=[self.point(t,lat=55,lon=10,gs=5,alt=50,elev=50) for t in range(0,600,60)]
  self.assertEqual(len(segment_legs(pts,self.airports,min_ground_seconds=300)),1)
if __name__=="__main__":unittest.main()
