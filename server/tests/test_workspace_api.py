from fastapi.testclient import TestClient

from app import services
from app.main import app


def test_list_workspaces_groups_worker_workspace_configs(tmp_path, monkeypatch):
    workspace = tmp_path / 'project'
    workspace.mkdir()

    monkeypatch.setattr(
        services.repository,
        'list_workers',
        lambda worker_type=None: [
            {
                'id': 'code-agent-1',
                'name': 'Code Agent',
                'type': 'Agent',
                'config': {
                    'workspaces': [
                        {'path': str(workspace), 'permission': 'read-write'},
                    ],
                },
            },
            {
                'id': 'code-explorer-1',
                'name': 'Code Explorer',
                'type': 'Agent',
                'config': {
                    'workspaces': [
                        {'path': str(workspace), 'permission': 'read'},
                    ],
                },
            },
        ],
    )

    response = TestClient(app).get('/api/workspaces')

    assert response.status_code == 200
    workspaces = response.json()
    assert len(workspaces) == 1
    assert workspaces[0]['name'] == 'project'
    assert workspaces[0]['path'] == str(workspace)
    assert workspaces[0]['permission'] == 'read-write'
    assert workspaces[0]['workerIds'] == ['code-agent-1', 'code-explorer-1']


def test_create_workspace_session_defaults_to_workspace_path(tmp_path, monkeypatch):
    workspace = tmp_path / 'project'
    workspace.mkdir()

    monkeypatch.setattr(
        services.repository,
        'list_workers',
        lambda worker_type=None: [
            {
                'id': 'code-agent-1',
                'name': 'Code Agent',
                'type': 'Agent',
                'config': {
                    'workspaces': [
                        {'path': str(workspace), 'permission': 'read-write'},
                    ],
                },
            },
        ],
    )
    monkeypatch.setattr(
        services.repository,
        'get_worker',
        lambda worker_id: {
            'id': worker_id,
            'name': 'Code Agent',
            'type': 'Agent',
            'config': {'workspaces': [{'path': str(workspace), 'permission': 'read-write'}]},
        },
    )

    client = TestClient(app)
    workspace_id = client.get('/api/workspaces').json()[0]['id']
    response = client.post(
        f'/api/workspaces/{workspace_id}/sessions',
        json={'workerId': 'code-agent-1', 'title': 'Workspace chat'},
    )

    assert response.status_code == 201
    session = response.json()
    assert session['workerId'] == 'code-agent-1'
    assert session['title'] == 'Workspace chat'
    assert session['workspaces'] == [str(workspace)]
