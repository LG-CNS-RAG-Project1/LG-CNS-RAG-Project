from evaluation.answer_eval import FIELDS, JUDGE_PROMPT, ANSWER_PROMPT, prompt_hash


def test_answer_eval_records_prompt_hashes_for_reproducibility():
    assert prompt_hash(ANSWER_PROMPT) == prompt_hash(ANSWER_PROMPT)
    assert len(prompt_hash(JUDGE_PROMPT)) == 64
    assert {"answer_prompt_sha256", "judge_prompt_sha256", "commit"} <= set(FIELDS)
