/**
 * ChannelGuideModal — setup guide modal for channel platforms.
 * Shows step-by-step instructions for creating bots on DingTalk, Feishu, etc.
 * Inspired by QwenPaw channel documentation (Apache-2.0).
 */

import { useI18n } from '../i18n';

interface ChannelGuideModalProps {
  platform: string;
  onClose: () => void;
}

const FEISHU_PERMISSIONS_JSON = `{
  "scopes": {
    "tenant": [
      "im:chat",
      "im:message",
      "im:message.group_msg",
      "im:message.p2p_msg:readonly",
      "im:resource",
      "contact:user.base:readonly"
    ],
    "user": []
  }
}`;

function GuideDingTalk({ locale }: { locale: string }) {
  if (locale === 'zh-CN') {
    return (
      <div className="channel-guide-content">
        <h4>📌 钉钉机器人设置指南</h4>
        <ol>
          <li>
            打开 <a href="https://open-dev.dingtalk.com/" target="_blank" rel="noreferrer">钉钉开发者后台</a>
          </li>
          <li>
            进入「应用开发 → 企业内部应用 → 钉钉应用 → 创建应用」
          </li>
          <li>
            在「应用能力 → 添加应用能力」中添加 <strong>「机器人」</strong>
          </li>
          <li>
            配置机器人基础信息，将消息接收模式设为 <strong>Stream 模式</strong>（流式接收），点击发布
          </li>
          <li>
            在「应用发布 → 版本管理与发布」中创建新版本，填写信息后保存
          </li>
          <li>
            在「基础信息 → 凭证与基础信息」中获取：
            <ul>
              <li><strong>Client ID</strong>（即 AppKey）</li>
              <li><strong>Client Secret</strong>（即 AppSecret）</li>
            </ul>
          </li>
          <li>
            ⚠️ <strong>可选</strong>：将服务器 IP 加入白名单 — 在「安全设置 → 服务器出口 IP」中添加公网 IP。
            下载图片/文件时需要此配置，否则会报 <code>IpNotInWhiteList</code> 错误。
            可在终端执行 <code>curl ifconfig.me</code> 查看公网 IP。
          </li>
          <li>
            回到 NoWork 的 Channels 页面，填入 <strong>Client ID</strong> 和 <strong>Client Secret</strong>，选择 Worker，保存并启用
          </li>
        </ol>
        <div className="channel-guide-tip">
          💡 在钉钉「消息」栏搜索框中搜索机器人名称，即可找到并开始对话。
          也可通过「群设置 → 机器人 → 添加机器人」将机器人添加到群聊。
        </div>
      </div>
    );
  }
  return (
    <div className="channel-guide-content">
      <h4>📌 DingTalk Bot Setup Guide</h4>
      <ol>
        <li>
          Open the <a href="https://open-dev.dingtalk.com/" target="_blank" rel="noreferrer">DingTalk Developer Console</a>
        </li>
        <li>
          Go to "App Development → Internal Apps → DingTalk App → Create App"
        </li>
        <li>
          Under "App Capabilities → Add Capability", add <strong>"Robot"</strong>
        </li>
        <li>
          Configure the robot basics, set the message receiving mode to <strong>Stream Mode</strong>, then click Publish
        </li>
        <li>
          Under "App Publishing → Version Management", create a new version, fill in the info, and save
        </li>
        <li>
          Under "Basic Info → Credentials", copy:
          <ul>
            <li><strong>Client ID</strong> (a.k.a. AppKey)</li>
            <li><strong>Client Secret</strong> (a.k.a. AppSecret)</li>
          </ul>
        </li>
        <li>
          ⚠️ <strong>Optional</strong>: Add your server IP to the whitelist — under "Security Settings → Server Egress IP".
          This is required for downloading images/files sent by users; otherwise you'll get an <code>IpNotInWhiteList</code> error.
          Run <code>curl ifconfig.me</code> in terminal to find your public IP.
        </li>
        <li>
          Return to NoWork's Channels page, fill in <strong>Client ID</strong> and <strong>Client Secret</strong>, select a Worker, save and enable
        </li>
      </ol>
      <div className="channel-guide-tip">
        💡 Search for your bot name in the DingTalk "Messages" search bar to start chatting.
        You can also add the bot to a group via "Group Settings → Bots → Add Bot".
      </div>
    </div>
  );
}

