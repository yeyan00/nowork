from __future__ import annotations

from pathlib import Path
from typing import Any

from agno.agent import Agent
from agno.os import AgentOS
from agno.team import Team

from app.config import get_full_model_config, get_default_model_id, resolve_tools, resolve_database_config, resolve_server_root, load_mcp_config, get_all_knowledge_configs
from app.repository import _detect_type, _merge_history, _merge_learning


def _apply_history(agent_kwargs: dict, history: dict) -> None:
    """Apply history/compaction settings to agent or team kwargs."""
    if history.get('enable_compaction'):
        # Compaction mode: enable_compaction=True, add_history_to_context is ignored
        agent_kwargs['enable_compaction'] = True
        try:
            from agno.compaction import CompactionManager
            agent_kwargs['compaction_manager'] = CompactionManager(
                context_usage_threshold=history.get('compaction_context_usage_threshold', 0.75),
                context_reserve_tokens=history.get('compaction_context_reserve_tokens', 4000),
                preserve_last_n_messages=history.get('compaction_preserve_last_n_messages', 2),
            )
        except ImportError:
            from agno.utils.log import log_warning
            log_warning("CompactionManager not available, falling back to history mode")
            agent_kwargs['add_history_to_context'] = True
            if history.get('num_history_messages') is not None:
                agent_kwargs['num_history_messages'] = history['num_history_messages']
            if history.get('max_tool_calls_from_history') is not None:
                agent_kwargs['max_tool_calls_from_history'] = history['max_tool_calls_from_history']
    else:
        # Classic history mode
        agent_kwargs['add_history_to_context'] = history.get('add_history_to_context', True)
        if history.get('num_history_messages') is not None:
            agent_kwargs['num_history_messages'] = history['num_history_messages']
        if history.get('max_tool_calls_from_history') is not None:
            agent_kwargs['max_tool_calls_from_history'] = history['max_tool_calls_from_history']


def _build_learning(learning_cfg: dict | None, db: Any | None, model: Any | None) -> Any | None:
    """Build LearningMachine from learning configuration.

    Args:
        learning_cfg: Learning config dict with boolean flags:
            - user_profile: Enable user profile learning
            - user_memory: Enable user memory learning
            - session_context: Enable session context learning
            - entity_memory: Enable entity memory learning
            - decision_log: Enable decision log learning
        db: Database instance for storage
        model: Model instance for extraction

    Returns:
        LearningMachine instance or None if disabled.
    """
    if not learning_cfg:
        return None

    # Check if any learning type is enabled
    any_enabled = any([
        learning_cfg.get('user_profile', False),
        learning_cfg.get('user_memory', False),
        learning_cfg.get('session_context', False),
        learning_cfg.get('entity_memory', False),
        learning_cfg.get('decision_log', False),
    ])

    if not any_enabled:
        return None

    # LearningMachine requires a database
    if db is None:
        from agno.utils.log import log_warning
        log_warning("Learning enabled but no database provided. LearningMachine not initialized.")
        return None

    from agno.learn.machine import LearningMachine

    return LearningMachine(
        db=db,
        model=model,
        user_profile=learning_cfg.get('user_profile', False),
        user_memory=learning_cfg.get('user_memory', False),
        session_context=learning_cfg.get('session_context', False),
        entity_memory=learning_cfg.get('entity_memory', False),
        decision_log=learning_cfg.get('decision_log', False),
    )


def _build_knowledge_for_worker(knowledge_refs: list[str] | str | None) -> Any | None:
    if not knowledge_refs:
        return None

    if isinstance(knowledge_refs, str):
        knowledge_refs = [knowledge_refs]

    all_kb_configs = get_all_knowledge_configs()
    kb_map: dict[str, dict] = {}
    for kb_cfg in all_kb_configs:
        kb_id = kb_cfg.get('id', '')
        ref_name = kb_cfg.get('_ref', '')
        if kb_id:
            kb_map[kb_id] = kb_cfg
        if ref_name:
            kb_map[ref_name] = kb_cfg

    first_kb = None
    for ref in knowledge_refs:
        kb_cfg = kb_map.get(ref)
        if kb_cfg is None:
            continue

        kb_obj = _build_single_knowledge(kb_cfg)
        if kb_obj is not None and first_kb is None:
            first_kb = kb_obj

    return first_kb


