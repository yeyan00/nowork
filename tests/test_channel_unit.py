"""Unit tests for channel framework — no server required.

Tests:
  - schema: ChannelConfig, ChannelMessage, ChannelStatus
  - registry: register, get, list_platforms
  - base: BaseChannel abstract class
  - manager: ChannelManager config loading, session mapping
  - dingtalk: DingTalkChannel class structure

Usage:
  pytest tests/test_channel_unit.py -v
"""
import json
import pytest
import sys
import os

# Ensure server is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))


class TestSchema:
    def test_channel_config_basic(self):
        from app.channels.schema import ChannelConfig
        cfg = ChannelConfig(
            id='test-ch',
            platform='dingtalk',
            name='Test',
            enabled=True,
            worker_id='worker-1',
            config={'client_id': 'abc', 'client_secret': 'xyz'},
        )
        assert cfg.id == 'test-ch'
        assert cfg.platform == 'dingtalk'
        assert cfg.worker_id == 'worker-1'
        assert cfg.enabled is True

    def test_channel_config_platform_config(self):
        from app.channels.schema import ChannelConfig
        cfg = ChannelConfig(
            id='ch',
            platform='dingtalk',
            name='',
            enabled=False,
            worker_id='',
            config={'client_id': 'abc', 'client_secret': 'xyz', 'message_type': 'markdown'},
        )
        assert cfg.platform_config('client_id') == 'abc'
        assert cfg.platform_config('message_type') == 'markdown'
        assert cfg.platform_config('nonexistent', 'default') == 'default'

    def test_channel_config_defaults(self):
        from app.channels.schema import ChannelConfig
        cfg = ChannelConfig(id='ch', platform='dingtalk', name='', enabled=False, worker_id='')
        assert cfg.config == {}
        assert cfg.platform_config('anything') is None

    def test_channel_message(self):
        from app.channels.schema import ChannelMessage
        msg = ChannelMessage(
            channel_id='ch1',
            platform='dingtalk',
            sender_id='user123',
            session_id='dingtalk:user123',
            text='hello',
            meta={'is_group': False},
        )
        assert msg.channel_id == 'ch1'
        assert msg.session_id == 'dingtalk:user123'
        assert msg.text == 'hello'

    def test_channel_status(self):
        from app.channels.schema import ChannelStatus
        st = ChannelStatus(
            id='ch1',
            platform='dingtalk',
            name='Test',
            enabled=True,
            worker_id='w1',
            status='running',
            detail='',
        )
        assert st.status == 'running'

    def test_supported_platforms(self):
        from app.channels.schema import SUPPORTED_PLATFORMS
        assert 'dingtalk' in SUPPORTED_PLATFORMS
        assert 'feishu' in SUPPORTED_PLATFORMS
        assert 'wecom' in SUPPORTED_PLATFORMS


class TestRegistry:
    def test_dingtalk_registered(self):
        from app.channels.registry import get, list_platforms
        assert 'dingtalk' in list_platforms()
        cls = get('dingtalk')
        assert cls is not None
        assert cls.platform == 'dingtalk'

    def test_unknown_platform(self):
        from app.channels.registry import get
        assert get('nonexistent') is None

    def test_register_custom(self):
        from app.channels.registry import register, get, list_platforms
        from app.channels.base import BaseChannel
        from app.channels.schema import ChannelConfig, ChannelMessage

        class FakeChannel(BaseChannel):
            platform = 'fake'

            async def start(self): pass
            async def stop(self): pass
            async def send(self, session_id, text, meta=None): pass

        register('fake', FakeChannel)
        assert 'fake' in list_platforms()
        assert get('fake') is FakeChannel


