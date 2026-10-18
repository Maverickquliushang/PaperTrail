import { useEffect, useState, type FormEvent } from 'react';
import { sourceNames, type Source } from './types';

interface Status {
  configured: boolean; app_id: string; enabled: boolean; connection: string; error: string;
  paired: boolean; chat_id: string; push_enabled: boolean; push_sources: Source[];
  deliveries: { id: string; status: string; at: string; title: string }[];
  authorization_url: string; registration_status: string;
}
const deliveryNames: Record<string, string> = { sent: '已确认送达', failed: '发送失败', unknown: '结果不确定，未自动重发', sending: '发送中', preparing: '准备中' };

async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`/api/feishu${path}`, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '请检查输入与本地服务。');
  return data;
}

export function Feishu() {
  const [status, setStatus] = useState<Status | null>(null);
  const [appId, setAppId] = useState('');
  const [secret, setSecret] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [pair, setPair] = useState<{ code: string; until: number } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    let first = true;
    let savedAppId = '';
    const load = async () => {
      try {
        const data = await api<Status>('');
        if (active) { setStatus(data); if (first || savedAppId !== data.app_id) { setAppId(data.app_id); savedAppId = data.app_id; first = false; } }
      } catch (err) { if (active) setError((err as Error).message); }
    };
    void load();
    const timer = setInterval(load, 3000);
    return () => { active = false; clearInterval(timer); };
  }, []);
  async function action(work: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('');
    try { await work(); } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }
  function save(event: FormEvent) {
    event.preventDefault();
    void action(async () => { setStatus(await api<Status>('/credentials', 'PUT', { app_id: appId.trim(), app_secret: secret, enabled: true })); setSecret(''); setNotice('凭据已保存在本机，正在连接飞书。'); });
  }
  return <section className="feishu-page">
    <div className="section-heading"><div><span className="eyebrow">FEISHU / 飞书接入</span><h1>把论文带进群聊</h1><p>群内检索与五个专区的每日推荐，共用你的本地 PaperTrail。</p></div><span className="tag">{status?.connection || '正在读取状态'}</span></div>
    {error && <div className="alert error-alert" role="alert">{error}</div>}
    {notice && <div className="alert" role="status">{notice}</div>}
    {status?.error && <div className="alert">{status.error}</div>}
    {!status?.configured && <section className="feishu-card"><h2>创建或连接应用机器人</h2><p>通过飞书官方页面授权，凭据会自动保存到本机。只申请发送消息和接收群内 @消息所需权限。如果已经创建 PaperTrail，请选择已有应用。</p><button className="search-button" disabled={busy} onClick={() => void action(async () => { setStatus(await api<Status>('/registration', 'POST')); })}>准备飞书授权</button><p role="status">{status?.registration_status}</p>{status?.authorization_url && <p><a href={status.authorization_url} target="_blank" rel="noopener noreferrer">打开飞书官方页面，登录并确认授权 →</a></p>}<p className="muted">如果你的组织不支持快速授权，可按下面的手动步骤配置。</p></section>}
    <div className="feishu-grid">
      <section className="feishu-card"><h2>1. 创建应用机器人</h2><ol>
        <li>打开 <a href="https://open.feishu.cn/app" target="_blank" rel="noopener noreferrer">飞书开发者后台 ↗</a>，登录后创建企业自建应用，名称可用 PaperTrail。</li>
        <li>在应用能力中添加「机器人」。</li>
        <li>权限管理添加：<code>im:message:send_as_bot</code>（以应用身份发送消息）、<code>im:message.group_at_msg:readonly</code>（接收群聊中 @机器人的消息）。</li>
        <li>把「凭证与基础信息」中的 App ID 和 App Secret 填入右侧，保存连接。</li>
        <li>在「事件与回调」中选择长连接，订阅「接收消息」<code>im.message.receive_v1</code>，创建版本并发布。若组织要求审批，等待管理员批准。</li>
        <li>在要接收论文的飞书群中添加这个应用机器人。</li>
      </ol><p className="muted">这里需要应用机器人，群自定义 Webhook 机器人不能完成本页的群聊检索。账号登录和授权由你在飞书页面完成。</p></section>
      <section className="feishu-card"><h2>2. 保存应用凭据</h2><form onSubmit={save} className="feishu-form">
        <label>App ID<input value={appId} onChange={e => setAppId(e.target.value)} required placeholder="cli_…" autoComplete="off" disabled={busy} /></label>
        <label>App Secret<input type="password" value={secret} onChange={e => setSecret(e.target.value)} required={!status?.configured || appId !== status.app_id} placeholder={status?.configured ? '已保存；留空沿用' : '仅在本机保存'} autoComplete="new-password" disabled={busy} /></label>
        <button className="search-button" disabled={busy}>保存并连接</button>
      </form><p className="muted">密钥保存在项目的私人配置中，不显示在状态接口、日志或群消息中。更换应用会清除原群绑定。</p>
      {status?.enabled && <button className="text-button" disabled={busy} onClick={() => void action(async () => { setStatus(await api<Status>('/credentials', 'PUT', { app_id: status.app_id, app_secret: '', enabled: false })); })}>暂停飞书连接与推送</button>}</section>
      <section className="feishu-card"><h2>3. 绑定目标群</h2>{status?.paired ? <><p>已绑定群：<code>{status.chat_id}</code></p><p>仅绑定者在此群 @机器人的指令会被处理。</p><button className="text-button" disabled={busy} onClick={() => void action(async () => { setStatus(await api<Status>('/pairing', 'DELETE')); setPair(null); })}>解绑并停止群推送</button></> : <><p>机器人加群后，生成一次性绑定码，在那个群里 @机器人并发送下方指令。</p><button className="secondary-button" disabled={busy || !status?.enabled} onClick={() => void action(async () => { const value = await api<{ code: string; expires_in: number }>('/pairing', 'POST'); setPair({ code: value.code, until: Date.now() + value.expires_in * 1000 }); })}>生成绑定码</button>{pair && <p className="pair-code"><code>@PaperTrail 绑定 {pair.code}</code><br /><small>{Date.now() < pair.until ? '10 分钟内有效；@请选择群里的机器人。绑定后本页自动更新。' : '绑定码已过期，请重新生成。'}</small></p>}</>}</section>
      <section className="feishu-card"><h2>4. 开启每日推送</h2><p>推送 arXiv、OpenAlex、Hugging Face、顶会索引和 OpenReview 五个专区各自的推荐，每个专区最多 10 篇。</p><p>沿用各专区每天北京时间 09:00 的生成计划，生成完成后依次发送。开启后新产生的定时推荐才会推送，不补发过去的推荐。</p>
        <button className="search-button" disabled={busy || !status?.paired || !status.enabled} onClick={() => void action(async () => { setStatus(await api<Status>('/push', 'PUT', { enabled: !status?.push_enabled, sources: Object.keys(sourceNames) })); setNotice(status?.push_enabled ? '每日推送已关闭。' : '每日推送已开启，下一次新生成的定时推荐会发送到绑定群。'); })}>{status?.push_enabled ? '关闭每日推送' : '开启五个专区的每日推送'}</button><p className="muted">电脑和 PaperTrail 需要保持运行。发送失败或结果不确定会记录在下方，不盲目重发。</p></section>
    </div>
    <section className="feishu-card"><h2>群里怎么用</h2>
      <p>群聊与网页共用检索和推荐数据。以下每条消息都先 @PaperTrail。</p>
      <p><code>检索图神经网络</code> · <code>帮我找计算机视觉的论文</code> · <code>查一下图神经网络</code></p>
      <p>默认搜索全部来源，常见中文研究术语会自动转换为英文关键词，并在回复中展示。也支持中英文混输；不认识的中文会提示你换个说法。</p>
      <p><code>检索 all graph neural network | 最近=30 | 数量=20 | 排序=最新</code></p>
      <p><code>检索 arxiv,openreview computer vision | 会议=ICLR,ICML</code></p>
      <p><code>下一页</code> · <code>排序 最新</code> · <code>详情 1</code> · <code>来源</code> · <code>取消检索</code></p>
      <p><code>推荐 arxiv</code> 查看最新记录；<code>历史 arxiv</code> 查看历史；<code>生成推荐 arxiv</code> 立即生成。</p>
      <p><code>设置 arxiv | 时间=09:00 | 数量=10</code> 保存到同一专区；<code>帮助 设置</code> 查看主题、排除词、回溯等全部设置。</p>
      <p><code>推送 开启</code> / <code>推送 关闭</code> 控制每日投递；<code>状态</code> 查看运行计划。</p>
      <p>每页 10 篇，全部结果可翻页；用回复中的结果 ID 继续查看旧列表。<code>帮助</code> 查看完整菜单。</p>
      <p>需要限定来源时可填写：arxiv、openalex、huggingface、conferences、openreview、all。all 表示综合工作台。账号凭据和群绑定在本页管理。</p>
    </section>
    <section className="feishu-card"><h2>最近投递</h2>{status?.deliveries.length ? status.deliveries.map(d => <div className="feishu-delivery" key={d.id}><strong>{d.title}</strong><span>{deliveryNames[d.status] || d.status} · {new Date(d.at).toLocaleString('zh-CN')}</span></div>) : <p className="muted">暂无群消息投递记录。</p>}</section>
  </section>;
}
