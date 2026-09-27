"""Provider-specific, non-secret frozen request configuration. No silent fallback."""
from urllib.parse import urlsplit
from openai import AsyncOpenAI
from config.settings import Settings

PROMPT_VERSION = 'notes-3'
STRUCTURE_VERSION = 2


def freeze(provider=None):
    from note_ai.generation import POLISH_POLICY, HANDOFF_POLICY
    s = Settings()
    provider = provider or s.notes_default_provider
    if provider not in ('local', 'deepseek'):
        raise ValueError('未知整理服务')
    remote = provider == 'deepseek'
    url = s.deepseek_base_url if remote else s.llm_base_url
    parsed = urlsplit(url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('服务地址不能含凭据或查询参数')
    if remote and url.rstrip('/') != 'https://api.deepseek.com':
        raise ValueError('DeepSeek 仅支持官方 HTTPS 地址')
    return {'provider':provider, 'model':s.deepseek_model if remote else s.model_name,
            'base_url':url.rstrip('/'), 'prompt_version':PROMPT_VERSION, 'structure_version':STRUCTURE_VERSION, 'validation_version':5,
            'prompts':{'polish':POLISH_POLICY,'handoff':HANDOFF_POLICY},
            'temperature':0, 'max_tokens':min(12000, max(s.llm_max_output_tokens,8192)),
            'context_window':65536 if remote else s.llm_context_window,
            'timeout':s.llm_timeout_seconds, 'response_format':{'type':'json_object'},
            'extra_body':{'thinking':{'type':'disabled'}} if remote else {'chat_template_kwargs':{'enable_thinking':False}}}


def credential(config):
    s=Settings()
    key = s.deepseek_api_key.get_secret_value() if config['provider']=='deepseek' else s.llm_api_key.get_secret_value()
    if not key.strip() or not config['model'] or not config['base_url']:
        raise ValueError('整理服务未配置完整；仍可保存记录或按原文导出')
    return key


async def connection(provider):
    config=freeze(provider)
    try:
        key=credential(config)
        async with AsyncOpenAI(base_url=config['base_url'], api_key=key, max_retries=0, timeout=12) as client:
            models=await client.models.list()
        found=config['model'] in [m.id for m in models.data]
        return {'provider':provider,'model':config['model'],'connected':found,'message':'连接正常' if found else '当前模型不在服务列表中'}
    except Exception as exc:
        code=getattr(exc,'status_code',None)
        return {'provider':provider,'model':config['model'],'connected':False,'message':error_message(code)}


def error_message(code):
    return {400:'服务参数不被接受，请检查配置',401:'服务凭据无效或已撤销',402:'服务余额不足，请切回本机或按原文导出',
            422:'服务参数校验失败',429:'服务暂时限流，请稍后重试'}.get(code,'服务连接失败或超时，请重试、切回本机或按原文导出')
