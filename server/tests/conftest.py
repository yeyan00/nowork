from pathlib import Path
import sys

import pytest
import yaml


SERVER_ROOT = Path(__file__).resolve().parents[1]

if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))


TEST_PROVIDER_CONFIG = {
    'provider': 'qwen-coding',
    'base_url': 'http://localhost:11434/v1',
    'api_key': 'test-key',
    'models': {
        'test-model': {
            'name': 'Test Chat v0',
        },
    },
}

TEST_WORKER_AGENT = {
    'agent': {
        'id': 'code-agent-1',
        'name': 'Code Agent',
        'description': 'Handles coding and debugging tasks',
    },
    'model': 'qwen-coding/test-model',
    'tools': [],
    'database': {
        'db_file': 'db/code_agent.db',
        'db_id': 'code_agent_db',
    },
    'workspaces': [],
    'knowledge': [],
}

TEST_WORKER_TEAM = {
    'team': {
        'id': 'product-rd-team-1',
        'name': 'Product R&D Team',
        'description': 'Coordinates planning, implementation, architecture review, and research',
    },
    'model': 'qwen-coding/test-model',
    'members': [],
    'database': {
        'db_file': 'db/product_rd_team.db',
        'db_id': 'product_rd_team_db',
    },
}

TEST_WORKER_WORKFLOW = {
    'workflow': {
        'id': 'pr-workflow-1',
        'name': 'PR Workflow',
        'description': 'Spec -> prototype -> review -> ship',
    },
    'model': 'qwen-coding/test-model',
    'nodes': [],
    'database': {
        'db_file': 'db/pr_workflow.db',
        'db_id': 'pr_workflow_db',
    },
}


@pytest.fixture(autouse=True)
def _use_test_config(tmp_path, monkeypatch):
    config_dir = tmp_path / 'config'
    config_dir.mkdir()
    (config_dir / 'models').mkdir()
    (config_dir / 'workers').mkdir()

    (config_dir / 'models' / 'qwen-coding.yaml').write_text(
        yaml.dump(TEST_PROVIDER_CONFIG, allow_unicode=True), encoding='utf-8'
    )
    (config_dir / 'workers' / 'code-agent.yaml').write_text(
        yaml.dump(TEST_WORKER_AGENT, allow_unicode=True), encoding='utf-8'
    )
    (config_dir / 'workers' / 'product-rd-team.yaml').write_text(
        yaml.dump(TEST_WORKER_TEAM, allow_unicode=True), encoding='utf-8'
    )
    (config_dir / 'workers' / 'pr-workflow.yaml').write_text(
        yaml.dump(TEST_WORKER_WORKFLOW, allow_unicode=True), encoding='utf-8'
    )

    main_config = {
        'server': {'host': '127.0.0.1', 'port': 18080},
        'default_model': 'qwen-coding/test-model',
        'models': ['qwen-coding'],
        'workers': ['code-agent', 'product-rd-team', 'pr-workflow'],
    }
    config_path = config_dir / 'config.yaml'
    config_path.write_text(yaml.dump(main_config, allow_unicode=True), encoding='utf-8')
    monkeypatch.setenv('NOWORK_CONFIG_PATH', str(config_path))
