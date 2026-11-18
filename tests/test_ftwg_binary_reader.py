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

    def test_rejects_wrong_magic(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"graph.bin"; p.write_bytes(b"NOPE"+bytes(40))
            with self.assertRaises(ValueError): RepositoryNavDatabase()._load_ftwg_binary(p)

    def test_rejects_truncated_graph(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"graph.bin"; p.write_bytes(FTWG_HEADER.pack(b"FTWG",1,0,2,2))
            with self.assertRaises(ValueError): RepositoryNavDatabase()._load_ftwg_binary(p)

if __name__=="__main__": unittest.main()
