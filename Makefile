LOCAL_NODE_PATH := $(CURDIR)/.node/bin

.PHONY: backend-install backend-init backend-seed backend-normalize-information-dates backend-update-prices backend-update-company-context backend-clean-test-data backend-reset-market-data backend-dev llama-serve llama-stop llama-recreate llama-logs llama-command frontend-node frontend-bin-perms frontend-install frontend-dev dev dev-stop test

backend-install:
	python -m venv .venv
	. .venv/bin/activate && pip install -r backend/requirements.txt

backend-init:
	. .venv/bin/activate && python -m backend.app.scripts.init_db

backend-seed:
	. .venv/bin/activate && python -m backend.app.scripts.seed_watchlist

backend-normalize-information-dates:
	. .venv/bin/activate && python -m backend.app.scripts.normalize_information_dates

backend-update-prices:
	. .venv/bin/activate && python -m backend.app.scripts.update_prices --list-name JPX400 --range 1y

backend-update-company-context:
	. .venv/bin/activate && python -m backend.app.scripts.update_company_context --list-name JPX400 --range 1y

backend-clean-test-data:
	. .venv/bin/activate && python -m backend.app.scripts.cleanup_test_data

backend-reset-market-data:
	. .venv/bin/activate && python -m backend.app.scripts.reset_market_data

backend-dev:
	. .venv/bin/activate && uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000

llama-serve:
	./scripts/llama_cpp_docker.py serve

llama-stop:
	./scripts/llama_cpp_docker.py stop

llama-recreate:
	./scripts/llama_cpp_docker.py recreate

llama-logs:
	./scripts/llama_cpp_docker.py logs

llama-command:
	./scripts/llama_cpp_docker.py command

frontend-node:
	./scripts/ensure-node.sh

frontend-bin-perms:
	@if [ -d frontend/node_modules/.bin ]; then find frontend/node_modules/.bin -maxdepth 1 -type f -exec chmod +x {} +; fi

frontend-install: frontend-node
	cd frontend && PATH="$(LOCAL_NODE_PATH):$$PATH" npm install
	$(MAKE) frontend-bin-perms

frontend-dev: frontend-node frontend-bin-perms
	cd frontend && PATH="$(LOCAL_NODE_PATH):$$PATH" npm run dev

dev: frontend-node frontend-bin-perms
	./scripts/dev-all.sh

dev-stop:
	./scripts/dev-stop.sh

test:
	. .venv/bin/activate && python -m unittest discover backend/tests
