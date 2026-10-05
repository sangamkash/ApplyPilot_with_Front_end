# ==============================================================================
# ApplyPilot Makefile
# Multi-Profile Job Search & Pipeline Automation (Golang & GameDev)
# ==============================================================================

SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

# --- Python & Environment Detection ---
VENV ?= .venv
BIN := $(VENV)/bin
APPLYPILOT := $(shell if [ -x "$(BIN)/applypilot" ]; then echo "$(BIN)/applypilot"; else which applypilot 2>/dev/null || echo "$(BIN)/applypilot"; fi)

# --- Configuration & Defaults ---
WORKERS ?= 2
MIN_SCORE ?= 7
VALIDATION ?= normal
STAGES ?= discover enrich
DRY_RUN ?= 0
STREAM ?= 0
EXTRA_ARGS ?=
ISOLATE ?= 1

# Isolated directories (keeps DB, scraped jobs, and resumes independent per profile)
GOLANG_DIR ?= $(HOME)/.applypilot/profiles/golang
GAMEDEV_DIR ?= $(HOME)/.applypilot/profiles/gamedev
SHARED_DIR := $(HOME)/.applypilot

# Build CLI flags
RUN_FLAGS := -w $(WORKERS) --min-score $(MIN_SCORE) --validation $(VALIDATION)
ifeq ($(DRY_RUN),1)
RUN_FLAGS += --dry-run
endif
ifeq ($(STREAM),1)
RUN_FLAGS += --stream
endif
ifneq ($(strip $(EXTRA_ARGS)),)
RUN_FLAGS += $(EXTRA_ARGS)
endif

# Build Apply CLI flags
APPLY_FLAGS := --min-score $(MIN_SCORE) -w $(WORKERS)
ifeq ($(DRY_RUN),1)
APPLY_FLAGS += --dry-run
endif
ifneq ($(strip $(EXTRA_ARGS)),)
APPLY_FLAGS += $(EXTRA_ARGS)
endif


