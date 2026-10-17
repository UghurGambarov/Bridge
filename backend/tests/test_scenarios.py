"""The scenario suite (SPEC §13) runs inside `make test`: every case must pass, each on a fresh DB."""
import pytest

from app.reports.scenarios import load_cases, run_case

CASES = load_cases()


def test_case_ids_are_unique_and_cover_the_spec():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids))
    expected = {f"N-0{i}" for i in range(1, 8)} | {f"V-{i:02d}" for i in range(1, 11)} | \
               {f"A-{i:02d}" for i in range(1, 19)} | {f"T-0{i}" for i in range(1, 5)}
    assert set(ids) == expected


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_scenario(case, samples_dir):
    result = run_case(case, samples_dir)
    assert result["passed"], f"{case['id']}: {result['failures']} (actual: {result['actual']})"
