"""The separation plan: which stems own a file, which are folded, which are dropped."""

import tempfile
import unittest
from pathlib import Path

from unweave.audio.pipeline import (_build_other, legacy_group, model_request,
                                        publish_names, resolve_plan, select_model)
from unweave.webui.library import Library, plan_stems, validate_group


class SelectModelTests(unittest.TestCase):
    """One 6-stem model for every multi-stem plan; only karaoke falls back to MDX."""

    def test_a_multi_stem_plan_always_gets_the_six_stem_model(self):
        for stems in (["vocals", "drums"], ["drums"], ["other"], ["vocals", "drums", "other"],
                      ["vocals", "guitar"], ["vocals", "piano", "other"]):
            with self.subTest(stems=stems):
                self.assertEqual(select_model(None, stems)[0], "htdemucs_6s.yaml")

    def test_only_the_karaoke_pair_uses_the_mdx_model(self):
        self.assertEqual(select_model(None, ["vocals", "instrumental"])[0],
                         "UVR_MDXNET_KARA_2.onnx")
        self.assertEqual(select_model(None, ["vocals"])[0], "UVR_MDXNET_KARA_2.onnx")

    def test_no_plan_still_runs_the_six_stem_model(self):
        self.assertEqual(select_model(None, None)[0], "htdemucs_6s.yaml")

    def test_the_four_stem_model_is_only_used_when_explicitly_asked_for(self):
        self.assertEqual(select_model("htdemucs.yaml", ["vocals", "drums"])[0], "htdemucs.yaml")



class ModelRequestTests(unittest.TestCase):
    def test_quick_selection_keeps_its_shape(self):
        self.assertEqual(model_request(["vocals"], None, False), ["vocals"])

    def test_group_members_are_computed_too(self):
        self.assertEqual(model_request([], ["other", "piano"], False), ["other", "piano"])

    def test_split_forces_the_guitar_in(self):
        self.assertEqual(model_request(["lead", "rhythm"], None, True), ["guitar"])

    def test_leaves_without_a_split_are_rejected(self):
        with self.assertRaises(ValueError):
            model_request(["lead"], None, False)

    def test_a_plan_that_writes_nothing_is_rejected(self):
        with self.assertRaises(ValueError):
            model_request([], [], False)

    def test_no_plan_asks_for_every_model_output(self):
        self.assertIsNone(model_request(None, None, False))


class ResolvePlanTests(unittest.TestCase):
    """An explicit group is the exact content of other.flac; only `--group` alone
    ("keep the rest") needs `other` added as a member."""

    def test_an_explicit_group_is_not_given_extra_members(self):
        # `other` is the destination: the file is still named other.flac, but its
        # content is exactly what the plan folded, with no residual mixed in.
        model, own, grouped = resolve_plan(None, (), ("piano",), False)
        self.assertEqual(grouped, ("piano",))
        self.assertEqual(own, ())
        self.assertEqual(publish_names(model, own, grouped), ("other",))

    def test_an_explicit_empty_group_writes_no_other_file(self):
        model, own, grouped = resolve_plan(None, ("vocals", "drums"), (), False)
        self.assertEqual(grouped, ())
        self.assertEqual(publish_names(model, own, grouped), ("vocals", "drums"))

    def test_group_without_stems_keeps_the_rest_own(self):
        model, own, grouped = resolve_plan(None, None, ("piano",), False)
        self.assertEqual(set(grouped), {"piano", "other"})
        self.assertTrue(own)
        self.assertFalse(set(own) & {"piano", "other"})

    def test_other_folds_the_guitar_and_piano_the_six_stem_model_produced(self):
        # The whole point of dropping the 4-stem fallback: guitar and piano are
        # no longer hidden inside `other` by the model, so the plan folds them in
        # explicitly and `other.flac` still holds "everything left over".
        model, own, grouped = resolve_plan(None, ("vocals", "drums", "other"), None, False)
        self.assertEqual(model, "htdemucs_6s.yaml")
        self.assertEqual(set(grouped), {"other", "bass", "guitar", "piano"})
        self.assertEqual(publish_names(model, own, grouped), ("vocals", "drums", "other"))

    def test_a_kept_guitar_is_not_folded_into_other(self):
        model, own, grouped = resolve_plan(None, ("vocals", "guitar", "other"), None, False)
        self.assertEqual(set(grouped), {"other", "bass", "drums", "piano"})
        self.assertNotIn("guitar", grouped)

    def test_no_plan_leaves_the_quick_path_untouched(self):
        model, own, grouped = resolve_plan(None, None, None, False)
        self.assertIsNone(own)
        self.assertIsNone(grouped)
        self.assertTrue(model)


class LegacyGroupTests(unittest.TestCase):
    def test_legacy_other_folds_the_unselected_in(self):
        self.assertEqual(set(legacy_group("htdemucs.yaml", ("vocals", "other"), None)),
                         {"other", "drums", "bass"})

    def test_an_explicit_group_is_left_alone(self):
        self.assertEqual(legacy_group("htdemucs_6s.yaml", ("vocals",), ("piano",)), ("piano",))

    def test_no_other_means_no_folding(self):
        self.assertIsNone(legacy_group("htdemucs.yaml", ("vocals", "drums"), None))