# Colors for terminal output
BOLD := \033[1m
GREEN := \033[32m
CYAN := \033[36m
YELLOW := \033[33m
MAGENTA := \033[35m
RESET := \033[0m

# ==============================================================================
# Help Menu
# ==============================================================================

.PHONY: help
help:
	@echo ""
	@echo -e "$(BOLD)$(CYAN)ApplyPilot Job Search Makefile$(RESET)"
	@echo -e "Automate job searches and application pipelines for $(BOLD)Golang$(RESET) and $(BOLD)GameDev$(RESET) separately."
	@echo ""
	@echo -e "$(BOLD)$(YELLOW)PRIMARY SEARCH TARGETS:$(RESET)"
	@echo -e "  $(GREEN)make search-golang$(RESET)       Run job search (discover + enrich) for Golang Backend"
	@echo -e "  $(GREEN)make search-gamedev$(RESET)      Run job search (discover + enrich) for Game Development"
	@echo -e "  $(GREEN)make search-all$(RESET)          Run job searches for Golang, then GameDev sequentially"
	@echo ""
	@echo -e "$(BOLD)$(YELLOW)FULL PIPELINE (Discover -> Enrich -> Score -> Tailor -> Cover -> PDF):$(RESET)"
	@echo -e "  $(GREEN)make run-golang$(RESET)          Run entire 6-stage pipeline for Golang"
	@echo -e "  $(GREEN)make run-gamedev$(RESET)         Run entire 6-stage pipeline for GameDev"
	@echo ""
	@echo -e "$(BOLD)$(YELLOW)INDIVIDUAL STAGES (Golang):$(RESET)"
	@echo -e "  $(CYAN)make discover-golang$(RESET)    Discover Golang jobs across 5+ boards & portals"
	@echo -e "  $(CYAN)make enrich-golang$(RESET)      Enrich discovered Golang jobs with full descriptions"
	@echo -e "  $(CYAN)make score-golang$(RESET)       Score Golang jobs using LLM against Golang profile"
	@echo -e "  $(CYAN)make tailor-golang$(RESET)      Generate tailored resumes for high-fit Golang jobs"
	@echo -e "  $(CYAN)make cover-golang$(RESET)       Generate targeted cover letters for Golang jobs"
	@echo -e "  $(CYAN)make apply-golang$(RESET)       Launch autonomous browser application submission"
	@echo -e "  $(GREEN)make auto-apply-golang$(RESET)  Tailor resumes & auto-apply in one step (supports MIN_SCORE=N)"
	@echo ""
	@echo -e "$(BOLD)$(YELLOW)INDIVIDUAL STAGES (GameDev):$(RESET)"
	@echo -e "  $(CYAN)make discover-gamedev$(RESET)   Discover GameDev jobs across 5+ boards & portals"
	@echo -e "  $(CYAN)make enrich-gamedev$(RESET)     Enrich discovered GameDev jobs with full descriptions"
	@echo -e "  $(CYAN)make score-gamedev$(RESET)      Score GameDev jobs using LLM against GameDev profile"
	@echo -e "  $(CYAN)make tailor-gamedev$(RESET)     Generate tailored resumes for high-fit GameDev jobs"
	@echo -e "  $(CYAN)make cover-gamedev$(RESET)      Generate targeted cover letters for GameDev jobs"
	@echo -e "  $(CYAN)make apply-gamedev$(RESET)      Launch autonomous browser application submission"
	@echo -e "  $(GREEN)make auto-apply-gamedev$(RESET) Tailor resumes & auto-apply in one step (supports MIN_SCORE=N)"
	@echo ""
	@echo -e "$(BOLD)$(YELLOW)PROFILE SWITCHING & STATUS:$(RESET)"
	@echo -e "  $(MAGENTA)make switch-golang$(RESET)      Activate Golang profile in ~/.applypilot"
	@echo -e "  $(MAGENTA)make switch-gamedev$(RESET)     Activate GameDev profile in ~/.applypilot"
	@echo -e "  $(MAGENTA)make switch-status$(RESET)      Show currently active profile in ~/.applypilot"
	@echo -e "  $(MAGENTA)make status-golang$(RESET)      Show DB stats & metrics for Golang profile"
	@echo -e "  $(MAGENTA)make status-gamedev$(RESET)     Show DB stats & metrics for GameDev profile"
	@echo -e "  $(MAGENTA)make dashboard-golang$(RESET)   Open interactive web dashboard for Golang"
	@echo -e "  $(MAGENTA)make dashboard-gamedev$(RESET)  Open interactive web dashboard for GameDev"
	@echo ""
	@echo -e "$(BOLD)$(YELLOW)SETUP & UTILITIES:$(RESET)"
	@echo -e "  $(BOLD)make setup$(RESET)               Set up .venv and install all dependencies (jobspy, curl_cffi)"
	@echo -e "  $(BOLD)make doctor$(RESET)              Diagnose system requirements and API keys"
	@echo ""
	@echo -e "$(BOLD)$(YELLOW)CONFIGURATION FLAGS (override on command line):$(RESET)"
	@echo -e "  WORKERS=N           Number of parallel worker threads (default: 2)"
	@echo -e "  STAGES=\"...\"        Stages to run (default: \"discover enrich\")"
	@echo -e "  DRY_RUN=1           Preview actions without writing/scraping (default: 0)"
	@echo -e "  STREAM=1            Stream stages concurrently (default: 0)"
	@echo -e "  MIN_SCORE=N         Minimum fit score for scoring/tailoring (default: 7)"
	@echo -e "  ISOLATE=1           Keep databases isolated per profile in ~/.applypilot/profiles/ (default: 1)"
	@echo ""
	@echo -e "$(BOLD)Examples:$(RESET)"
	@echo -e "  make search-golang DRY_RUN=1"
	@echo -e "  make search-gamedev WORKERS=4"
	@echo -e "  make run-golang MIN_SCORE=8"
	@echo ""

# ==============================================================================
# Setup & Health Checks
# ==============================================================================

.PHONY: setup install doctor
setup: install
install:
	@echo -e "$(BOLD)$(CYAN)Setting up ApplyPilot environment...$(RESET)"
	@if command -v uv >/dev/null 2>&1; then \
		echo "Found uv, syncing environment..."; \
		uv venv $(VENV); \
		uv pip install -e .; \
		uv pip install --no-deps python-jobspy; \
		uv pip install pydantic tls-client requests markdownify regex curl_cffi; \
	else \
		echo "uv not found, using python3 -m venv..."; \
		python3 -m venv $(VENV); \
		$(BIN)/pip install -e .; \
		$(BIN)/pip install --no-deps python-jobspy; \
		$(BIN)/pip install pydantic tls-client requests markdownify regex curl_cffi; \
	fi
	@echo -e "$(GREEN)✅ Setup complete. Binary available at: $(APPLYPILOT)$(RESET)"

doctor:
	@$(APPLYPILOT) doctor

# ==============================================================================
# Profile Switching & Activation Helpers
# ==============================================================================

.PHONY: switch-golang switch-go switch-gamedev switch-game switch-status
switch-golang switch-go:
	@./switch_profile.sh golang

switch-gamedev switch-game:
	@./switch_profile.sh gamedev

switch-status:
	@./switch_profile.sh status

# Target directory determination based on ISOLATE flag
ifeq ($(ISOLATE),1)
GOLANG_TARGET := $(GOLANG_DIR)
GAMEDEV_TARGET := $(GAMEDEV_DIR)
else
GOLANG_TARGET := $(SHARED_DIR)
GAMEDEV_TARGET := $(SHARED_DIR)
endif

# Ensure profile directory is initialized and in sync
define prepare_profile
	@mkdir -p "$(1)"
	@APPLYPILOT_DIR="$(1)" ./switch_profile.sh $(2) > /dev/null
	@./switch_profile.sh $(2) > /dev/null
endef

# ==============================================================================
# Job Search Targets (Golang)
# ==============================================================================

.PHONY: search-golang search-go discover-golang enrich-golang score-golang tailor-golang cover-golang pipeline-golang run-golang apply-golang auto-apply-golang status-golang dashboard-golang

search-golang search-go:
	@echo -e "$(BOLD)$(GREEN)=== Running Job Search: Golang Backend ===$(RESET)"
	$(call prepare_profile,$(GOLANG_TARGET),golang)
	APPLYPILOT_DIR="$(GOLANG_TARGET)" $(APPLYPILOT) run $(STAGES) $(RUN_FLAGS)

discover-golang:
	@echo -e "$(BOLD)$(GREEN)=== Discovering Jobs: Golang Backend ===$(RESET)"
	$(call prepare_profile,$(GOLANG_TARGET),golang)
	APPLYPILOT_DIR="$(GOLANG_TARGET)" $(APPLYPILOT) run discover $(RUN_FLAGS)

enrich-golang:
	@echo -e "$(BOLD)$(GREEN)=== Enriching Descriptions: Golang Backend ===$(RESET)"
	$(call prepare_profile,$(GOLANG_TARGET),golang)
	APPLYPILOT_DIR="$(GOLANG_TARGET)" $(APPLYPILOT) run enrich $(RUN_FLAGS)

score-golang:
	@echo -e "$(BOLD)$(GREEN)=== Scoring Jobs (LLM): Golang Backend ===$(RESET)"
	$(call prepare_profile,$(GOLANG_TARGET),golang)
	APPLYPILOT_DIR="$(GOLANG_TARGET)" $(APPLYPILOT) run score $(RUN_FLAGS)

tailor-golang:
	@echo -e "$(BOLD)$(GREEN)=== Tailoring Resumes: Golang Backend ===$(RESET)"
	$(call prepare_profile,$(GOLANG_TARGET),golang)
	APPLYPILOT_DIR="$(GOLANG_TARGET)" $(APPLYPILOT) run tailor $(RUN_FLAGS)

cover-golang:
	@echo -e "$(BOLD)$(GREEN)=== Generating Cover Letters: Golang Backend ===$(RESET)"
	$(call prepare_profile,$(GOLANG_TARGET),golang)
	APPLYPILOT_DIR="$(GOLANG_TARGET)" $(APPLYPILOT) run cover $(RUN_FLAGS)

pipeline-golang run-golang:
	@echo -e "$(BOLD)$(GREEN)=== Running Full Pipeline: Golang Backend ===$(RESET)"
	$(call prepare_profile,$(GOLANG_TARGET),golang)
	APPLYPILOT_DIR="$(GOLANG_TARGET)" $(APPLYPILOT) run all $(RUN_FLAGS)

apply-golang:
	@echo -e "$(BOLD)$(GREEN)=== Launching Auto-Apply: Golang Backend ===$(RESET)"
	$(call prepare_profile,$(GOLANG_TARGET),golang)
	APPLYPILOT_DIR="$(GOLANG_TARGET)" $(APPLYPILOT) apply $(APPLY_FLAGS)

auto-apply-golang:
	@echo -e "$(BOLD)$(GREEN)=== Tailoring & Auto-Applying: Golang Backend (min score: $(MIN_SCORE)) ===$(RESET)"
	@$(MAKE) tailor-golang MIN_SCORE=$(MIN_SCORE)
	@$(MAKE) apply-golang MIN_SCORE=$(MIN_SCORE)

status-golang:
	$(call prepare_profile,$(GOLANG_TARGET),golang)
	@echo -e "$(BOLD)$(CYAN)Pipeline Status: Golang Profile ($(GOLANG_TARGET))$(RESET)"
	@APPLYPILOT_DIR="$(GOLANG_TARGET)" $(APPLYPILOT) status

dashboard-golang:
	$(call prepare_profile,$(GOLANG_TARGET),golang)
	@echo -e "$(BOLD)$(CYAN)Opening Dashboard: Golang Profile ($(GOLANG_TARGET))$(RESET)"
	@APPLYPILOT_DIR="$(GOLANG_TARGET)" $(APPLYPILOT) dashboard

# ==============================================================================
# Job Search Targets (GameDev)
# ==============================================================================

.PHONY: search-gamedev search-game discover-gamedev enrich-gamedev score-gamedev tailor-gamedev cover-gamedev pipeline-gamedev run-gamedev apply-gamedev auto-apply-gamedev status-gamedev dashboard-gamedev

search-gamedev search-game:
	@echo -e "$(BOLD)$(CYAN)=== Running Job Search: Game Development ===$(RESET)"
	$(call prepare_profile,$(GAMEDEV_TARGET),gamedev)
	APPLYPILOT_DIR="$(GAMEDEV_TARGET)" $(APPLYPILOT) run $(STAGES) $(RUN_FLAGS)

discover-gamedev:
	@echo -e "$(BOLD)$(CYAN)=== Discovering Jobs: Game Development ===$(RESET)"
	$(call prepare_profile,$(GAMEDEV_TARGET),gamedev)
	APPLYPILOT_DIR="$(GAMEDEV_TARGET)" $(APPLYPILOT) run discover $(RUN_FLAGS)

enrich-gamedev:
	@echo -e "$(BOLD)$(CYAN)=== Enriching Descriptions: Game Development ===$(RESET)"
	$(call prepare_profile,$(GAMEDEV_TARGET),gamedev)
	APPLYPILOT_DIR="$(GAMEDEV_TARGET)" $(APPLYPILOT) run enrich $(RUN_FLAGS)

score-gamedev:
	@echo -e "$(BOLD)$(CYAN)=== Scoring Jobs (LLM): Game Development ===$(RESET)"
	$(call prepare_profile,$(GAMEDEV_TARGET),gamedev)
	APPLYPILOT_DIR="$(GAMEDEV_TARGET)" $(APPLYPILOT) run score $(RUN_FLAGS)

tailor-gamedev:
	@echo -e "$(BOLD)$(CYAN)=== Tailoring Resumes: Game Development ===$(RESET)"
	$(call prepare_profile,$(GAMEDEV_TARGET),gamedev)
	APPLYPILOT_DIR="$(GAMEDEV_TARGET)" $(APPLYPILOT) run tailor $(RUN_FLAGS)

cover-gamedev:
	@echo -e "$(BOLD)$(CYAN)=== Generating Cover Letters: Game Development ===$(RESET)"
	$(call prepare_profile,$(GAMEDEV_TARGET),gamedev)
	APPLYPILOT_DIR="$(GAMEDEV_TARGET)" $(APPLYPILOT) run cover $(RUN_FLAGS)

pipeline-gamedev run-gamedev:
	@echo -e "$(BOLD)$(CYAN)=== Running Full Pipeline: Game Development ===$(RESET)"
	$(call prepare_profile,$(GAMEDEV_TARGET),gamedev)
	APPLYPILOT_DIR="$(GAMEDEV_TARGET)" $(APPLYPILOT) run all $(RUN_FLAGS)

apply-gamedev:
	@echo -e "$(BOLD)$(CYAN)=== Launching Auto-Apply: Game Development ===$(RESET)"
	$(call prepare_profile,$(GAMEDEV_TARGET),gamedev)
	APPLYPILOT_DIR="$(GAMEDEV_TARGET)" $(APPLYPILOT) apply $(APPLY_FLAGS)

auto-apply-gamedev:
	@echo -e "$(BOLD)$(CYAN)=== Tailoring & Auto-Applying: Game Development (min score: $(MIN_SCORE)) ===$(RESET)"
	@$(MAKE) tailor-gamedev MIN_SCORE=$(MIN_SCORE)
	@$(MAKE) apply-gamedev MIN_SCORE=$(MIN_SCORE)

status-gamedev:
	$(call prepare_profile,$(GAMEDEV_TARGET),gamedev)
	@echo -e "$(BOLD)$(CYAN)Pipeline Status: GameDev Profile ($(GAMEDEV_TARGET))$(RESET)"
	@APPLYPILOT_DIR="$(GAMEDEV_TARGET)" $(APPLYPILOT) status

dashboard-gamedev:
	$(call prepare_profile,$(GAMEDEV_TARGET),gamedev)
	@echo -e "$(BOLD)$(CYAN)Opening Dashboard: GameDev Profile ($(GAMEDEV_TARGET))$(RESET)"
	@APPLYPILOT_DIR="$(GAMEDEV_TARGET)" $(APPLYPILOT) dashboard

# ==============================================================================
# Combined Targets
# ==============================================================================

.PHONY: search-all status dashboard clean

search-all:
	@echo -e "$(BOLD)$(MAGENTA)>>> Step 1/2: Searching Golang Backend Roles <<<$(RESET)"
	@$(MAKE) search-golang
	@echo ""
	@echo -e "$(BOLD)$(MAGENTA)>>> Step 2/2: Searching Game Development Roles <<<$(RESET)"
	@$(MAKE) search-gamedev
	@echo -e "$(BOLD)$(GREEN)✅ All job searches completed successfully!$(RESET)"

status:
	@$(APPLYPILOT) status

dashboard:
	@$(APPLYPILOT) dashboard

clean:
	@echo "Cleaning temporary files and build artifacts..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "Done."
