from fastapi.testclient import TestClient

from app.main import app


def test_workers_api_lists_seeded_workers() -> None:
    client = TestClient(app)

    response = client.get('/api/workers')

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 3
    assert {item['type'] for item in payload} == {'Agent', 'Team', 'Workflow'}


def test_workers_api_supports_type_filter() -> None:
    client = TestClient(app)

    response = client.get('/api/workers?type=Agent')

    assert response.status_code == 200
    assert [item['type'] for item in response.json()] == ['Agent']


def test_workers_api_can_create_and_update_worker() -> None:
    client = TestClient(app)

    create_response = client.post(
        '/api/workers',
        json={
            'type': 'Agent',
            'name': 'Docs Agent',
            'description': 'Answers docs questions',
            'status': 'Ready',
            'config': {
                'model': {'provider': 'OpenAI Compatible', 'model': 'gpt-4.1'},
                'workspaces': [],
                'knowledge': [],
            },
        },
    )

    assert create_response.status_code == 201
    created_worker = create_response.json()
    assert created_worker['name'] == 'Docs Agent'

    update_response = client.put(
        f"/api/workers/{created_worker['id']}",
        json={
            'name': 'Docs Agent Updated',
            'description': 'Updated',
            'status': 'Busy',
            'config': {
                'model': {'provider': 'Qwen', 'model': 'qwen-max'},
                'workspaces': [{'path': 'D:/docs', 'permission': 'read'}],
                'knowledge': ['Product Docs'],
            },
        },
    )

    assert update_response.status_code == 200
    assert update_response.json()['name'] == 'Docs Agent Updated'

    detail_response = client.get(f"/api/workers/{created_worker['id']}")

    assert detail_response.status_code == 200
    assert detail_response.json()['status'] == 'Busy'
