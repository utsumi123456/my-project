# -*- coding: utf-8 -*-
"""Models write "type"/"track_id" where the wire format says "op"/"track_ref";
the parser accepts those instead of rejecting a good proposal."""
import unittest

from setagent.agent.changeset import Op, Rejected


class OpAliasTests(unittest.TestCase):
    def test_canonical(self):
        o = Op.from_dict({"op": "remove", "track_ref": "a"})
        self.assertEqual((o.op, o.params), ("remove", {"track_ref": "a"}))

    def test_type_and_track_id_aliases(self):
        o = Op.from_dict({"type": "remove", "track_id": "a"})
        self.assertEqual((o.op, o.params), ("remove", {"track_ref": "a"}))
        o = Op.from_dict({"operation": "set_tempo", "track": "b", "bpm": 170})
        self.assertEqual((o.op, o.params), ("set_tempo", {"track_ref": "b", "bpm": 170}))

    def test_insert_keeps_track_id(self):
        o = Op.from_dict({"op": "insert", "track_id": "x", "at_index": 3})
        self.assertEqual(o.params, {"track_id": "x", "at_index": 3})

    def test_unknown_still_rejected(self):
        with self.assertRaises(Rejected):
            Op.from_dict({"type": "delete", "track_ref": "a"})
        with self.assertRaises(Rejected):
            Op.from_dict({"track_ref": "a"})


if __name__ == "__main__":
    unittest.main()
