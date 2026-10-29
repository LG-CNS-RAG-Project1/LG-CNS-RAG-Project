"""특허 메타데이터에서 색인·관련 후보 기술 동향 통계를 계산한다."""

import re
import threading
import time
from collections import Counter
from datetime import date

from src.schemas import PatentStatisticItem, PatentTrendStatistics

_CACHE_TTL_SECONDS = 300
_CACHE_LOCK = threading.Lock()
_INDEX_CACHE: dict[str, tuple[float, int, PatentTrendStatistics]] = {}


def _values(value) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = re.split(r"[|,;]", str(value or ""))
    return list(
        dict.fromkeys(str(item).strip() for item in values if str(item).strip())
    )


def _applicants(value) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = str(value or "").split("|")
    return list(
        dict.fromkeys(str(item).strip() for item in values if str(item).strip())
    )


def _subclass(value) -> str | None:
    normalized = re.sub(r"\s+", "", str(value or "")).upper()
    match = re.match(r"^([A-H][0-9]{2}[A-Z])", normalized)
    return match.group(1) if match else None


def calculate_patent_statistics(
    records: list[dict], *, scope: str, data_as_of: str | None = None
) -> PatentTrendStatistics:
    """청크 단위 레코드를 고유 특허로 합쳐 분류·연도·출원인 통계를 계산한다."""
    patents = {}
    for record in records:
        metadata = record.get("metadata") or record.get("metadatas") or record
        patent_id = (
            metadata.get("source_id")
            or metadata.get("application_number")
            or metadata.get("patent_id")
        )
        if patent_id:
            patents.setdefault(str(patent_id), metadata)

    ipc_counts, cpc_counts, years, applicants = (
        Counter(),
        Counter(),
        Counter(),
        Counter(),
    )
    ipc_coverage = cpc_coverage = date_coverage = applicant_coverage = 0
    for metadata in patents.values():
        ipc = list(
            dict.fromkeys(
                code
                for value in _values(metadata.get("ipc_codes"))
                if (code := _subclass(value))
            )
        )
        cpc = list(
            dict.fromkeys(
                code
                for value in _values(metadata.get("cpc_codes"))
                if (code := _subclass(value))
            )
        )
        if ipc:
            ipc_coverage += 1
            ipc_counts.update(ipc)
        if cpc:
            cpc_coverage += 1
            cpc_counts.update(cpc)
        application_date = str(metadata.get("application_date") or "")
        year = application_date[:4]
        if year.isdigit() and 1800 <= int(year) <= 2200:
            date_coverage += 1
            years[year] += 1
        patent_applicants = _applicants(metadata.get("applicant"))
        if patent_applicants:
            applicant_coverage += 1
            applicants.update(patent_applicants)

    def items(counter: Counter, limit: int | None = None):
        entries = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
        if limit is not None:
            entries = entries[:limit]
        return [
            PatentStatisticItem(label=label, count=count) for label, count in entries
        ]

    yearly_items = [
        PatentStatisticItem(label=year, count=count)
        for year, count in sorted(years.items())
    ]
    return PatentTrendStatistics(
        scope=scope,
        total_patents=len(patents),
        ipc_coverage=ipc_coverage,
        cpc_coverage=cpc_coverage,
        application_date_coverage=date_coverage,
        applicant_coverage=applicant_coverage,
        ipc_distribution=items(ipc_counts, 10),
        cpc_distribution=items(cpc_counts, 10),
        yearly_applications=yearly_items,
        top_applicants=items(applicants, 10),
        data_as_of=data_as_of or date.today().isoformat(),
    )


def indexed_patent_statistics(collection, *, page_size: int = 1000):
    """색인 컬렉션의 메타데이터를 페이지 단위로 읽고 5분간 결과를 재사용한다."""
    collection_name = str(
        getattr(collection, "id", getattr(collection, "name", "patents"))
    )
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _INDEX_CACHE.get(collection_name)
        if cached and now - cached[0] < _CACHE_TTL_SECONDS:
            return cached[2]

    count = int(collection.count())

    records = []
    offset = 0
    while offset < count:
        batch = collection.get(
            limit=page_size,
            offset=offset,
            include=["metadatas"],
        )
        ids = batch.get("ids") or []
        metadatas = batch.get("metadatas") or []
        if not ids:
            break
        records.extend({"metadata": metadata} for metadata in metadatas if metadata)
        offset += len(ids)
    result = calculate_patent_statistics(records, scope="현재 특허 색인")
    with _CACHE_LOCK:
        _INDEX_CACHE[collection_name] = (time.monotonic(), count, result)
        for key in list(_INDEX_CACHE):
            if (
                key != collection_name
                and time.monotonic() - _INDEX_CACHE[key][0] >= _CACHE_TTL_SECONDS
            ):
                _INDEX_CACHE.pop(key, None)
    return result
