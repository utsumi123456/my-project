import unittest
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from setagent.domain.draft import SetDraft, TrackEntry
from setagent.rekordbox.xml_export import build_xml, _location


@dataclass
class T:
    id: str; title: str; artist: str; bpm: float; length_s: int; key: str
    folder_path: str; file_type: int = 1
    @property
    def is_cloud(self): return self.folder_path.startswith("/contents_") or self.folder_path.startswith("spotify:")


class FakeDB:
    def __init__(self, m): self.m = m
    def export_row(self, i):
        t = self.m[i]
        return {"ID": t.id, "Title": t.title, "Artist": t.artist, "Composer": "", "Album": "",
                "Genre": "", "FileName": t.folder_path.rsplit("/", 1)[-1], "FileSize": 123,
                "Length": t.length_s, "DiscNo": 0, "TrackNo": 0, "ReleaseYear": 0,
                "BPM": int(t.bpm * 100), "DateCreated": "2026-01-02", "BitRate": 320,
                "SampleRate": 44100, "Commnt": "", "DJPlayCount": 0, "Rating": 0,
                "FolderPath": t.folder_path, "Remixer": "", "Tonality": t.key, "Label": ""}


class FakeAnalysis:
    anlz = None


class Lib:
    def __init__(self, *ts):
        self.m = {t.id: t for t in ts}
        self.db = FakeDB(self.m)
    def track(self, i): return self.m[i]
    def analysis(self, i): return FakeAnalysis()


class XmlTests(unittest.TestCase):
    def test_location_url_encoding(self):
        self.assertEqual(_location("C:/Music/a b.mp3"), "file://localhost/C:/Music/a%20b.mp3")

    def test_location_percent_escapes_are_lowercase_like_rekordbox(self):
        # rekordbox emits %c3%ab, not %C3%AB
        self.assertEqual(_location("C:/M/Dihhël.mp3"), "file://localhost/C:/M/Dihh%c3%abl.mp3")

    def test_local_tracks_included_cloud_skipped(self):
        lib = Lib(T("1", "Local", "A", 160.0, 300, "Am", "C:/Music/x.mp3"),
                  T("2", "Cloud", "B", 140.0, 200, "", "/contents_1/y.mp3"))
        d = SetDraft(name="demo", tracks=[TrackEntry("1"), TrackEntry("2")])
        xml, meta = build_xml(d, lib)
        self.assertEqual(meta["included"], 1)
        self.assertEqual(len(meta["skipped"]), 1)
        root = ET.fromstring(xml)
        self.assertEqual(root.find("COLLECTION").get("Entries"), "1")
        self.assertEqual(len(root.find("PLAYLISTS/NODE/NODE").findall("TRACK")), 1)

    def test_play_range_becomes_two_cues(self):
        lib = Lib(T("1", "X", "A", 160.0, 300, "Am", "C:/Music/x.mp3"))
        d = SetDraft(name="d", tracks=[TrackEntry("1", play_in_ms=60000, play_out_ms=180000)])
        root = ET.fromstring(build_xml(d, lib)[0])
        marks = root.find("COLLECTION/TRACK").findall("POSITION_MARK")
        self.assertEqual([m.get("Start") for m in marks], ["60.000", "180.000"])
        self.assertEqual(marks[0].get("Name"), "SetAgent IN")
        self.assertEqual(marks[0].get("Num"), "-1")   # memory cue

    def test_track_has_full_rekordbox_attribute_set(self):
        from setagent.rekordbox.xml_export import TRACK_ATTR_ORDER
        lib = Lib(T("1", "X", "A", 160.0, 300, "Am", "C:/Music/x.mp3"))
        d = SetDraft(name="d", tracks=[TrackEntry("1")])
        tr = ET.fromstring(build_xml(d, lib)[0]).find("COLLECTION/TRACK")
        self.assertEqual(list(tr.attrib.keys()), TRACK_ATTR_ORDER)
        self.assertEqual(tr.get("Kind"), "MP3 File")
        self.assertEqual(tr.get("BitRate"), "320")

    def test_playlist_name_is_ascii_safe(self):
        lib = Lib(T("1", "X", "A", 160.0, 300, "Am", "C:/Music/x.mp3"))
        d = SetDraft(name="acid", tracks=[TrackEntry("1")])
        node = ET.fromstring(build_xml(d, lib)[0]).find("PLAYLISTS/NODE/NODE")
        self.assertEqual(node.get("Name"), "SetAgent acid")

    def test_tempo_override_used_in_bpm(self):
        lib = Lib(T("1", "X", "A", 160.0, 300, "Am", "C:/Music/x.mp3"))
        d = SetDraft(name="d", tracks=[TrackEntry("1", tempo=176.0)])
        root = ET.fromstring(build_xml(d, lib)[0])
        self.assertEqual(root.find("COLLECTION/TRACK").get("AverageBpm"), "176.00")




class PreviewTests(unittest.TestCase):
    def test_preview_lists_what_travels_and_what_does_not(self):
        from setagent.rekordbox.xml_export import describe_preview, export_preview
        lib = Lib(T("1", "Local", "A", 160.0, 300, "Am", "C:/Music/x.mp3"),
                  T("2", "Cloud", "B", 140.0, 200, "", "/contents_1/y.mp3"))
        d = SetDraft(name="demo", tracks=[TrackEntry("1", play_in_ms=60000, play_out_ms=180000),
                                          TrackEntry("2")])
        p = export_preview(d, lib)
        self.assertEqual(p["carried"], ["Local"])
        self.assertEqual(len(p["dropped"]), 1)
        self.assertTrue(any("メモリーキュー" in k for k in p["keeps"]))
        self.assertTrue(any("マイルストーン" in k for k in p["loses"]))
        text = describe_preview(p)
        self.assertIn("1曲", text)
        self.assertIn("再起動", text)

    def test_preview_agrees_with_what_build_xml_actually_writes(self):
        from setagent.rekordbox.xml_export import build_xml, export_preview
        lib = Lib(T("1", "Local", "A", 160.0, 300, "Am", "C:/Music/x.mp3"),
                  T("2", "Cloud", "B", 140.0, 200, "", "/contents_1/y.mp3"))
        d = SetDraft(name="demo", tracks=[TrackEntry("1"), TrackEntry("2")])
        p = export_preview(d, lib)
        _, meta = build_xml(d, lib)
        self.assertEqual(len(p["carried"]), meta["included"])
        self.assertEqual(len(p["dropped"]), len(meta["skipped"]))


if __name__ == "__main__":
    unittest.main()
