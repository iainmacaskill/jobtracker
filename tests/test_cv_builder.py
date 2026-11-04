import pytest
from docx import Document

import config
import cv_builder

EXAMPLE = config.PROJECT_ROOT / "profile.example.json"


def test_generate_cv_from_example_profile(tmp_path):
    cv = cv_builder.generate_cv(
        {"title": "Senior Delivery Manager"}, profile_path=EXAMPLE, out_dir=tmp_path
    )
    assert cv.exists()
    assert cv.suffix == ".docx"

    doc = Document(str(cv))
    # The title line (2nd paragraph) should echo the role title.
    assert doc.paragraphs[1].text == "Senior Delivery Manager"


def test_missing_profile_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        cv_builder.generate_cv(
            {"title": "X"}, profile_path=tmp_path / "nope.json", out_dir=tmp_path
        )


@pytest.mark.parametrize(
    ("role", "sector"),
    [
        ({"title": "Programme Manager - Financial Crime"}, "fs"),
        ({"title": "AI Governance Lead"}, "ai"),
        ({"title": "Insurance Transformation Director"}, "fs"),
        ({"title": "Delivery Lead", "fit_notes": "public sector / government programme"}, "public"),
        ({"title": "Office Manager"}, "default"),
    ],
)
def test_detect_sector(role, sector):
    assert cv_builder.detect_sector(role) == sector


PROFILE = {
    "profiles": {"default": "D", "fs": "FS-summary", "ai": "AI-summary"},
    "leadCompetencies": {"fs": ["FS lead"], "ai": ["AI lead"]},
    "competencies": ["General one", "General two"],
}


def test_resolve_profile_leads_with_sector():
    text, comps = cv_builder.resolve_profile(PROFILE, "fs")
    assert text == "FS-summary"
    assert comps[0] == "FS lead"  # sector competency promoted to the front


def test_resolve_profile_default_uses_base_competencies():
    text, comps = cv_builder.resolve_profile(PROFILE, "default")
    assert text == "D"
    assert comps[0] == "General one"


def test_empty_sections_are_left_out(tmp_path):
    from docx import Document as _Doc

    path = cv_builder.write_cv(
        tmp_path / "cv.docx", name="Ada", title_line="BA", contact="", summary="S.",
        competencies=["X"], jobs=[], achievements=[], certifications="", education="BSc",
    )
    texts = [p.text for p in _Doc(str(path)).paragraphs]
    assert "KEY ACHIEVEMENTS" not in texts  # headings are upper-cased
    assert "CERTIFICATIONS & EDUCATION" in texts and "BSc" in texts
