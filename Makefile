# ==============================================================================
# ApplyPilot Makefile
# Automated Multi-Profile Job Application Pipeline & Dynamic WebUI
# ==============================================================================

SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

# ==============================================================================
# Environment & Toolchain Detection
# ==============================================================================

VENV ?= .venv
BIN  := $(VENV)/bin

# Detect Python interpreter (prefers .venv, falls back to uv or system python3)
PYTHON := $(shell if [ -x "$(BIN)/python" ]; then echo "$(BIN)/python"; elif command -v uv >/dev/null 2>&1; then echo "uv run python3"; else which python3 2>/dev/null || echo "python3"; fi)

# Detect ApplyPilot CLI binary
APPLYPILOT := $(shell if [ -x "$(BIN)/applypilot" ]; then echo "$(BIN)/applypilot"; else which applypilot 2>/dev/null || echo "$(BIN)/applypilot"; fi)

# OS-specific browser launcher
UNAME_S := $(shell uname -s)
ifeq ($(UNAME_S),Darwin)
  BROWSER_OPEN := open
else
  BROWSER_OPEN := xdg-open
endif

# ==============================================================================
# WebUI & Server Settings
# ==============================================================================

PORT ?= 8080
OPEN ?= 0
WEB_DIR := web
WEB_SERVER := $(WEB_DIR)/server.py
WEB_RUN := $(WEB_DIR)/run.sh

# ==============================================================================
# Pipeline Configuration & Defaults
# ==============================================================================

WORKERS ?= 2
MIN_SCORE ?= 7
VALIDATION ?= normal
STAGES ?= discover enrich
DRY_RUN ?= 0
STREAM ?= 0
EXTRA_ARGS ?=
ISOLATE ?= 1

# Isolated directories per profile
GOLANG_DIR ?= $(HOME)/.applypilot/profiles/golang
GAMEDEV_DIR ?= $(HOME)/.applypilot/profiles/gamedev
SHARED_DIR := $(HOME)/.applypilot

# CLI flags builders
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

APPLY_FLAGS := --min-score $(MIN_SCORE) -w $(WORKERS)
ifeq ($(DRY_RUN),1)
  APPLY_FLAGS += --dry-run
endif
ifneq ($(strip $(EXTRA_ARGS)),)
  APPLY_FLAGS += $(EXTRA_ARGS)
endif

# Target directory determination based on ISOLATE flag
ifeq ($(ISOLATE),1)
  GOLANG_TARGET := $(GOLANG_DIR)
  GAMEDEV_TARGET := $(GAMEDEV_DIR)
else
  GOLANG_TARGET := $(SHARED_DIR)
  GAMEDEV_TARGET := $(SHARED_DIR)
endif

# Helper: prepare and activate profile
define prepare_profile
	@mkdir -p "$(1)"
	@APPLYPILOT_DIR="$(1)" ./switch_profile.sh $(2) > /dev/null
	@./switch_profile.sh $(2) > /dev/null
endef

