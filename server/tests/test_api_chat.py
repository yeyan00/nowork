from fastapi.testclient import TestClient

from agno.run.agent import RunCompletedEvent
from app.main import app


def test_can_create_session_for_worker() -> None:
    client = TestClient(app)

    response = client.post('/api/workers/code-agent-1/sessions', json={'title': 'First session'})

    assert response.status_code == 201
    assert response.json()['workerId'] == 'code-agent-1'
    assert response.json()['title'] == 'First session'


def test_agent_message_uses_runtime_agent_run() -> None:
    client = TestClient(app)

    class FakeAgent:
        id = 'code-agent-1'
        calls = []

        def run(self, message: str, session_id: str | None = None, stream: bool | None = None):
            self.calls.append((message, session_id, stream))
            if stream:
                return [RunCompletedEvent(
                    created_at='', event='RunCompleted',
                    agent_id='code-agent-1', agent_name='Code Agent',
                    run_id='', parent_run_id=None, session_id=session_id,
                    workflow_id=None, workflow_run_id=None,
                    step_id=None, step_name=None, step_index=None,
                    tools=None, content='runtime response',
                    content_type=None, reasoning_content=None,
                    citations=None, model_provider_data=None,
                    images=None, videos=None, audio=None,
                    response_audio=None, references=None,
                    additional_input=None, reasoning_steps=None,
                    reasoning_messages=None, metadata=None,
                    metrics=None, session_state=None,
                )]
            return type('Result', (), {'content': 'runtime response'})()

    class FakeAgentOS:
        agents = [FakeAgent()]
        teams = []
        workflows = []

    app.state.agent_os = FakeAgentOS()

    session = client.post('/api/workers/code-agent-1/sessions', json={'title': 'Runtime chat'}).json()
    response = client.post(f"/api/sessions/{session['id']}/messages", json={'content': 'Hello runtime'})

    assert response.status_code == 200
    assert 'RunCompleted' in response.text
    assert 'runtime response' in response.text


def test_agent_session_messages_are_loaded_from_runtime_history() -> None:
    client = TestClient(app)

    class FakeMessage:
        def __init__(self, role: str, content: str):
            self.role = role
            self.content = content
            self.created_at = '2026-04-13T10:00:00Z'

    class FakeAgent:
        id = 'code-agent-1'

        def get_chat_history(self, session_id: str | None = None, last_n_runs: int | None = None):
            return [
                FakeMessage('user', 'Hello'),
                FakeMessage('assistant', 'Hi there'),
            ]

    class FakeAgentOS:
        agents = [FakeAgent()]
        teams = []
        workflows = []

    app.state.agent_os = FakeAgentOS()
    session = client.post('/api/workers/code-agent-1/sessions', json={'title': 'Runtime history'}).json()

    response = client.get(f"/api/sessions/{session['id']}/messages")

    assert response.status_code == 200
    data = response.json()
    messages = data['messages']
    assert len(messages) == 2
    assert messages[0]['content'] == 'Hello'
    assert messages[0]['role'] == 'user'
    assert messages[1]['content'] == 'Hi there'
    assert messages[1]['role'] == 'worker'


def test_agent_session_messages_handle_non_json_tool_arguments() -> None:
    client = TestClient(app)

    class FakeMessage:
        def __init__(self):
            self.role = 'assistant'
            self.content = 'Used a tool'
            self.created_at = '2026-04-13T10:00:00Z'
            self.tool_calls = [
                {
                    'id': 'call-1',
                    'function': {
                        'name': 'read_file',
                        'arguments': "{'path': 'README.md'}",
                    },
                }
            ]

    class FakeAgent:
        id = 'code-agent-1'

        def get_chat_history(self, session_id: str | None = None, last_n_runs: int | None = None):
            return [FakeMessage()]

    class FakeAgentOS:
        agents = [FakeAgent()]
        teams = []
        workflows = []

    app.state.agent_os = FakeAgentOS()
    session = client.post('/api/workers/code-agent-1/sessions', json={'title': 'Runtime history'}).json()

    response = client.get(f"/api/sessions/{session['id']}/messages")

    assert response.status_code == 200
    data = response.json()
    messages = data['messages']
    assert messages[0]['toolCalls'][0]['toolArgs'] == {'raw': "{'path': 'README.md'}"}


def test_team_message_returns_placeholder_response() -> None:
    client = TestClient(app)

    session = client.post('/api/workers/product-rd-team-1/sessions', json={'title': 'Team chat'}).json()
    response = client.post(
        f"/api/sessions/{session['id']}/messages",
        json={'content': 'Coordinate release'},
    )

    assert response.status_code == 201
    assert response.json()['workerMessage']['content'] == 'Team execution is not enabled in phase 1'


def test_session_id_encodes_worker_id() -> None:
    client = TestClient(app)

    response = client.post('/api/workers/code-agent-1/sessions', json={'title': 'Test'})
    session = response.json()

    assert session['workerId'] == 'code-agent-1'
    assert session['id'].startswith('code-agent-1:')


def test_agent_sessions_list_from_runtime() -> None:
    client = TestClient(app)

    class FakeSession:
        def __init__(self, session_id, agent_id, created_at, session_data=None):
            self.session_id = session_id
            self.agent_id = agent_id
            self.created_at = created_at
            self.session_data = session_data or {}

    class FakeDb:
        def get_sessions(self, **kwargs):
            return [
                FakeSession('code-agent-1:abc123', 'code-agent-1', '2026-04-13T10:00:00Z', {'title': 'Chat 1'}),
                FakeSession('code-agent-1:def456', 'code-agent-1', '2026-04-13T11:00:00Z', {'title': 'Chat 2'}),
            ]

    class FakeAgent:
        id = 'code-agent-1'
        db = FakeDb()

    class FakeAgentOS:
        agents = [FakeAgent()]
        teams = []
        workflows = []

    app.state.agent_os = FakeAgentOS()
    response = client.get('/api/workers/code-agent-1/sessions')

    assert response.status_code == 200
    sessions = response.json()
    assert len(sessions) == 2
    assert sessions[0]['title'] == 'Chat 1'
    assert sessions[1]['title'] == 'Chat 2'
