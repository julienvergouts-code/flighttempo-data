import struct
import tempfile
import unittest
from pathlib import Path

from pipeline.build_corridors import RepositoryNavDatabase, FTWG_HEADER, FTWG_NODE, FTWG_EDGE

class FtWGReaderTests(unittest.TestCase):
    def make_graph(self, path):
        nodes=[("FIXA",50000000,4000000,1),("FIXB",51000000,5000000,1)]
        edges=[(0,1,100,b"UL9"),(1,0,100,b"UL9")]
        with path.open("wb") as f:
            f.write(FTWG_HEADER.pack(b"FTWG",1,0,len(nodes),len(edges)))
            for ident,lat,lon,kind in nodes:
                f.write(FTWG_NODE.pack(ident.encode(),lat,lon,kind))
            for edge in edges: f.write(FTWG_EDGE.pack(*edge))

    def test_loads_nodes_and_directed_edges(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"graph.bin"; self.make_graph(p)
            db=RepositoryNavDatabase(); db._load_ftwg_binary(p)
            self.assertEqual(db.graph_source,"FTWG_BINARY_V1")
            self.assertIn("FIXB",[e[0] for e in db.adj["FIXA"]])
            self.assertEqual(db.a_star_connected("FIXA","FIXB")[0],["FIXA","FIXB"])

    def test_duplicate_identifier_nodes_do_not_teleport_between_locations(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"graph.bin"
            nodes=[
                ("START",0,0,1),("DUP",100000,100000,1),
                ("DUP",30000000,30000000,1),("GOAL",30100000,30100000,1),
            ]
            edges=[(0,1,100,b"X1"),(2,3,100,b"X2")]
            with p.open("wb") as f:
                f.write(FTWG_HEADER.pack(b"FTWG",1,0,len(nodes),len(edges)))
                for ident,lat,lon,kind in nodes:
                    f.write(FTWG_NODE.pack(ident.encode(),lat,lon,kind))
                for edge in edges: f.write(FTWG_EDGE.pack(*edge))
            db=RepositoryNavDatabase(); db._load_ftwg_binary(p)
            # The identifier-collapsed legacy graph would incorrectly connect START
            # through DUP to GOAL; physical-node search correctly sees no path.
            self.assertIsNone(db.a_star_connected("START","GOAL",(0,0),(30.1,30.1)))

    def test_duplicate_identifier_endpoint_requires_coordinate(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"graph.bin"
            nodes=[("DUP",0,0,1),("DUP",30000000,30000000,1),("GOAL",30100000,30100000,1)]
            edges=[(0,2,100,b"X1"),(1,2,100,b"X2")]
            with p.open("wb") as f:
                f.write(FTWG_HEADER.pack(b"FTWG",1,0,len(nodes),len(edges)))
                for ident,lat,lon,kind in nodes: f.write(FTWG_NODE.pack(ident.encode(),lat,lon,kind))
                for edge in edges: f.write(FTWG_EDGE.pack(*edge))
            db=RepositoryNavDatabase(); db._load_ftwg_binary(p)
            with self.assertRaisesRegex(ValueError,"Ambiguous physical fix identifier DUP"):
                db.resolve_physical_endpoint("DUP",None,"start")
            resolved=db.resolve_physical_endpoint("DUP",(30,30),"start")
            self.assertEqual(resolved["node_index"],1)
            self.assertLess(resolved["offset_nm"],1)

    def test_physical_astar_returns_lowest_cost_path_with_duplicate_names(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"graph.bin"
            nodes=[("START",0,0,1),("DUP",100000,100000,1),
                   ("DUP",200000,200000,1),("GOAL",300000,300000,1)]
            edges=[(0,1,100,b"SHORT1"),(1,3,1000,b"SHORT2"),
                   (0,2,300,b"LONG1"),(2,3,300,b"LONG2")]
            with p.open("wb") as f:
                f.write(FTWG_HEADER.pack(b"FTWG",1,0,len(nodes),len(edges)))
                for ident,lat,lon,kind in nodes: f.write(FTWG_NODE.pack(ident.encode(),lat,lon,kind))
                for edge in edges: f.write(FTWG_EDGE.pack(*edge))
            db=RepositoryNavDatabase(); db._load_ftwg_binary(p)
            path,cost=db.a_star_connected("START","GOAL",(0,0),(0.3,0.3))
            self.assertEqual(path,["START","DUP","GOAL"])
            self.assertAlmostEqual(cost,60.0)
            self.assertEqual([n["node_index"] for n in db.last_route_physical_path],[0,2,3])
            self.assertAlmostEqual(sum(n["step_cost_nm"] for n in db.last_route_physical_path),cost)
            self.assertAlmostEqual(db.last_route_physical_path[-1]["cumulative_cost_nm"],cost)
            self.assertEqual(db.last_route_physical_path[1]["airway_from_previous"],"LONG1")

    def test_rejects_wrong_magic(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"graph.bin"; p.write_bytes(b"NOPE"+bytes(40))
            with self.assertRaises(ValueError): RepositoryNavDatabase()._load_ftwg_binary(p)

    def test_rejects_truncated_graph(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"graph.bin"; p.write_bytes(FTWG_HEADER.pack(b"FTWG",1,0,2,2))
            with self.assertRaises(ValueError): RepositoryNavDatabase()._load_ftwg_binary(p)

if __name__=="__main__": unittest.main()
