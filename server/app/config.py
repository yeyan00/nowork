from __future__ import annotations

import importlib
import os
from pathlib import Path

import yaml


CONFIG_DIR = Path(__file__).resolve().parents[1] / 'config'
DEFAULT_CONFIG_PATH = CONFIG_DIR / 'config.yaml'
SERVER_RUNTIME_DIR = Path(__file__).resolve().parents[1] / 'runtime'
SERVER_RUNTIME_FILE = SERVER_RUNTIME_DIR / 'app-runtime.json'
WEB_RUNTIME_FILE = Path(__file__).resolve().parents[2] / 'web' / 'public' / 'runtime' / 'app-runtime.json'


def resolve_config_path() -> Path:
    value = os.environ.get('NOWORK_CONFIG_PATH')
    if value:
        return Path(value)
    return DEFAULT_CONFIG_PATH


def resolve_config_dir() -> Path:
    return resolve_config_path().parent


def resolve_server_root() -> Path:
    return resolve_config_dir().parent


def load_config(path: Path | None = None) -> dict:
    config_path = path or resolve_config_path()
    with open(config_path, encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def get_server_config(config: dict | None = None) -> dict:
    cfg = config or load_config()
    return cfg.get('server', {})


def get_log_dir(config: dict | None = None) -> Path:
    cfg = config or load_config()
    server = cfg.get('server', {})
    log_dir = server.get('log_dir', 'runtime/logs')
    log_path = Path(log_dir)
    if not log_path.is_absolute():
        log_path = resolve_server_root() / log_path
    log_path.mkdir(parents=True, exist_ok=True)
    return log_path


def load_provider_config(provider_name: str) -> dict:
    cfg_dir = resolve_config_dir()
    provider_file = cfg_dir / 'models' / f'{provider_name}.yaml'
    if provider_file.exists():
        with open(provider_file, encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    return {}


def get_session_config(config: dict | None = None) -> dict:
    cfg = config or load_config()
    return cfg.get('session', {})


def get_compaction_config(config: dict | None = None) -> dict:
    session_cfg = get_session_config(config)
    return session_cfg.get('compaction', {})


def update_compaction_config(updates: dict) -> dict:
    """Update compaction config in config.yaml. Returns the updated compaction config."""
    config_path = resolve_config_path()
    cfg = load_config(config_path)
    if 'session' not in cfg:
        cfg['session'] = {}
    if 'compaction' not in cfg['session']:
        cfg['session']['compaction'] = {}
    cfg['session']['compaction'].update(updates)
    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return cfg['session']['compaction']


def get_default_model_id(config: dict | None = None) -> str:
    cfg = config or load_config()
    model = cfg.get('default_model')
    if not model:
        raise ValueError("config.yaml 中未配置 default_model，请在 server/config/config.yaml 中设置 default_model")
    return model


def set_default_model_id(model_id: str) -> None:
    config_path = resolve_config_path()
    cfg = load_config(config_path)
    cfg['default_model'] = model_id
    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _parse_model_ref(model_ref: str) -> tuple[str, str]:
    if '/' in model_ref:
        provider, model_id = model_ref.split('/', 1)
        return provider, model_id
    return 'openai', model_ref


def get_full_model_config(model_ref: str | None = None, config: dict | None = None) -> dict:
    cfg = config or load_config()
    try:
        ref = model_ref or get_default_model_id(cfg)
    except ValueError:
        return {}
    provider_name, model_id = _parse_model_ref(ref)
    provider_cfg = load_provider_config(provider_name)
    provider_cfg['id'] = model_id
    return provider_cfg


def get_model_capabilities(model_ref: str | None = None, config: dict | None = None) -> dict:
    cfg = config or load_config()
    try:
        ref = model_ref or get_default_model_id(cfg)
    except ValueError:
        return {
            'image': False,
            'video': False,
            'file': True,
        }
    provider_name, model_id = _parse_model_ref(ref)
    provider_cfg = load_provider_config(provider_name)
    models = provider_cfg.get('models', {}) if isinstance(provider_cfg, dict) else {}
    model_info = models.get(model_id, {}) if isinstance(models, dict) else {}
    if not isinstance(model_info, dict):
        model_info = {}
    legacy_vision = bool(model_info.get('vision', False))
    return {
        'image': bool(model_info.get('image', legacy_vision)),
        'video': bool(model_info.get('video', legacy_vision)),
        'file': True,
    }


def get_worker_refs(config: dict | None = None) -> list[str]:
    cfg = config or load_config()
    return cfg.get('workers', [])


def load_worker_config(worker_ref: str) -> dict:
    cfg_dir = resolve_config_dir()
    worker_file = cfg_dir / 'workers' / f'{worker_ref}.yaml'
    if worker_file.exists():
        with open(worker_file, encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    return {}


def get_workers_config(config: dict | None = None) -> list[dict]:
    cfg = config or load_config()
    refs = cfg.get('workers', [])
    result = []
    for ref in refs:
        if isinstance(ref, str):
            worker_cfg = load_worker_config(ref)
            if worker_cfg:
                worker_cfg['_ref'] = ref
                result.append(worker_cfg)
        elif isinstance(ref, dict):
            result.append(ref)
    return result


def save_worker_config(worker_ref: str, worker_cfg: dict) -> None:
    cfg_dir = resolve_config_dir()
    workers_dir = cfg_dir / 'workers'
    workers_dir.mkdir(parents=True, exist_ok=True)
    worker_file = workers_dir / f'{worker_ref}.yaml'
    clean = {k: v for k, v in worker_cfg.items() if not k.startswith('_')}
    with open(worker_file, 'w', encoding='utf-8') as f:
        yaml.dump(clean, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def add_worker_ref(worker_ref: str) -> None:
    config_path = resolve_config_path()
    cfg = load_config(config_path)
    workers = cfg.get('workers', [])
    if worker_ref not in workers:
        workers.append(worker_ref)
        cfg['workers'] = workers
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _get_global_tools_config() -> dict:
    cfg = load_config()
    return cfg.get('tools', {})


def resolve_tools(tools_cfg: list[dict] | None, workspace_permissions: dict[str, str] | None = None) -> list:
    global_tools = _get_global_tools_config()
    shell_path = global_tools.get('shell_path')
    rg_path = global_tools.get('rg_path')
    fd_path = global_tools.get('fd_path')
    has_global = shell_path or rg_path or fd_path

    instances = []
    if not tools_cfg:
        return instances
    for tool_def in tools_cfg:
        module_path = tool_def.get('module')
        class_name = tool_def.get('class')
        tool_kwargs = tool_def.get('config', {})
        if not module_path or not class_name:
            continue
        try:
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
            if class_name == 'CodingTools':
                # Auto-create workspace directories if they don't exist
                base_dirs = tool_kwargs.get('base_dirs')
                if isinstance(base_dirs, list):
                    for d in base_dirs:
                        p = Path(d).expanduser()
                        if not p.exists():
                            try:
                                p.mkdir(parents=True, exist_ok=True)
                                from agno.utils.log import log_info as _li
                                _li(f"Created workspace directory: {p}")
                            except Exception as mkdir_err:
                                from agno.utils.log import log_warning as _lw
                                _lw(f"Cannot create workspace directory {p}: {mkdir_err}")
                elif isinstance(base_dirs, str):
                    p = Path(base_dirs).expanduser()
                    if not p.exists():
                        try:
                            p.mkdir(parents=True, exist_ok=True)
                            from agno.utils.log import log_info as _li
                            _li(f"Created workspace directory: {p}")
                        except Exception as mkdir_err:
                            from agno.utils.log import log_warning as _lw
                            _lw(f"Cannot create workspace directory {p}: {mkdir_err}")
                # Pass workspace permissions to CodingTools
                if workspace_permissions:
                    tool_kwargs['workspace_permissions'] = workspace_permissions
                if has_global:
                    tc = tool_kwargs.get('tool_config', {})
                    if isinstance(tc, dict):
                        tc.setdefault('shell_path', shell_path)
                        tc.setdefault('rg_path', rg_path)
                        tc.setdefault('fd_path', fd_path)
                        tool_kwargs['tool_config'] = tc
            instances.append(cls(**tool_kwargs))
        except Exception as e:
            from agno.utils.log import log_error
            log_error(f"Failed to load tool {module_path}.{class_name}: {e}")
    return instances


def resolve_database_config(db_cfg: dict | None) -> dict:
    if not db_cfg:
        return {}
    return {
        'db_file': db_cfg.get('db_file'),
        'db_id': db_cfg.get('db_id'),
    }


def get_all_providers(config: dict | None = None) -> list[dict]:
    cfg = config or load_config()
    provider_refs = cfg.get('models', [])
    result = []
    for ref in provider_refs:
        if not isinstance(ref, str):
            continue
        provider_cfg = load_provider_config(ref)
        if not provider_cfg:
            continue
        result.append(_serialize_provider(ref, provider_cfg))
    return result


def _serialize_provider(provider_id: str, provider_cfg: dict) -> dict:
    models_raw = provider_cfg.get('models', {})
    models = []
    for model_id, model_info in models_raw.items():
        if not isinstance(model_info, dict):
            model_info = {}
        legacy_vision = model_info.get('vision', False)
        models.append({
            'id': f'{provider_id}/{model_id}',
            'localId': model_id,
            'name': model_info.get('name', model_id),
            'image': model_info.get('image', legacy_vision),
            'video': model_info.get('video', legacy_vision),
        })
    return {
        'id': provider_id,
        'name': provider_cfg.get('name', provider_cfg.get('provider', provider_id)),
        'type': provider_cfg.get('type', 'openai_compatible'),
        'provider': provider_cfg.get('provider', provider_id),
        'baseUrl': provider_cfg.get('base_url', ''),
        'apiKey': provider_cfg.get('api_key', ''),
        'models': models,
    }


def save_provider_config(provider_id: str, provider_cfg: dict) -> None:
    cfg_dir = resolve_config_dir()
    models_dir = cfg_dir / 'models'
    models_dir.mkdir(parents=True, exist_ok=True)
    provider_file = models_dir / f'{provider_id}.yaml'
    clean = {k: v for k, v in provider_cfg.items() if not k.startswith('_')}
    with open(provider_file, 'w', encoding='utf-8') as f:
        yaml.dump(clean, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def add_provider_ref(provider_id: str) -> None:
    config_path = resolve_config_path()
    cfg = load_config(config_path)
    models = cfg.get('models', [])
    if provider_id not in models:
        models.append(provider_id)
        cfg['models'] = models
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def remove_provider_ref(provider_id: str) -> None:
    config_path = resolve_config_path()
    cfg = load_config(config_path)
    models = cfg.get('models', [])
    if provider_id in models:
        models.remove(provider_id)
        cfg['models'] = models
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def delete_provider_config(provider_id: str) -> bool:
    cfg_dir = resolve_config_dir()
    provider_file = cfg_dir / 'models' / f'{provider_id}.yaml'
    if provider_file.exists():
        provider_file.unlink()
        return True
    return False


MCP_CONFIG_FILE = 'mcp.yaml'


def load_mcp_config() -> list[dict]:
    cfg_dir = resolve_config_dir()
    mcp_file = cfg_dir / MCP_CONFIG_FILE
    if not mcp_file.exists():
        return []
    with open(mcp_file, encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    return data.get('servers', [])


def save_mcp_config(servers: list[dict]) -> None:
    cfg_dir = resolve_config_dir()
    mcp_file = cfg_dir / MCP_CONFIG_FILE
    with open(mcp_file, 'w', encoding='utf-8') as f:
        yaml.dump({'servers': servers}, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def resolve_runtime_files(override_dir: Path | None = None) -> list[Path]:
    if override_dir is None:
        override_value = os.environ.get('NOWORK_RUNTIME_DIR')
        override_dir = Path(override_value) if override_value else None

    if override_dir is not None:
        files = [override_dir / 'app-runtime.json']
        # Also write to web/public so Vite dev server can find it
        web_rt = os.environ.get('NOWORK_WEB_RUNTIME_FILE')
        if web_rt:
            files.append(Path(web_rt))
        elif WEB_RUNTIME_FILE.parent.parent.exists():
            files.append(WEB_RUNTIME_FILE)
        return files

    return [SERVER_RUNTIME_FILE, WEB_RUNTIME_FILE]


def list_knowledge_refs(config: dict | None = None) -> list[str]:
    cfg = config or load_config()
    return cfg.get('knowledge', [])


def load_knowledge_config(knowledge_ref: str) -> dict:
    cfg_dir = resolve_config_dir()
    k_file = cfg_dir / 'knowledge' / f'{knowledge_ref}.yaml'
    if k_file.exists():
        with open(k_file, encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    return {}


def get_all_knowledge_configs(config: dict | None = None) -> list[dict]:
    cfg = config or load_config()
    refs = cfg.get('knowledge', [])
    result = []
    for ref in refs:
        if isinstance(ref, str):
            k_cfg = load_knowledge_config(ref)
            if k_cfg:
                k_cfg['_ref'] = ref
                result.append(k_cfg)
        elif isinstance(ref, dict):
            result.append(ref)
    return result


def save_knowledge_config(knowledge_ref: str, k_cfg: dict) -> None:
    cfg_dir = resolve_config_dir()
    k_dir = cfg_dir / 'knowledge'
    k_dir.mkdir(parents=True, exist_ok=True)
    k_file = k_dir / f'{knowledge_ref}.yaml'
    clean = {k: v for k, v in k_cfg.items() if not k.startswith('_')}
    with open(k_file, 'w', encoding='utf-8') as f:
        yaml.dump(clean, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def add_knowledge_ref(knowledge_ref: str) -> None:
    config_path = resolve_config_path()
    cfg = load_config(config_path)
    knowledge = cfg.get('knowledge', [])
    if knowledge_ref not in knowledge:
        knowledge.append(knowledge_ref)
        cfg['knowledge'] = knowledge
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def remove_knowledge_ref(knowledge_ref: str) -> None:
    config_path = resolve_config_path()
    cfg = load_config(config_path)
    knowledge = cfg.get('knowledge', [])
    if knowledge_ref in knowledge:
        knowledge.remove(knowledge_ref)
        cfg['knowledge'] = knowledge
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def delete_knowledge_config(knowledge_ref: str) -> bool:
    cfg_dir = resolve_config_dir()
    k_file = cfg_dir / 'knowledge' / f'{knowledge_ref}.yaml'
    if k_file.exists():
        k_file.unlink()
        return True
    return False