def _build_embedder(embedder_cfg: dict) -> Any:
    embedder_type = embedder_cfg.get('type', 'openai')

    if embedder_type == 'sentence-transformer':
        from app.extensions import is_extension_available
        if not is_extension_available('sentence-transformer'):
            from agno.utils.log import log_warning
            log_warning("sentence-transformer extension not installed, falling back to OpenAI embedder")
            return _build_embedder({**embedder_cfg, 'type': 'openai'})
        from agno.knowledge.embedder.sentence_transformer import SentenceTransformerEmbedder
        model_id = embedder_cfg.get('model', 'sentence-transformers/all-MiniLM-L6-v2')
        return SentenceTransformerEmbedder(id=model_id)

    from agno.knowledge.embedder.openai import OpenAIEmbedder
    embedder_kwargs: dict[str, Any] = {}
    model_ref = embedder_cfg.get('model')
    if model_ref:
        model_full = get_full_model_config(model_ref)
        embedder_kwargs['api_key'] = model_full.get('api_key')
        embedder_kwargs['base_url'] = model_full.get('base_url')
        embedder_kwargs['id'] = model_full.get('id', 'text-embedding-3-small')
    return OpenAIEmbedder(**embedder_kwargs)


def _build_single_knowledge(kb_cfg: dict) -> Any | None:
    from app.extensions import is_extension_available
    if not is_extension_available('local-vector-db'):
        from agno.utils.log import log_warning
        log_warning("pymilvus not installed, knowledge system disabled. Install 'local-vector-db' extension.")
        return None

    from agno.knowledge.knowledge import Knowledge
    from agno.vectordb.milvus import Milvus

    kb_id = kb_cfg.get('id', 'default')
    name = kb_cfg.get('name', kb_id)

    db_dir = resolve_server_root() / 'db'
    db_dir.mkdir(parents=True, exist_ok=True)
    db_uri = str(db_dir / f'{kb_id}.db')

    embedder = _build_embedder(kb_cfg.get('embedder', {}))

    vector_db = Milvus(
        collection=kb_id,
        embedder=embedder,
        uri=db_uri,
    )

    knowledge = Knowledge(
        id=kb_id,
        name=name,
        description=kb_cfg.get('description', ''),
        vector_db=vector_db,
    )

    paths = kb_cfg.get('paths', [])
    if paths:
        knowledge.insert_many(paths=paths)

    return knowledge


def _build_model(model_ref: str | None) -> Any | None:
    if not model_ref:
        model_ref = get_default_model_id()
    model_cfg = get_full_model_config(model_ref)
    if not model_cfg:
        return None
    from agno.models.openai.like import OpenAILike
    model_id = model_cfg.get('id')
    if not model_id:
        raise ValueError(f"模型配置中缺少 id 字段: {model_cfg}")
    return OpenAILike(
        id=model_id,
        name=model_cfg.get('provider', model_id),
        base_url=model_cfg.get('base_url'),
        api_key=model_cfg.get('api_key'),
    )


async def _build_mcp_tools(mcp_names: list[str] | None) -> list[Any]:
    if not mcp_names:
        return []
    all_servers = load_mcp_config()
    name_set = set(mcp_names)
    instances = []
    for srv in all_servers:
        srv_name = srv.get('name', '')
        if srv_name not in name_set:
            continue
        try:
            from agno.tools.mcp import MCPTools
            kwargs: dict[str, Any] = {}
            transport = srv.get('transport', 'stdio')
            kwargs['transport'] = transport
            if transport == 'stdio':
                kwargs['command'] = srv.get('command', '')
            else:
                kwargs['url'] = srv.get('url', '')
            if srv.get('env'):
                kwargs['env'] = srv['env']
            if srv.get('timeout_seconds'):
                kwargs['timeout_seconds'] = srv['timeout_seconds']
            tools_cfg = srv.get('tools', [])
            if isinstance(tools_cfg, list) and len(tools_cfg) > 0 and isinstance(tools_cfg[0], str):
                all_names = tools_cfg
            else:
                all_names = [t['name'] for t in tools_cfg if isinstance(t, dict) and t.get('enabled', True)]
            if srv.get('exclude_tools'):
                kwargs['exclude_tools'] = srv['exclude_tools']
            elif srv.get('include_tools'):
                kwargs['include_tools'] = srv['include_tools']
            elif all_names:
                kwargs['include_tools'] = all_names
            mcp = MCPTools(**kwargs)
            await mcp.connect()
            instances.append(mcp)
        except Exception as e:
            from agno.utils.log import log_error
            log_error(f"Failed to load MCP server {srv_name}: {e}")
    return instances