class PublishTests(unittest.TestCase):
    def test_a_group_member_is_never_published(self):
        self.assertEqual(publish_names("htdemucs_6s.yaml", ("vocals",), ("other", "piano")),
                         ("vocals", "other"))

    def test_a_plan_with_no_own_files_still_writes_other(self):
        self.assertEqual(publish_names("htdemucs_6s.yaml", (), ("other",)), ("other",))

    def test_other_is_not_listed_twice(self):
        self.assertEqual(publish_names("htdemucs_6s.yaml", ("other",), ("other",)), ("other",))


class BuildOtherTests(unittest.TestCase):
    def test_a_lone_other_needs_no_mix(self):
        with tempfile.TemporaryDirectory() as temporary:
            other = Path(temporary) / "other.flac"
            other.write_bytes(b"stub")
            self.assertEqual(_build_other({"other": other}, ["other"]), other)

    def test_a_member_the_run_did_not_produce_is_an_error(self):
        with self.assertRaises(RuntimeError):
            _build_other({"other": Path("other.flac")}, ["piano", "other"])

    def test_no_group_means_no_other_file(self):
        self.assertIsNone(_build_other({}, []))


class ValidateGroupTests(unittest.TestCase):
    def test_none_keeps_the_legacy_behaviour(self):
        self.assertIsNone(validate_group(None))

    def test_unknown_stems_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_group(["kazoo"])

    def test_duplicates_collapse(self):
        self.assertEqual(validate_group(["other", "other"]), ["other"])


class PlanStemsTests(unittest.TestCase):
    """An explicit plan may deliberately keep no own files."""

    def test_a_fully_folded_plan_is_accepted(self):
        self.assertEqual(plan_stems("custom", [], ["other", "vocals"]), [])

    def test_a_plan_that_keeps_and_folds_nothing_is_rejected(self):
        with self.assertRaises(ValueError):
            plan_stems("custom", [], [])

    def test_the_quick_grid_still_needs_a_stem(self):
        with self.assertRaises(ValueError):
            plan_stems("custom", [])

    def test_unknown_stems_are_rejected(self):
        with self.assertRaises(ValueError):
            plan_stems("custom", ["kazoo"], ["other"])

    def test_the_guitar_leaves_are_legal_own_files(self):
        # The dialog puts lead/rhythm in `stems` when the split is on; the quick
        # grid never can, but the plan path must accept them.
        self.assertEqual(plan_stems("custom", ["vocals", "lead", "rhythm"], ["other"]),
                         ["vocals", "lead", "rhythm"])

    def test_the_guitar_leaves_are_legal_group_members(self):
        self.assertEqual(validate_group(["other", "lead", "rhythm"]),
                         ["other", "lead", "rhythm"])

    def test_the_error_names_the_offending_stem(self):
        with self.assertRaises(ValueError) as caught:
            plan_stems("custom", ["kazoo"], ["other"])
        self.assertIn("kazoo", str(caught.exception))


class CommandTests(unittest.TestCase):
    """The CLI must be told about an explicitly empty own-file list."""

    def command(self, stems, group, split_leaves=True):
        library = object.__new__(Library)
        library.cache = Path("/cache")
        return Library._separation_command(
            library, {"kind": "separate"}, Path("/project"), "original.wav",
            Path("/stage"), stems, group, split_leaves, None)

    def test_an_all_grouped_plan_still_sends_stems(self):
        command = self.command([], ["other", "piano"])
        self.assertIn("--stems", command)
        self.assertEqual(command[command.index("--stems") + 1], "--group")

    def test_the_group_is_separate_from_the_own_files(self):
        command = self.command(["vocals"], ["other"])
        self.assertEqual(command[command.index("--stems") + 1], "vocals")
        self.assertEqual(command[command.index("--group") + 1], "other")

    def test_the_split_is_requested_only_when_planned(self):
        self.assertIn("--split-guitar", self.command(["vocals"], ["other"]))
        self.assertNotIn("--split-guitar", self.command(["vocals"], ["other"], False))


class CliPlanTests(unittest.TestCase):
    """The CLI must accept a plan that names the guitar-split outputs."""

    def parse(self, *extra):
        from unweave.cli import parser
        return parser().parse_args(["separate", "--file", "song.wav", *extra])

    def test_leaves_are_accepted_as_own_files(self):
        args = self.parse("--stems", "vocals", "lead", "--group", "other", "--split-guitar")
        self.assertEqual(args.stems, ["vocals", "lead"])
        self.assertTrue(args.split_guitar)

    def test_leaves_are_accepted_as_group_members(self):
        args = self.parse("--stems", "vocals", "--group", "other", "rhythm")
        self.assertEqual(args.group, ["other", "rhythm"])

    def test_an_unknown_stem_is_still_rejected(self):
        with self.assertRaises(SystemExit):
            self.parse("--stems", "kazoo", "--group", "other")


if __name__ == "__main__":
    unittest.main()
