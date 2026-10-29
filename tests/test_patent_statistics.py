from src.analysis.patent_statistics import (
    calculate_patent_statistics,
    indexed_patent_statistics,
)


def test_statistics_deduplicate_patent_chunks_and_report_metadata_coverage():
    result = calculate_patent_statistics(
        [
            {
                "metadata": {
                    "source_id": "P-1",
                    "ipc_codes": ["A01B 1/00", "A01B 3/00", "B25J 9/00"],
                    "cpc_codes": ["A01B 1/00"],
                    "application_date": "2021-04-05",
                    "applicant": "Alpha | Beta",
                }
            },
            {
                "metadata": {
                    "source_id": "P-1",
                    "ipc_codes": ["C02F 1/00"],
                    "application_date": "2021-04-05",
                    "applicant": "Alpha",
                }
            },
            {"metadata": {"source_id": "P-2", "title": "메타데이터 미확보"}},
        ],
        scope="test index",
        data_as_of="2026-10-29",
    )

    assert result.total_patents == 2
    assert result.ipc_coverage == 1
    assert result.cpc_coverage == 1
    assert result.application_date_coverage == 1
    assert result.applicant_coverage == 1
    assert [(item.label, item.count) for item in result.ipc_distribution] == [
        ("A01B", 1),
        ("B25J", 1),
    ]
    assert result.yearly_applications[0].label == "2021"
    assert [(item.label, item.count) for item in result.top_applicants] == [
        ("Alpha", 1),
        ("Beta", 1),
    ]
    assert result.data_as_of == "2026-10-29"


def test_index_statistics_reads_metadata_in_pages_and_caches_by_collection():
    class Collection:
        id = "stats-cache-test"

        def __init__(self):
            self.count_calls = 0
            self.get_calls = []

        def count(self):
            self.count_calls += 1
            return 2

        def get(self, *, limit, offset, include):
            self.get_calls.append((limit, offset, include))
            return {
                "ids": [f"chunk-{offset}"],
                "metadatas": [{"source_id": f"P-{offset}", "ipc_codes": "A01B 1/00"}],
            }

    collection = Collection()
    first = indexed_patent_statistics(collection, page_size=1)
    second = indexed_patent_statistics(collection, page_size=1)

    assert first is second
    assert first.total_patents == 2
    assert collection.count_calls == 1
    assert collection.get_calls == [
        (1, 0, ["metadatas"]),
        (1, 1, ["metadatas"]),
    ]