class TestBaseChannel:
    def test_abstract_cannot_instantiate(self):
        from app.channels.base import BaseChannel
        with pytest.raises(TypeError):
            BaseChannel(None, None)

    def test_resolve_session_id(self):
        from app.channels.base import BaseChannel
        from app.channels.schema import ChannelConfig, ChannelMessage

        class DummyChannel(BaseChannel):
            platform = 'dummy'
            async def start(self): pass
            async def stop(self): pass
            async def send(self, session_id, text, meta=None): pass

        cfg = ChannelConfig(id='ch', platform='dummy', name='', enabled=False, worker_id='w1')
        ch = DummyChannel(cfg=cfg, on_message=lambda m: None)
        assert ch.channel_id == 'ch'
        assert ch.worker_id == 'w1'
        assert ch.resolve_session_id('user123') == 'dummy:user123'


class TestManager:
    def test_init(self):
        from app.channels.manager import ChannelManager
        mgr = ChannelManager()
        assert mgr._channels == {}
        assert mgr._session_map == {}

    def test_load_configs(self):
        from app.channels.manager import ChannelManager
        mgr = ChannelManager()
        configs = mgr.load_configs()
        # Should load from channels.yaml (has dingtalk-test)
        assert isinstance(configs, list)
        if configs:
            assert any(c.platform == 'dingtalk' for c in configs)

    def test_session_map(self):
        from app.channels.manager import ChannelManager
        mgr = ChannelManager()
        mgr._session_map['dingtalk:user123'] = 'test-agent-1:abc'
        assert mgr._session_map['dingtalk:user123'] == 'test-agent-1:abc'


class TestDingTalkChannel:
    def test_import(self):
        from app.channels.dingtalk import HAS_DINGTALK
        assert HAS_DINGTALK, 'dingtalk-stream SDK not installed'

    def test_class_exists(self):
        from app.channels.dingtalk import DingTalkChannel
        assert DingTalkChannel.platform == 'dingtalk'

    def test_instantiation(self):
        from app.channels.dingtalk import DingTalkChannel
        from app.channels.schema import ChannelConfig

        cfg = ChannelConfig(
            id='test-dt', platform='dingtalk', name='Test DT', enabled=True, worker_id='w1',
            config={'client_id': 'test_client', 'client_secret': 'test_secret'},
        )
        ch = DingTalkChannel(cfg=cfg, on_message=lambda m: None)
        assert ch.channel_id == 'test-dt'
        assert ch.worker_id == 'w1'
        assert ch.client_id == 'test_client'
        assert ch.client_secret == 'test_secret'

    def test_resolve_session_id(self):
        from app.channels.dingtalk import DingTalkChannel
        from app.channels.schema import ChannelConfig

        cfg = ChannelConfig(
            id='ch', platform='dingtalk', name='', enabled=False, worker_id='',
            config={'client_id': 'a', 'client_secret': 'b'},
        )
        ch = DingTalkChannel(cfg=cfg, on_message=lambda m: None)
        assert ch.resolve_session_id('staff001') == 'dingtalk:staff001'

    def test_missing_credentials_raises(self):
        from app.channels.dingtalk import DingTalkChannel
        from app.channels.schema import ChannelConfig

        cfg = ChannelConfig(id='ch', platform='dingtalk', name='', enabled=False, worker_id='', config={})
        with pytest.raises(ValueError, match='client_id'):
            DingTalkChannel(cfg=cfg, on_message=lambda m: None)


