"""The guitar stem after a lead/rhythm split, and the UI server's port choice."""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest

import numpy as np

from unweave.audio.guitar_split import mute_section, section_gain, split_guitar
from unweave.projects.store import describe_project
from unweave.webui.library import Library
from unweave.webui.server import bind_server, running_unweave

from test_trim import project


class MutedSectionTests(unittest.TestCase):
    def check_adds_back_up(self, start, frames, fade_in, fade_out):
        guitar = np.random.default_rng(1).uniform(-1, 1, (20000, 2)).astype("float32")
        gain = section_gain(frames, 220, fade_in, fade_out)
        # Lead and rhythm together are exactly the faded section the split was given.
        leaves = guitar[start:start + frames] * gain[:, None]
        muted = mute_section(guitar, start, gain)
        played = muted.copy()
        played[start:start + frames] += leaves
        np.testing.assert_allclose(played, guitar, atol=1e-6)
        return muted

    def test_a_middle_section_leaves_a_hole_that_the_leaves_fill(self):
        muted = self.check_adds_back_up(4000, 8000, True, True)
        self.assertFalse(muted[4300:11700].any())
        self.assertTrue(muted[:4000].any() and muted[12000:].any())

    def test_a_section_at_the_start_fades_only_at_its_end(self):
        self.check_adds_back_up(0, 8000, False, True)

    def test_the_source_is_left_alone(self):
        guitar = np.ones((1000, 2), dtype="float32")
        mute_section(guitar, 100, section_gain(500, 50, True, True))
        self.assertTrue((guitar == 1).all())

    def test_replacing_needs_the_guitar_inside_the_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / "guitar.flac").write_bytes(b"x")
            (base / "out").mkdir()
            with self.assertRaises(ValueError):
                split_guitar(base / "guitar.flac", base / "out", base, replace_source=True)


class MutedGuitarListingTests(unittest.TestCase):
    def test_a_muted_guitar_is_listed_next_to_lead_and_rhythm(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = project(Path(temporary), {
                "stems": ["vocals", "guitar"],
                "trim": {"start": 90, "end": 120},
                "lead_rhythm_split": {"model": "listra92", "guitar": "muted",
                                      "trim": {"start": 95, "end": 110}},
            })
            offsets = {item["file"]: item["offset"] for item in describe_project(path)["stems"]}
            self.assertEqual(offsets["guitar.wav"], 90.0)
            self.assertEqual(offsets["lead.wav"], 95.0)

    def test_an_older_split_still_hides_its_whole_guitar(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = project(Path(temporary), {"lead_rhythm_split": {"model": "listra92"}})
            files = {item["file"] for item in describe_project(path)["stems"]}
            self.assertNotIn("guitar.wav", files)


class NotFound(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"404")

    def log_message(self, *args):
        pass


class PortTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.library = Library(base / "projects", base / "ui.json", base / "cache")
        self.servers = []

    def tearDown(self):
        for server in self.servers:
            server.shutdown()
            server.server_close()
        self.temporary.cleanup()

    def run_server(self, server):
        self.servers.append(server)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server.server_address[1]

    def test_a_port_held_by_another_program_moves_unweave_along(self):
        taken = self.run_server(HTTPServer(("127.0.0.1", 0), NotFound))
        server = bind_server(self.library, taken)
        try:
            self.assertNotEqual(server.server_port, taken)
        finally:
            # Never started, so shutdown() would wait forever; just close it.
            server.server_close()

    def test_only_unweave_counts_as_a_running_unweave(self):
        foreign = self.run_server(HTTPServer(("127.0.0.1", 0), NotFound))
        self.assertFalse(running_unweave(foreign))
        ours = self.run_server(bind_server(self.library, foreign))
        self.assertTrue(running_unweave(ours))


if __name__ == "__main__":
    unittest.main()