def _build_db(db_cfg: dict | None) -> Any | None:
    if not db_cfg or not db_cfg.get('db_file'):
        return None
    from agno.db.sqlite import SqliteDb
    db_path = Path(db_cfg['db_file'])
    if not db_path.is_absolute():
        db_path = resolve_server_root() / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {'db_file': str(db_path)}
    if db_cfg.get('db_id'):
        kwargs['id'] = db_cfg['db_id']
    return SqliteDb(**kwargs)


def _extract_block(raw: dict) -> dict:
    block = raw
    for key in ('agent', 'team', 'workflow'):
        if key in raw:
            return raw[key]
    return block


def _build_skills(skill_names: list[str] | None, skills_dir: Path) -> Any | None:
    if not skill_names:
        return None
    try:
        from agno.skills.agent_skills import Skills
        from agno.skills.loaders.local import LocalSkills
        loader = LocalSkills(str(skills_dir), validate=False)
        all_skills = Skills(loaders=[loader])
        matched = [all_skills.get_skill(n) for n in skill_names]
        matched = [s for s in matched if s is not None]
        if not matched:
            return None
        from agno.skills.agent_skills import Skills as SkillsCls
        filtered = SkillsCls.__new__(SkillsCls)
        filtered.loaders = [loader]
        filtered._skills = {s.name: s for s in matched}
        return filtered
    except Exception:
        return None


async def build_agent_os(workers: list[dict[str, Any]], base_app: Any | None = None) -> AgentOS:
    skills_dir = Path(__file__).resolve().parents[2] / 'skills'
    agents: list[Agent] = []
    teams: list[Team] = []

    for worker in workers:
        raw = worker.get('_raw', worker)
        worker_type = _detect_type(worker)
        block = _extract_block(raw)

        if worker_type == 'Agent':
            agent_kwargs: dict[str, Any] = {
                'id': block.get('id', worker.get('id', '')),
                'name': block.get('name', worker.get('name', '')),
                'description': block.get('description', ''),
            }

            instructions = block.get('instructions')
            if instructions:
                agent_kwargs['instructions'] = instructions

            model = _build_model(raw.get('model'))
            if model:
                agent_kwargs['model'] = model

            tools = resolve_tools(raw.get('tools'))
            if tools:
                agent_kwargs['tools'] = tools

            mcp_tools = await _build_mcp_tools(raw.get('mcp'))
            if mcp_tools:
                agent_kwargs['tools'] = tools + mcp_tools if tools else mcp_tools

            db_cfg = resolve_database_config(raw.get('database'))
            db = _build_db(db_cfg)
            if db:
                agent_kwargs['db'] = db

            skills = _build_skills(raw.get('skills'), skills_dir)
            if skills:
                agent_kwargs['skills'] = skills

            history = _merge_history(raw)
            _apply_history(agent_kwargs, history)

            learning_cfg = _merge_learning(raw)
            model_for_learning = agent_kwargs.get('model')
            learning = _build_learning(learning_cfg, db, model_for_learning)
            if learning:
                agent_kwargs['learning'] = learning

            knowledge = _build_knowledge_for_worker(raw.get('knowledge'))
            if knowledge:
                agent_kwargs['knowledge'] = knowledge

            agents.append(Agent(**agent_kwargs))

        elif worker_type == 'Team':
            model = _build_model(raw.get('model'))

            member_refs = raw.get('members', [])
            member_agents: list[Agent] = []
            for ref in member_refs:
                member_id = ref.get('agent_id', '')
                for a in agents:
                    if a.id == member_id:
                        member_agents.append(a)
                        break

            team_kwargs: dict[str, Any] = {
                'id': block.get('id', worker.get('id', '')),
                'name': block.get('name', worker.get('name', '')),
                'description': block.get('description', ''),
                'members': member_agents,
            }

            instructions = block.get('instructions')
            if instructions:
                team_kwargs['instructions'] = instructions

            if model:
                team_kwargs['model'] = model

            db_cfg = resolve_database_config(raw.get('database'))
            db = _build_db(db_cfg)
            if db:
                team_kwargs['db'] = db

            skills = _build_skills(raw.get('skills'), skills_dir)
            if skills:
                team_kwargs['skills'] = skills

            history = _merge_history(raw)
            _apply_history(team_kwargs, history)

            learning_cfg = _merge_learning(raw)
            model_for_learning = team_kwargs.get('model')
            learning = _build_learning(learning_cfg, db, model_for_learning)
            if learning:
                team_kwargs['learning'] = learning

            knowledge = _build_knowledge_for_worker(raw.get('knowledge'))
            if knowledge:
                team_kwargs['knowledge'] = knowledge

            teams.append(Team(**team_kwargs))

    return AgentOS(agents=agents, teams=teams, base_app=base_app)


