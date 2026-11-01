"""Select cited patent claims within the comparison context budget."""

from src.schemas import PatentClaim


def _select_claims(idea, claims: list, limit: int = 5) -> list:
    """관련 청구항과 그 상위항을 한 묶음으로 선택한다."""
    from src.retrieval.engine import tokenize

    idea_text = " ".join(idea.technical_components or [idea.technology, idea.problem])
    terms = set(tokenize(idea_text))
    claims_by_number = {claim.claim_number: claim for claim in claims}
    ranked = sorted(
        claims,
        key=lambda claim: (
            len(terms & set(tokenize(claim.text))),
            claim.claim_type == "independent",
            -claim.claim_number,
        ),
        reverse=True,
    )
    selected = []
    selected_numbers = set()
    for claim in ranked:
        if claim.claim_number in selected_numbers:
            continue
        ancestors = []
        pending = list(claim.depends_on)
        visited = set()
        missing_parent = False
        while pending:
            number = pending.pop()
            if number in visited or number in selected_numbers:
                continue
            visited.add(number)
            parent = claims_by_number.get(number)
            if not parent:
                missing_parent = True
                break
            ancestors.append(parent)
            pending.extend(parent.depends_on)
        # 부모 원문이 빠져 있어도 인용 자체는 보존한다. 호출부가 미확인 경고를 붙이고,
        # 비교기는 상위항 범위를 추정하지 않도록 프롬프트에서 제한한다.
        additions = sorted(ancestors, key=lambda item: item.claim_number) + [claim]
        additions = [
            item for item in additions if item.claim_number not in selected_numbers
        ]
        if len(selected) + len(additions) <= limit:
            selected.extend(additions)
            selected_numbers.update(item.claim_number for item in additions)
    return sorted(selected, key=lambda claim: claim.claim_number)


def _estimate_text_tokens(text: str) -> int:
    """특허 근거 문맥을 위한 보수적인 토큰 수 근사치를 계산한다.

    한국어·영어가 섞인 원문에서 문자 길이만으로 예산을 과소평가하지 않도록
    공백 단위 토큰과 문자 길이 기반 상한 중 큰 값을 사용한다.
    """
    normalized = " ".join(text.split())
    if not normalized:
        return 0
    return max(len(normalized.split()), (len(normalized) + 2) // 3)


def _build_patent_context(
    idea, claims: list, *, max_tokens: int = 1800, max_claims: int = 5
) -> tuple[list[PatentClaim], int, list[str]]:
    """청구항 원문과 상위항 문맥을 예산 내에서 선택한다.

    토큰 추정에는 검색 계획·아이디어·서식 오버헤드를 포함하지 않으므로,
    호출부는 반환된 사용량을 전체 요청 한도로 간주하지 않아야 한다.
    """
    selected = _select_claims(idea, claims, limit=max_claims)
    selected_numbers = {claim.claim_number for claim in selected}
    claim_map = {claim.claim_number: claim for claim in claims}
    notes = []

    def cost(claim: PatentClaim) -> int:
        """청구항 텍스트 토큰 수를 예산 산정용으로 추정한다."""
        return _estimate_text_tokens(claim.text)

    while selected and sum(cost(claim) for claim in selected) > max_tokens:
        removable = [
            claim
            for claim in selected
            if claim.claim_type == "dependent"
            and not any(claim.claim_number in other.depends_on for other in selected)
        ]
        if removable:
            selected.remove(max(removable, key=cost))
            selected_numbers = {claim.claim_number for claim in selected}
            continue

        # 독립항은 잘라 인용하지 않고, 원문 전체가 예산에 들지 않으면 보류한다.
        independent = next(
            (claim for claim in selected if claim.claim_type == "independent"), None
        )
        if independent:
            selected.remove(independent)
            selected_numbers = {claim.claim_number for claim in selected}
            notes.append(
                f"청구항 {independent.claim_number} 원문이 문맥 토큰 예산을 초과해 제외됨"
            )
            # 빠진 독립항에 의존하는 종속항도 함께 제외해 문맥이 잘리지 않게 한다.
            changed = True
            while changed:
                changed = False
                for claim in list(selected):
                    if any(
                        parent not in selected_numbers for parent in claim.depends_on
                    ):
                        selected.remove(claim)
                        selected_numbers.remove(claim.claim_number)
                        notes.append(
                            f"청구항 {claim.claim_number} 상위항 문맥이 제외되어 함께 제외됨"
                        )
                        changed = True
            continue

        # 남은 종속항 집합이 상위항 관계를 모두 포함하지 않으면 추가 비교에 쓰지 않는다.
        claim = max(selected, key=cost)
        selected.remove(claim)
        selected_numbers.remove(claim.claim_number)
        notes.append(
            f"청구항 {claim.claim_number} 원문이 문맥 토큰 예산을 초과해 제외됨"
        )

    for claim in selected:
        missing = [number for number in claim.depends_on if number not in claim_map]
        if missing:
            notes.append(
                f"청구항 {claim.claim_number} 상위항 {', '.join(map(str, missing))} 원문 미확보"
            )
    return selected, sum(cost(claim) for claim in selected), notes
