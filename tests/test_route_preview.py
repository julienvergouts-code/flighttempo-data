import importlib.util
import struct
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "route_preview.py"
spec = importlib.util.spec_from_file_location("route_preview", SCRIPT)
route_preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route_preview)

class RoutePreviewTests(unittest.TestCase):
    def test_reads_ftwg_and_generates_airway_path(self):
        header = struct.Struct("<4sHHIIII")
        node = struct.Struct("<iiIHH")
        edge = struct.Struct("<IIIHBBII")
        strings = bytearray()
        def add_string(s):
            raw=s.encode()
            off=len(strings); strings.extend(raw)
            return off,len(raw)
        rows=[]
        for lat,lon,ident,flag in [(520000000,90000000,"EDDV",1),
                                   (515000000,80000000,"FIXA",0),
                                   (510000000,60000000,"EBLG",1)]:
            off,n=add_string(ident); rows.append((lat,lon,off,n,flag))
        airway_off,airway_len=add_string("Y1")
        conn1_off,conn1_len=add_string("DIRECT_CONNECTOR:EDDV")
        conn2_off,conn2_len=add_string("DIRECT_CONNECTOR:EBLG")
        edges=[
            (0,1,conn1_off,conn1_len,0,1,0,0),
            (1,2,airway_off,airway_len,2,0,0,45000),
            (2,1,conn2_off,conn2_len,0,1,0,0),
        ]
        payload=bytearray(header.pack(b"FTWG",1,0,len(rows),len(edges),len(strings),2))
        for r in rows: payload.extend(node.pack(*r))
        for e in edges: payload.extend(edge.pack(*e))
        payload.extend(strings)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"graph.bin"; path.write_bytes(payload)
            nodes,airports,adj,meta=route_preview.load_graph(path)
        result=route_preview.find_route(nodes,airports,adj,"EDDV","EBLG",35000)
        self.assertEqual(result["routeClass"],"generated_candidate")
        self.assertEqual(result["legs"][1]["edge"],"Y1")
        self.assertEqual(result["status"],"candidate")

    def test_rejects_unknown_airport(self):
        with self.assertRaises(ValueError):
            route_preview.find_route([],{}, {}, "EDDV","EBLG",35000)

if __name__ == "__main__":
    unittest.main()