class TestFeishuChannel:
    def test_import(self):
        from app.channels.feishu import HAS_FEISHU
        assert HAS_FEISHU, 'lark-oapi SDK not installed'

    def test_class_exists(self):
        from app.channels.feishu import FeishuChannel
        assert FeishuChannel.platform == 'feishu'

    def test_instantiation(self):
        from app.channels.feishu import FeishuChannel
        from app.channels.schema import ChannelConfig

        cfg = ChannelConfig(
            id='test-fs', platform='feishu', name='Test FS', enabled=True, worker_id='w1',
            config={'app_id': 'cli_test', 'app_secret': 'test_secret'},
        )
        ch = FeishuChannel(cfg=cfg, on_message=lambda m: None)
        assert ch.channel_id == 'test-fs'
        assert ch.worker_id == 'w1'
        assert ch.app_id == 'cli_test'
        assert ch.app_secret == 'test_secret'

    def test_resolve_session_id_p2p(self):
        from app.channels.feishu import FeishuChannel
        from app.channels.schema import ChannelConfig

        cfg = ChannelConfig(
            id='ch', platform='feishu', name='', enabled=False, worker_id='',
            config={'app_id': 'a', 'app_secret': 'b'},
        )
        ch = FeishuChannel(cfg=cfg, on_message=lambda m: None)
        assert ch.resolve_session_id('ou_abc123') == 'feishu:ou_abc123'

    def test_resolve_session_id_group(self):
        from app.channels.feishu import FeishuChannel
        from app.channels.schema import ChannelConfig

        cfg = ChannelConfig(
            id='ch', platform='feishu', name='', enabled=False, worker_id='',
            config={'app_id': 'a', 'app_secret': 'b'},
        )
        ch = FeishuChannel(cfg=cfg, on_message=lambda m: None)
        assert ch.resolve_session_id('ou_abc', meta={'feishu_chat_type': 'group', 'feishu_chat_id': 'oc_xyz'}) == 'feishu:group:oc_xyz'

    def test_missing_credentials_raises(self):
        from app.channels.feishu import FeishuChannel
        from app.channels.schema import ChannelConfig

        cfg = ChannelConfig(id='ch', platform='feishu', name='', enabled=False, worker_id='', config={})
        with pytest.raises(ValueError, match='app_id'):
            FeishuChannel(cfg=cfg, on_message=lambda m: None)

    def test_domain_default(self):
        from app.channels.feishu import FeishuChannel
        from app.channels.schema import ChannelConfig

        cfg = ChannelConfig(
            id='ch', platform='feishu', name='', enabled=False, worker_id='',
            config={'app_id': 'a', 'app_secret': 'b'},
        )
        ch = FeishuChannel(cfg=cfg, on_message=lambda m: None)
        assert ch.domain == 'feishu'

    def test_domain_lark(self):
        from app.channels.feishu import FeishuChannel
        from app.channels.schema import ChannelConfig

        cfg = ChannelConfig(
            id='ch', platform='feishu', name='', enabled=False, worker_id='',
            config={'app_id': 'a', 'app_secret': 'b', 'domain': 'lark'},
        )
        ch = FeishuChannel(cfg=cfg, on_message=lambda m: None)
        assert ch.domain == 'lark'

    def test_extract_json_key(self):
        from app.channels.feishu import _extract_json_key
        assert _extract_json_key('{"text": "hello"}', 'text') == 'hello'
        assert _extract_json_key('{"image_key": "abc"}', 'text', 'image_key') == 'abc'
        assert _extract_json_key('{}', 'text') == ''
        assert _extract_json_key('invalid json', 'text') == ''

    def test_extract_post_text(self):
        from app.channels.feishu import _extract_post_text
        content = json.dumps({
            'title': 'Title',
            'content': [[{'tag': 'text', 'text': 'Hello '}, {'tag': 'text', 'text': 'World'}]],
        })
        text = _extract_post_text(content)
        assert 'Title' in text
        assert 'Hello' in text
        assert 'World' in text

    def test_make_chunk_sender(self):
        """Test that _make_chunk_sender returns a callable that stores receive_id."""
        from app.channels.feishu import FeishuChannel
        from app.channels.schema import ChannelConfig

        cfg = ChannelConfig(
            id='ch', platform='feishu', name='', enabled=False, worker_id='',
            config={'app_id': 'a', 'app_secret': 'b'},
        )
        ch = FeishuChannel(cfg=cfg, on_message=lambda m: None)
        ch._receive_id_store['feishu:ou_123'] = ('open_id', 'ou_123')
        sender = ch._make_chunk_sender('feishu:ou_123')
        assert callable(sender)


class TestChannelAPI:
    """Test channel API router structure."""
    def test_router_prefix(self):
        from app.channels_api import router
        assert router.prefix == '/api/channels'

    def test_router_routes(self):
        from app.channels_api import router
        paths = [r.path for r in router.routes]
        # Routes include the prefix
        assert '/api/channels' in paths
        assert '/api/channels/platforms' in paths
        assert '/api/channels/{channel_id}' in paths
