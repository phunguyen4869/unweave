"""Stem plan validation shared by the UI job queue and tests."""

CUSTOM_STEMS = ("vocals", "guitar", "bass", "drums", "piano", "other")
# A plan may also name the guitar-split outputs, both as own files and as group
# members; they are produced mid-run by the split, not by the separation model.
PLAN_STEMS = (*CUSTOM_STEMS, "lead", "rhythm")


def selection_stems(preset, stems=None):
    if preset == "vocals":
        return ["vocals", "instrumental"]
    if preset != "custom":
        raise ValueError("Choose vocals/instrumental or custom separation.")
    if not isinstance(stems, list) or not stems:
        raise ValueError("Select at least one instrument.")
    unknown = [stem for stem in stems
               if not isinstance(stem, str) or stem not in CUSTOM_STEMS]
    if unknown:
        raise ValueError(f"Unknown custom stem: {', '.join(map(str, unknown))}.")
    return list(dict.fromkeys(stems))


def validate_group(group):
    """None keeps the legacy `--stems other,…` folding; a list is an explicit plan."""
    if group is None:
        return None
    if not isinstance(group, list):
        raise ValueError("Invalid stem plan.")
    unknown = [name for name in group
               if not isinstance(name, str) or name not in PLAN_STEMS]
    if unknown:
        raise ValueError(f"Unknown stem in the plan: {', '.join(map(str, unknown))}.")
    return list(dict.fromkeys(group))


def plan_stems(preset, stems, group=None):
    """Own files for a job. An explicit plan may keep none of them, as long as
    something is folded; the empty list is then deliberate, not a mistake."""
    if group is None:
        return selection_stems(preset, stems)
    if not isinstance(stems, list):
        raise ValueError("Invalid stem plan.")
    # `lead`/`rhythm` are legal own files: they arrive from the guitar split.
    unknown = [stem for stem in stems
               if not isinstance(stem, str) or stem not in PLAN_STEMS]
    if unknown:
        raise ValueError(f"Unknown stem in the plan: {', '.join(map(str, unknown))}.")
    chosen = list(dict.fromkeys(stems))
    if not chosen and not group:
        raise ValueError("Select at least one instrument.")
    return chosen