async def _build_single_agent(raw: dict[str, Any]) -> Agent | None:
    skills_dir = Path(__file__).resolve().parents[2] / 'skills'
    block = _extract_block(raw)

    agent_kwargs: dict[str, Any] = {
        'id': block.get('id', raw.get('id', '')),
        'name': block.get('name', raw.get('name', '')),
        'description': block.get('description', ''),
    }

    instructions = block.get('instructions')
    if instructions:
        agent_kwargs['instructions'] = instructions

    model = _build_model(raw.get('model'))
    if model:
        agent_kwargs['model'] = model

    tools = resolve_tools(raw.get('tools'))
    if tools:
        agent_kwargs['tools'] = tools

    mcp_tools = await _build_mcp_tools(raw.get('mcp'))
    if mcp_tools:
        agent_kwargs['tools'] = tools + mcp_tools if tools else mcp_tools

    db_cfg = resolve_database_config(raw.get('database'))
    db = _build_db(db_cfg)
    if db:
        agent_kwargs['db'] = db

    skills = _build_skills(raw.get('skills'), skills_dir)
    if skills:
        agent_kwargs['skills'] = skills

    history = _merge_history(raw)
    _apply_history(agent_kwargs, history)

    learning_cfg = _merge_learning(raw)
    model_for_learning = agent_kwargs.get('model')
    learning = _build_learning(learning_cfg, db, model_for_learning)
    if learning:
        agent_kwargs['learning'] = learning

    knowledge = _build_knowledge_for_worker(raw.get('knowledge'))
    if knowledge:
        agent_kwargs['knowledge'] = knowledge

    return Agent(**agent_kwargs)


async def _build_single_team(raw: dict[str, Any], existing_agents: list[Agent]) -> Team | None:
    skills_dir = Path(__file__).resolve().parents[2] / 'skills'
    block = _extract_block(raw)

    model = _build_model(raw.get('model'))

    member_refs = raw.get('members', [])
    member_agents: list[Agent] = []
    for ref in member_refs:
        member_id = ref.get('agent_id', '')
        for a in existing_agents:
            if a.id == member_id:
                member_agents.append(a)
                break

    team_kwargs: dict[str, Any] = {
        'id': block.get('id', raw.get('id', '')),
        'name': block.get('name', raw.get('name', '')),
        'description': block.get('description', ''),
        'members': member_agents,
    }

    instructions = block.get('instructions')
    if instructions:
        team_kwargs['instructions'] = instructions

    if model:
        team_kwargs['model'] = model

    db_cfg = resolve_database_config(raw.get('database'))
    db = _build_db(db_cfg)
    if db:
        team_kwargs['db'] = db

    skills = _build_skills(raw.get('skills'), skills_dir)
    if skills:
        team_kwargs['skills'] = skills

    history = _merge_history(raw)
    _apply_history(team_kwargs, history)

    learning_cfg = _merge_learning(raw)
    model_for_learning = team_kwargs.get('model')
    learning = _build_learning(learning_cfg, db, model_for_learning)
    if learning:
        team_kwargs['learning'] = learning

    knowledge = _build_knowledge_for_worker(raw.get('knowledge'))
    if knowledge:
        team_kwargs['knowledge'] = knowledge

    return Team(**team_kwargs)


async def reload_worker(agent_os: AgentOS, worker_id: str, worker_type: str) -> bool:
    from app.repository import get_worker
    serialized = get_worker(worker_id)
    if serialized is None:
        return False
    raw = serialized.get('_raw', serialized)

    if worker_type == 'Agent':
        new_agent = await _build_single_agent(raw)
        if new_agent is None:
            return False
        for i, a in enumerate(agent_os.agents):
            if a.id == worker_id:
                agent_os.agents[i] = new_agent
                break
        else:
            agent_os.agents.append(new_agent)
        return True

    if worker_type == 'Team':
        new_team = await _build_single_team(raw, agent_os.agents)
        if new_team is None:
            return False
        for i, t in enumerate(agent_os.teams):
            if t.id == worker_id:
                agent_os.teams[i] = new_team
                break
        else:
            agent_os.teams.append(new_team)
        return True

    return False


async def add_worker_to_os(agent_os: AgentOS, worker_id: str) -> bool:
    from app.repository import get_worker, _detect_type
    serialized = get_worker(worker_id)
    if serialized is None:
        return False
    raw = serialized.get('_raw', serialized)
    worker_type = _detect_type(raw)
    return await reload_worker(agent_os, worker_id, worker_type)
