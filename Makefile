# 자주 쓰는 개발 명령 모음. `make help`로 목록을 확인한다.
.DEFAULT_GOAL := help
COMPOSE := docker compose
RUN_APP := $(COMPOSE) run --rm app
GITHUB_REPOSITORY ?= $(shell git remote get-url origin 2>/dev/null | sed -E 's#.*github\.com[:/]##; s#\.git$$##')

.PHONY: help env up down build shell format format-check test precommit script-test review-preview review-model-check review-codex-login

help: ## 명령 목록 출력
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

env: ## .env.example을 .env로 복사 (이미 있으면 유지)
	@test -f .env && echo ".env가 이미 있습니다." || (cp .env.example .env && echo ".env를 생성했습니다.")

up: ## 개발 컨테이너 실행
	$(COMPOSE) up -d --build

down: ## 개발 컨테이너 종료
	$(COMPOSE) down

build: ## 개발 이미지 다시 빌드
	$(COMPOSE) build app

shell: ## app 컨테이너 셸 접속
	$(COMPOSE) exec app bash

format: ## black으로 Python 코드 포맷 적용
	$(RUN_APP) black .

format-check: ## black 포맷 검사 (CI와 동일)
	$(RUN_APP) black --check --diff .

test: ## pytest 실행 (수집된 테스트가 없으면 CI와 같이 통과 처리)
	$(RUN_APP) sh -c 'python -m pytest; status=$$?; if [ $$status -eq 5 ]; then echo "수집된 테스트가 없습니다."; exit 0; fi; exit $$status'

precommit: ## 모든 파일에 pre-commit 검사 실행
	$(RUN_APP) pre-commit run --all-files

script-test: ## GitHub·Notion 자동화 스크립트 테스트 (Node.js 필요)
	node --test "scripts/**/*.test.mjs"

review-preview: ## PR 분석 미리보기, Notion에 쓰지 않음 (예: make review-preview PR=26 [LLM=true], LLM은 ~/.codex의 ChatGPT 로그인 사용)
	@test -n "$(PR)" || (echo "PR 번호를 지정하세요. 예: make review-preview PR=26" && exit 1)
	DRY_RUN=1 PR_NUMBER=$(PR) CI_WAIT_SECONDS=0 REVIEW_LLM_ENABLED=$(or $(LLM),false) CODEX_HOME="$(or $(CODEX_HOME),$(HOME)/.codex)" \
		GITHUB_TOKEN="$$(gh auth token 2>/dev/null)" \
		REVIEW_PREVIEW_OUT="$${TMPDIR:-/tmp}/review-preview-$(PR).json" node scripts/review/analyze_pr.mjs

review-model-check: ## 분석기(REVIEW_PROVIDER, 기본 codex: ~/.codex의 ChatGPT 로그인 / openai: 셸 환경변수 OPENAI_API_KEY)로 REVIEW_MODEL(기본 gpt-6-luna) 최소 호출 1회, PR·Notion 미사용
	node scripts/review/check_model.mjs

review-codex-login: ## PR 분석 자동화 전용 ChatGPT 로그인을 만들어 Environment pr-analysis의 CODEX_AUTH_JSON에 저장(리더 PC에서 1회, 브라우저 로그인)
	bash scripts/review/seed_codex_auth.sh
