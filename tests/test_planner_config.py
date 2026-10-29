"""사업기획 프로필·질문 은행: 모델 고정, 예산 합계, 질문 ID·슬롯 연결."""

import pytest
import yaml

from src.ingestion.patent_processor import load_technology_areas
from src.planner.config import (
    Profile,
    available_profiles,
    load_profile,
    load_question_bank,
    profile_hash,
    profile_path,
    template_slots,
    validate_against_bank,
)


def raw_profile():
    return yaml.safe_load(profile_path("SF-02").read_text("utf-8"))


def test_question_bank_keeps_research_ids_and_links():
    bank = load_question_bank()
    ids = [q.id for q in bank.questions]
    assert len(ids) == 32 and bank.version == "planner-questions-v1"
    assert {"C2", "G3", "E4", "M4"} <= set(ids)
    assert "requires_company_input" in bank.stop_reasons
    assert template_slots("{supplier} {product} 도입 계약") == {"supplier", "product"}


def test_sf02_profile_loads_and_matches_technology_area_taxonomy():
    profile = load_profile("SF-02")
    assert profile.area_id in load_technology_areas()
    assert available_profiles() == ["SF-02"]
    budget = profile.budget
    assert budget.max_articles == 80 and budget.initial_articles == 50
    assert budget.initial_articles + budget.followup_batch * 3 <= 80
    assert [c.id for c in profile.criteria] == [
        "defect_data_preparation",
        "changeover_reconfiguration",
        "site_customization",
    ]
    assert len(profile_hash(profile)) == 64


def test_profile_rejects_other_models_and_budget_overflow():
    raw = raw_profile()
    raw["model"] = "gpt-4o"
    with pytest.raises(ValueError, match="gpt-4o-mini"):
        Profile.model_validate(raw)

    raw = raw_profile()
    raw["budget"]["followup_batch"] = 20
    with pytest.raises(ValueError, match="총량"):
        Profile.model_validate(raw)

    raw = raw_profile()
    raw["initial_allocation"][0]["articles"] = 11
    with pytest.raises(ValueError, match="초기 배분"):
        Profile.model_validate(raw)


def test_profile_question_ids_and_slots_must_exist_in_bank():
    bank = load_question_bank()
    raw = raw_profile()
    raw["question_checks"]["Z9"] = "approved_suppliers"
    with pytest.raises(ValueError, match="Z9"):
        validate_against_bank(Profile.model_validate(raw), bank)

    raw = raw_profile()
    del raw["slots"]["offering"]
    with pytest.raises(ValueError, match="offering"):
        validate_against_bank(Profile.model_validate(raw), bank)


def test_profile_hash_changes_when_lexicon_changes():
    profile = load_profile("SF-02")
    raw = raw_profile()
    raw["criteria"][0]["strong"].append("새 표현")
    assert profile_hash(Profile.model_validate(raw)) != profile_hash(profile)