function GuideFeishu({ locale }: { locale: string }) {
  if (locale === 'zh-CN') {
    return (
      <div className="channel-guide-content">
        <h4>🐦 飞书机器人设置指南</h4>
        <ol>
          <li>
            打开 <a href="https://open.feishu.cn/app" target="_blank" rel="noreferrer">飞书开放平台</a>，创建企业自建应用
          </li>
          <li>
            在「凭证与基础信息」中获取 <strong>App ID</strong> 和 <strong>App Secret</strong>
          </li>
          <li>
            ⚠️ <strong>重要：操作顺序</strong> — 先在 NoWork 填写 App ID/Secret 并保存，启动 NoWork 服务，
            然后再回到飞书开放平台配置后续步骤。否则长连接验证会失败。
          </li>
          <li>
            回到飞书开放平台，在「能力」中启用 <strong>「机器人」</strong>
          </li>
          <li>
            在「权限管理」中点击「批量导入」，粘贴以下 JSON：
            <pre className="channel-guide-code">{FEISHU_PERMISSIONS_JSON}</pre>
          </li>
          <li>
            在「事件与回调」中，选择订阅方式为 <strong>长连接（WebSocket）</strong> 模式（无需公网 IP）
          </li>
          <li>
            点击「添加事件」，搜索 <strong>「接收消息」</strong>，订阅 <strong>「接收消息 v2.0」</strong>
          </li>
          <li>
            在「应用发布 → 版本管理与发布」中创建版本，填写信息，<strong>保存并发布</strong>
          </li>
        </ol>
        <div className="channel-guide-tip">
          💡 飞书使用 WebSocket 长连接接收消息，无需公网 IP 或 Webhook。
          发送消息走飞书 Open API，支持文本和富文本格式。
        </div>
      </div>
    );
  }
  return (
    <div className="channel-guide-content">
      <h4>🐦 Feishu Bot Setup Guide</h4>
      <ol>
        <li>
          Open the <a href="https://open.feishu.cn/app" target="_blank" rel="noreferrer">Feishu Developer Platform</a> and create an enterprise self-built app
        </li>
        <li>
          Under "Credentials & Basic Info", copy the <strong>App ID</strong> and <strong>App Secret</strong>
        </li>
        <li>
          ⚠️ <strong>Important: Order of Operations</strong> — First fill in the App ID/Secret in NoWork and save,
          start the NoWork service, then return to the Feishu platform to configure the remaining steps.
          Otherwise the long-connection verification will fail.
        </li>
        <li>
          Return to the Feishu platform, under "Capabilities", enable <strong>"Bot"</strong>
        </li>
        <li>
          Under "Permission Management", click "Batch Import" and paste this JSON:
          <pre className="channel-guide-code">{FEISHU_PERMISSIONS_JSON}</pre>
        </li>
        <li>
          Under "Events & Callbacks", select <strong>Long Connection (WebSocket)</strong> mode (no public IP needed)
        </li>
        <li>
          Click "Add Event", search for <strong>"Receive Message"</strong>, and subscribe to <strong>"Receive Message v2.0"</strong>
        </li>
        <li>
          Under "App Publishing → Version Management", create a version, fill in the info, and <strong>publish</strong>
        </li>
      </ol>
      <div className="channel-guide-tip">
        💡 Feishu uses WebSocket long connection to receive messages — no public IP or webhook required.
        Sending messages goes through the Feishu Open API, supporting both text and rich text formats.
      </div>
    </div>
  );
}

function GuideWeCom({ locale }: { locale: string }) {
  if (locale === 'zh-CN') {
    return (
      <div className="channel-guide-content">
        <h4>💼 企业微信 — 即将支持</h4>
        <p>企业微信频道正在开发中，敬请期待。</p>
      </div>
    );
  }
  return (
    <div className="channel-guide-content">
      <h4>💼 WeCom — Coming Soon</h4>
      <p>The WeCom channel is under development. Stay tuned.</p>
    </div>
  );
}

const GUIDE_COMPONENTS: Record<string, React.FC<{ locale: string }>> = {
  dingtalk: GuideDingTalk,
  feishu: GuideFeishu,
  wecom: GuideWeCom,
};

export function ChannelGuideModal({ platform, onClose }: ChannelGuideModalProps) {
  const { t, locale } = useI18n();
  const GuideComponent = GUIDE_COMPONENTS[platform];

  return (
    <div className="help-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <aside className="help-sidebar" style={{ width: 520 }}>
        <div className="help-sidebar-header">
          <div className="help-sidebar-title">
            <span style={{ fontSize: 18 }}>📖</span>
            <h3>{t('channels.setupGuide')}</h3>
          </div>
          <button type="button" className="icon-button help-sidebar-close" onClick={onClose} aria-label="Close">
            <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="5" y1="5" x2="15" y2="15" /><line x1="15" y1="5" x2="5" y2="15" /></svg>
          </button>
        </div>
        <div className="help-sidebar-body">
          {GuideComponent ? <GuideComponent locale={locale} /> : (
            <p style={{ color: '#666' }}>{t('channels.noGuideForPlatform')}</p>
          )}
        </div>
      </aside>
    </div>
  );
}
