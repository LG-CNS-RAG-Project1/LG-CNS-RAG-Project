"""Command-line interface for readiness checks and sample analyses."""

import argparse
import json
import sys
from pathlib import Path

import src.pipeline as pipeline


def main() -> None:
    """상태를 점검하거나 샘플 아이디어를 분석해 JSON으로 출력한다."""
    parser = argparse.ArgumentParser(description="IdeaLens 통합 분석 흐름")
    sub = parser.add_subparsers(dest="command", required=True)
    status_cmd = sub.add_parser(
        "status", help="키·색인 준비 상태 점검(외부 생성 호출 없음)"
    )
    status_cmd.add_argument("--json", action="store_true", help="JSON으로 출력")
    status_cmd.add_argument("--area", help="특허 분야 ID(예: SF-02)")
    run_cmd = sub.add_parser("run", help="샘플 아이디어로 실분석 실행(API 비용 발생)")
    run_cmd.add_argument(
        "--idea-id", required=True, help="data/samples/ideas.json의 ID"
    )
    run_cmd.add_argument(
        "--area", help="특허 분야 ID(기본: idea-id와 같은 분야가 있으면 그 값)"
    )
    run_cmd.add_argument("--questions", type=Path, help="질문 목록 JSON 파일")
    run_cmd.add_argument("--out", type=Path, help="PipelineReport JSON 저장 경로")
    args = parser.parse_args()

    if args.command == "status":
        readiness = pipeline.check_readiness(args.area)
        if args.json:
            print(readiness.model_dump_json(indent=2))
        else:
            print(f"Chroma: {readiness.chroma}")
            print(
                f"시장 색인: {readiness.market_index.count} ({readiness.market_index.reason or 'ok'})"
            )
            print(
                f"특허 색인: {readiness.patent_index.count} 분야별 {readiness.patent_index.area_counts}"
            )
            print(f"특허 실행 방식: {readiness.patent_mode}")
            for reason in readiness.reasons:
                print(f"- {reason}")
        return

    draft = pipeline.sample_draft(args.idea_id)
    area = args.area or (args.idea_id if args.idea_id in pipeline._area_ids() else None)
    questions = (
        json.loads(args.questions.read_text(encoding="utf-8"))
        if args.questions
        else pipeline.default_questions(draft)
    )
    from src.generation.market_analysis import call_analysis_llm

    report = pipeline.run_pipeline(
        draft,
        questions,
        technology_area_id=area,
        swot_llm_fn=call_analysis_llm,
        canvas_llm_fn=call_analysis_llm,
    )
    print(
        f"[{report.status}] 특허 {report.patent_run.state}({report.patent_run.seconds}s)"
        f" · 시장 {report.market_run.state}({report.market_run.seconds}s)",
        file=sys.stderr,
    )
    payload = report.model_dump_json(indent=2)
    if args.out:
        args.out.write_text(payload, encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