# Terminal Colors & Formatting
BOLD    := \033[1m
DIM     := \033[2m
GREEN   := \033[32m
CYAN    := \033[36m
YELLOW  := \033[33m
MAGENTA := \033[35m
BLUE    := \033[34m
RESET   := \033[0m

# ==============================================================================
# Help Menu
# ==============================================================================

.PHONY: help
help:
	@echo ""
	@echo -e "$(BOLD)$(CYAN)ApplyPilot — Pipeline & WebUI Automation$(RESET)"
	@echo -e "$(DIM)Multi-profile job discovery, LLM scoring, ATS resume tailoring, and autonomous application.$(RESET)"
	@echo ""
	@echo -e "$(BOLD)$(YELLOW)🌟 WEB UI & DASHBOARD:$(RESET)"
	@echo -e "  $(GREEN)make web$(RESET)                Start the dynamic WebUI server (http://localhost:$(PORT))"
	@echo -e "  $(GREEN)make web-open$(RESET)           Start WebUI and open browser automatically"
	@echo -e "  $(CYAN)make web-status$(RESET)         Check if WebUI server is currently running"
	@echo -e "  $(YELLOW)make web-restart$(RESET)        Restart the WebUI server process"
	@echo -e "  $(MAGENTA)make web-stop$(RESET)           Stop all running WebUI server instances"
	@echo -e "  $(CYAN)make dashboard$(RESET)          Alias for starting & opening the dynamic WebUI"
	@echo ""
	@echo -e "$(BOLD)$(YELLOW)🚀 PRIMARY SEARCH & PIPELINE TARGETS:$(RESET)"
	@echo -e "  $(GREEN)make search-all$(RESET)          Run job searches for Golang, then GameDev sequentially"
	@echo -e "  $(GREEN)make search-golang$(RESET)       Run job search (discover + enrich) for Golang Backend"
	@echo -e "  $(GREEN)make search-gamedev$(RESET)      Run job search (discover + enrich) for Game Development"
	@echo -e "  $(GREEN)make run-golang$(RESET)          Run entire 6-stage pipeline for Golang"
	@echo -e "  $(GREEN)make run-gamedev$(RESET)         Run entire 6-stage pipeline for GameDev"
	@echo -e "  $(GREEN)make auto-apply-golang$(RESET)  Tailor resumes & auto-apply Golang roles"
	@echo -e "  $(GREEN)make auto-apply-gamedev$(RESET) Tailor resumes & auto-apply GameDev roles"
	@echo ""
	@echo -e "$(BOLD)$(YELLOW)⚙️  PROFILE SWITCHING & STATUS:$(RESET)"
	@echo -e "  $(MAGENTA)make switch-golang$(RESET)      Activate Golang profile in ~/.applypilot"
	@echo -e "  $(MAGENTA)make switch-gamedev$(RESET)     Activate GameDev profile in ~/.applypilot"
	@echo -e "  $(MAGENTA)make switch-status$(RESET)      Show currently active profile name"
	@echo -e "  $(CYAN)make status$(RESET)             Show status of current active profile"
	@echo -e "  $(CYAN)make status-golang$(RESET)      Show DB stats & metrics for Golang profile"
	@echo -e "  $(CYAN)make status-gamedev$(RESET)     Show DB stats & metrics for GameDev profile"
	@echo ""
	@echo -e "$(BOLD)$(YELLOW)🔍 INDIVIDUAL STAGES (Golang | GameDev):$(RESET)"
	@echo -e "  $(CYAN)make discover-golang$(RESET)  |  $(CYAN)make discover-gamedev$(RESET)   Scrape 5+ job boards"
	@echo -e "  $(CYAN)make enrich-golang$(RESET)    |  $(CYAN)make enrich-gamedev$(RESET)     Fetch full job descriptions"
	@echo -e "  $(CYAN)make score-golang$(RESET)     |  $(CYAN)make score-gamedev$(RESET)      Score fit with LLM"
	@echo -e "  $(CYAN)make tailor-golang$(RESET)    |  $(CYAN)make tailor-gamedev$(RESET)     Tailor ATS resumes"
	@echo -e "  $(CYAN)make cover-golang$(RESET)     |  $(CYAN)make cover-gamedev$(RESET)      Generate cover letters"
	@echo -e "  $(CYAN)make apply-golang$(RESET)     |  $(CYAN)make apply-gamedev$(RESET)      Launch autonomous browser"
	@echo ""
	@echo -e "$(BOLD)$(YELLOW)🛠️  SETUP & UTILITIES:$(RESET)"
	@echo -e "  $(BOLD)make setup$(RESET)               Create virtualenv & install dependencies"
	@echo -e "  $(BOLD)make doctor$(RESET)              Diagnose system requirements and API keys"
	@echo -e "  $(BOLD)make clean$(RESET)               Clean Python cache files and build artifacts"
	@echo ""
	@echo -e "$(BOLD)$(YELLOW)CONFIGURATION FLAGS (override on command line):$(RESET)"
	@echo -e "  PORT=N              WebUI server port (default: 8080)"
	@echo -e "  OPEN=1              Auto-open browser on WebUI start (default: 0)"
	@echo -e "  WORKERS=N           Parallel worker threads (default: 2)"
	@echo -e "  MIN_SCORE=N         Minimum fit score (default: 7)"
	@echo -e "  DRY_RUN=1           Simulate actions without writing/submitting (default: 0)"
	@echo -e "  STREAM=1            Stream stages concurrently (default: 0)"
	@echo -e "  ISOLATE=1           Keep databases isolated per profile (default: 1)"
	@echo ""
	@echo -e "$(BOLD)Examples:$(RESET)"
	@echo -e "  make web PORT=8080              # Start dynamic WebUI on port 8080"
	@echo -e "  make web-open                   # Start WebUI & automatically open browser"
	@echo -e "  make search-golang WORKERS=4    # Run search with 4 workers"
	@echo -e "  make run-golang MIN_SCORE=8     # Run full pipeline for score >= 8"
	@echo ""

# ==============================================================================
# Web UI & Server Commands
# ==============================================================================

.PHONY: web webui ui start web-open web-stop web-status web-restart dashboard dashboard-html

web webui ui start:
	@PID=$$(lsof -ti :$(PORT) 2>/dev/null || true); \
	if [ -n "$$PID" ]; then \
		echo -e "$(YELLOW)⚠️  Port $(PORT) is currently in use by PID: $$PID$(RESET)"; \
		echo -e "   Run $(BOLD)make web-stop$(RESET) to kill it, or choose another port: $(BOLD)make web PORT=8081$(RESET)\n"; \
		exit 1; \
	fi
ifeq ($(OPEN),1)
	@(sleep 1 && $(BROWSER_OPEN) "http://localhost:$(PORT)" >/dev/null 2>&1 || true) &
endif
	@echo -e "$(BOLD)$(CYAN)================================================================$(RESET)"
	@echo -e "$(BOLD)$(GREEN)🚀 Starting ApplyPilot Dynamic WebUI & Automation Server$(RESET)"
	@echo -e "   $(BOLD)Local URL:$(RESET)   $(CYAN)http://localhost:$(PORT)$(RESET)"
	@echo -e "   $(BOLD)Features:$(RESET)    Multi-Profile CRUD, AI Tailoring, Live Auto-Apply"
	@echo -e "   $(BOLD)Shutdown:$(RESET)    Press $(YELLOW)Ctrl+C$(RESET) to stop"
	@echo -e "$(BOLD)$(CYAN)================================================================$(RESET)"
	@PORT="$(PORT)" $(PYTHON) $(WEB_SERVER)

web-open:
	@$(MAKE) web OPEN=1 PORT=$(PORT)

web-stop:
	@echo -e "$(YELLOW)Stopping running ApplyPilot WebUI servers...$(RESET)"
	@PIDS=$$(pgrep -f "web/server.py" 2>/dev/null || true); \
	if [ -n "$$PIDS" ]; then \
		echo -e "Terminating WebUI PID(s): $$PIDS"; \
		kill -15 $$PIDS 2>/dev/null || kill -9 $$PIDS 2>/dev/null || true; \
		echo -e "$(GREEN)✅ WebUI server stopped.$(RESET)"; \
	else \
		echo "No running WebUI server found."; \
	fi

web-status:
	@PIDS=$$(pgrep -f "web/server.py" 2>/dev/null || true); \
	if [ -n "$$PIDS" ]; then \
		echo -e "$(GREEN)✅ ApplyPilot WebUI is RUNNING$(RESET)"; \
		echo -e "   PID(s): $$PIDS"; \
		lsof -iTCP -sTCP:LISTEN -n -P 2>/dev/null | grep -E "($$(echo $$PIDS | tr ' ' '|'))" || true; \
	else \
		echo -e "$(YELLOW)ApplyPilot WebUI is NOT running.$(RESET)"; \
	fi

web-restart: web-stop
	@sleep 1
	@$(MAKE) web PORT=$(PORT) OPEN=$(OPEN)

dashboard: web-open

dashboard-html:
	@$(APPLYPILOT) dashboard

# ==============================================================================
# Setup & Health Checks
# ==============================================================================

.PHONY: setup install doctor clean
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

clean:
	@echo "Cleaning temporary files and build artifacts..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f \( -name "*.pyc" -o -name "*.pyo" -o -name ".DS_Store" \) -delete 2>/dev/null || true
	@rm -rf .pytest_cache .ruff_cache build dist *.egg-info 2>/dev/null || true
	@echo -e "$(GREEN)✅ Clean complete.$(RESET)"

# ==============================================================================
# Profile Switching & Activation Helpers
# ==============================================================================

.PHONY: switch-golang switch-go switch-gamedev switch-game switch-status status

switch-golang switch-go:
	@./switch_profile.sh golang

switch-gamedev switch-game:
	@./switch_profile.sh gamedev

switch-status:
	@./switch_profile.sh status

status:
	@$(APPLYPILOT) status

# ==============================================================================
# Pipeline & Search Targets (Golang Backend)
# ==============================================================================

.PHONY: search-golang search-go discover-golang enrich-golang score-golang \
        tailor-golang cover-golang pipeline-golang run-golang apply-golang \
        auto-apply-golang status-golang dashboard-golang

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
	@$(MAKE) web OPEN=1

# ==============================================================================
# Pipeline & Search Targets (Game Development)
# ==============================================================================

.PHONY: search-gamedev search-game discover-gamedev enrich-gamedev score-gamedev \
        tailor-gamedev cover-gamedev pipeline-gamedev run-gamedev apply-gamedev \
        auto-apply-gamedev status-gamedev dashboard-gamedev

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
	@$(MAKE) web OPEN=1

# ==============================================================================
# Combined Multi-Profile Targets
# ==============================================================================

.PHONY: search-all
search-all:
	@echo -e "$(BOLD)$(MAGENTA)>>> Step 1/2: Searching Golang Backend Roles <<<$(RESET)"
	@$(MAKE) search-golang
	@echo ""
	@echo -e "$(BOLD)$(MAGENTA)>>> Step 2/2: Searching Game Development Roles <<<$(RESET)"
	@$(MAKE) search-gamedev
	@echo -e "$(BOLD)$(GREEN)✅ All job searches completed successfully!$(RESET)"
