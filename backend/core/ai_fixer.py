"""
AI-assisted build failure fixer.

Fallback tier that runs AFTER the rule-based auto-fixers in
backend.apps.packages.tasks. Sends a trimmed error context from the build
log plus the relevant spec sections to a local (Ollama) or OpenAI-compatible
LLM and asks for a *structured JSON list of fix actions* — never a full spec.

The LLM acts only as a classifier/parameterizer; all spec mutations are
performed deterministically by this module from an allowlisted set of
operations. Every applied fix is stored as a SpecFileRevision so it is
fully auditable and revertible.

Configuration is managed in the UI (Settings page) and stored on the
SystemSettings singleton. Environment variables (settings.REQPM['AI_FIXER'])
serve as fallback defaults when the DB row has not been configured yet.

Backends:
    builtin - llama-cpp-python running a local GGUF model in-process.
              No external services needed; models are downloaded from the
              UI into data/models/. Install runtime with:
              pip install llama-cpp-python
    ollama  - local/remote Ollama server
    openai  - any OpenAI-compatible API
"""

import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


# ─── Model catalog (builtin backend) ────────────────────────────────────────
# Single-file GGUF quantizations suitable for CPU inference on 8-12 GB RAM.

MODEL_CATALOG = {
    'qwen2.5-coder-7b': {
        'label': 'Qwen2.5 Coder 7B (best quality, ~4.7 GB download, ~6 GB RAM)',
        'url': 'https://huggingface.co/bartowski/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf',
        'filename': 'Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf',
        'size_mb': 4683,
    },
    'qwen2.5-coder-3b': {
        'label': 'Qwen2.5 Coder 3B (recommended, ~1.9 GB download, ~3 GB RAM)',
        'url': 'https://huggingface.co/bartowski/Qwen2.5-Coder-3B-Instruct-GGUF/resolve/main/Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf',
        'filename': 'Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf',
        'size_mb': 1929,
    },
    'qwen2.5-coder-1.5b': {
        'label': 'Qwen2.5 Coder 1.5B (fastest, ~1 GB download, ~2 GB RAM)',
        'url': 'https://huggingface.co/bartowski/Qwen2.5-Coder-1.5B-Instruct-GGUF/resolve/main/Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf',
        'filename': 'Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf',
        'size_mb': 986,
    },
}


def models_dir() -> Path:
    d = Path(settings.BASE_DIR) / 'data' / 'models'
    d.mkdir(parents=True, exist_ok=True)
    return d


def model_path(model_key: str) -> Path:
    entry = MODEL_CATALOG.get(model_key)
    if not entry:
        raise ValueError(f'Unknown model key: {model_key}')
    return models_dir() / entry['filename']


def is_model_downloaded(model_key: str) -> bool:
    try:
        p = model_path(model_key)
    except ValueError:
        return False
    # Guard against partial downloads (tmp suffix used during download)
    return p.exists() and not (p.parent / (p.name + '.part')).exists()


def builtin_runtime_available() -> bool:
    """Is llama-cpp-python importable?"""
    try:
        import llama_cpp  # noqa: F401
        return True
    except ImportError:
        return False


# ─── Configuration ──────────────────────────────────────────────────────────

def get_config() -> dict:
    """DB-backed config (Settings UI) with env fallback defaults."""
    env = settings.REQPM.get('AI_FIXER', {})
    try:
        from backend.apps.core.models import SystemSettings
        s = SystemSettings.load()
        return {
            'enabled': s.ai_fixer_enabled,
            'backend': s.ai_fixer_backend,
            'base_url': (s.ai_fixer_base_url or 'http://localhost:11434').rstrip('/'),
            'model': s.ai_fixer_model,
            'api_key': s.ai_fixer_api_key or env.get('API_KEY', ''),
            'timeout': s.ai_fixer_timeout,
            'max_attempts': s.ai_fixer_max_attempts,
            'max_concurrent': s.ai_fixer_max_concurrent,
            'max_log_lines': env.get('MAX_LOG_LINES', 120),
        }
    except Exception:
        # DB not ready (e.g. during migrations) — fall back to env config
        return {
            'enabled': env.get('ENABLED', False),
            'backend': env.get('BACKEND', 'builtin'),
            'base_url': env.get('BASE_URL', 'http://localhost:11434').rstrip('/'),
            'model': env.get('MODEL', 'qwen2.5-coder-3b'),
            'api_key': env.get('API_KEY', ''),
            'timeout': env.get('TIMEOUT', 300),
            'max_attempts': int(env.get('MAX_ATTEMPTS', 3)),
            'max_concurrent': int(env.get('MAX_CONCURRENT', 1)),
            'max_log_lines': env.get('MAX_LOG_LINES', 120),
        }


def is_enabled() -> bool:
    return bool(get_config()['enabled'])


# ─── Action schema ──────────────────────────────────────────────────────────
#
# The model must return:
#   {"error_category": "<short label>",
#    "reasoning": "<one sentence>",
#    "actions": [{"op": "<op>", "value": "<value>"}, ...]}
#
# Allowed ops (everything else is rejected):

ALLOWED_OPS = {
    'add_files_entry',          # add a line to the %files section
    'add_buildrequires',        # add a BuildRequires: line
    'add_requires',             # add a Requires: line
    'set_license',              # replace the License: tag value
    'add_pyproject_save_module',  # append a module name to %pyproject_save_files
    'no_fix',                   # model determined no spec-level fix applies
}

# Values must be a single safe token/path — no shell metacharacters, no newlines.
_SAFE_VALUE_RE = re.compile(r'^[A-Za-z0-9_.+%{}/()\[\]<>=~:, -]+$')

SYSTEM_PROMPT = """You are an RPM packaging expert helping fix failed Python RPM builds.
You will receive an excerpt of a failed mock/rpmbuild log and relevant sections of the RPM spec file.

Respond with ONLY a JSON object (no markdown, no prose) in this exact format:
{"error_category": "<short label>", "reasoning": "<one sentence>", "actions": [{"op": "<op>", "value": "<value>"}]}

Allowed ops:
- add_files_entry: add one line to the %files section. Value is the file/dir path, using RPM macros where possible (e.g. "%{python3_sitelib}/foo/", "%{_bindir}/foo").
- add_buildrequires: add a BuildRequires. Value e.g. "python3-devel" or "python3dist(setuptools) >= 60".
- add_requires: add a runtime Requires. Value like above.
- set_license: replace the License: tag. Value is a valid SPDX expression, e.g. "MIT".
- add_pyproject_save_module: append a top-level module name to the %pyproject_save_files line. Value is the bare module name.
- no_fix: use alone when no spec-level fix can resolve the error.

Common patterns to recognize:
1. "Installed (but unpackaged) file(s) found" -> add_files_entry for the missing paths (prefer the deepest common directory; for namespace packages like foo/bar/ use "%{python3_sitelib}/foo/bar/").
2. "nothing provides python3dist(X)" during dynamic buildrequires -> usually a missing dependency that must be built first; if X is a standard build backend available in RHEL (setuptools, wheel, pip), use add_buildrequires, otherwise no_fix.
3. "No matching package to install" / missing -devel headers -> add_buildrequires for the -devel package.
4. "License field must be" / invalid license -> set_license with the correct SPDX id.
5. "File listed twice" -> no_fix (needs manual spec restructuring).
6. Module import errors during %check -> usually add_buildrequires for the missing python3dist module.

Only propose actions you are confident about. Keep actions minimal."""


# ─── Log/spec context extraction ────────────────────────────────────────────

_ERROR_MARKERS = [
    r'error:',
    r'Error:',
    r'ERROR',
    r'nothing provides',
    r'No matching package',
    r'Installed \(but unpackaged\)',
    r'File listed twice',
    r'Failed build dependencies',
    r'ModuleNotFoundError',
    r'RPM build errors',
]
_ERROR_RE = re.compile('|'.join(_ERROR_MARKERS))

_LOG_PREFIX_RE = re.compile(r'^[\w.-]+\.log\s*-\s*')


def extract_error_context(build_log: str, root_log: str = '', max_lines: int = 120) -> str:
    """
    Pull the most relevant error lines (with a little surrounding context)
    out of potentially huge logs, capped at max_lines.
    """
    selected = []

    for log in (build_log or '', root_log or ''):
        if not log:
            continue
        lines = [_LOG_PREFIX_RE.sub('', l) for l in log.splitlines()]
        # Skip DEBUG noise from root.log
        lines = [l for l in lines if not l.startswith('DEBUG util.py:558') and 'umount' not in l]

        keep = set()
        for i, line in enumerate(lines):
            if _ERROR_RE.search(line):
                for j in range(max(0, i - 2), min(len(lines), i + 12)):
                    keep.add(j)
        selected.extend(lines[i] for i in sorted(keep))

    if not selected:
        # No marker matched — fall back to the tail of the build log
        selected = [_LOG_PREFIX_RE.sub('', l) for l in (build_log or '').splitlines()[-40:]]

    return '\n'.join(selected[:max_lines])


def extract_spec_context(spec_content: str) -> str:
    """Return the header tags, BuildRequires and %files section of a spec."""
    lines = spec_content.splitlines()
    keep = []
    in_files = False
    for line in lines:
        s = line.strip()
        if s.startswith('%files'):
            in_files = True
        elif in_files and s.startswith('%') and not s.startswith(('%{', '%doc', '%license', '%dir', '%attr', '%exclude')):
            in_files = False
        if in_files:
            keep.append(line)
        elif re.match(r'^(Name|Version|Release|License|BuildArch|BuildRequires|Requires|Summary):', s):
            keep.append(line)
        elif s.startswith(('%pyproject_save_files', '%generate_buildrequires', '%pyproject_buildrequires')):
            keep.append(line)
    return '\n'.join(keep[:80])


# ─── LLM backends ───────────────────────────────────────────────────────────

# Lazy-loaded llama.cpp model singleton (per worker process)
_LLAMA = {'model_key': None, 'llm': None}


def _query_builtin(prompt: str, cfg: dict) -> str:
    """Run inference in-process with llama-cpp-python (CPU)."""
    from llama_cpp import Llama

    key = cfg['model']
    path = model_path(key)
    if not path.exists():
        raise RuntimeError(
            f'Model {key} is not downloaded. Download it from the Settings page.')

    if _LLAMA['llm'] is None or _LLAMA['model_key'] != key:
        logger.info(f'AI fixer: loading GGUF model {path.name} (first use in this worker)')
        _LLAMA['llm'] = Llama(
            model_path=str(path),
            n_ctx=8192,
            n_threads=max(1, (os.cpu_count() or 2) - 1),
            verbose=False,
        )
        _LLAMA['model_key'] = key

    out = _LLAMA['llm'].create_chat_completion(
        messages=[
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': prompt},
        ],
        temperature=0.1,
        max_tokens=800,
        response_format={'type': 'json_object'},
    )
    return out['choices'][0]['message']['content']


def _query_llm(prompt: str) -> str:
    """Send prompt to the configured backend, return raw text response."""
    cfg = get_config()

    if cfg['backend'] == 'builtin':
        return _query_builtin(prompt, cfg)

    if cfg['backend'] == 'openai':
        url = f"{cfg['base_url']}/v1/chat/completions"
        headers = {'Content-Type': 'application/json'}
        if cfg['api_key']:
            headers['Authorization'] = f"Bearer {cfg['api_key']}"
        payload = {
            'model': cfg['model'],
            'messages': [
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': prompt},
            ],
            'temperature': 0.1,
            'max_tokens': 800,
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=cfg['timeout'])
        resp.raise_for_status()
        return resp.json()['choices'][0]['message']['content']

    # Default: Ollama
    url = f"{cfg['base_url']}/api/chat"
    payload = {
        'model': cfg['model'],
        'messages': [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': prompt},
        ],
        'stream': False,
        'format': 'json',            # constrain Ollama to valid JSON output
        'options': {'temperature': 0.1, 'num_predict': 800},
    }
    resp = requests.post(url, json=payload, timeout=cfg['timeout'])
    resp.raise_for_status()
    return resp.json()['message']['content']


# ─── Response parsing/validation ────────────────────────────────────────────

def parse_actions(raw: str) -> list:
    """
    Parse and validate the model response.
    Returns a list of {'op': ..., 'value': ...} dicts (may be empty).
    Raises ValueError on malformed/unsafe output.
    """
    # Strip markdown fences if the model added them anyway
    raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip())
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if not m:
        raise ValueError('No JSON object in model response')
    data = json.loads(m.group(0))

    actions = data.get('actions', [])
    if not isinstance(actions, list):
        raise ValueError('"actions" is not a list')

    validated = []
    for a in actions:
        op = a.get('op', '')
        value = str(a.get('value', '') or '').strip()
        if op not in ALLOWED_OPS:
            raise ValueError(f'Disallowed op: {op!r}')
        if op == 'no_fix':
            continue
        if not value or '\n' in value or not _SAFE_VALUE_RE.match(value):
            raise ValueError(f'Unsafe or empty value for {op}: {value!r}')
        validated.append({'op': op, 'value': value})

    logger.info(f"AI fixer: category={data.get('error_category')!r} "
                f"reasoning={data.get('reasoning')!r} actions={validated}")
    return validated


# ─── Spec mutation (deterministic) ──────────────────────────────────────────

def apply_actions(spec_content: str, actions: list) -> tuple:
    """
    Apply validated actions to the spec content.
    Returns (new_content, descriptions). Raises ValueError if an action
    cannot be applied.
    """
    content = spec_content
    descriptions = []

    for a in actions:
        op, value = a['op'], a['value']

        if op == 'add_files_entry':
            if value in content:
                continue
            m = re.search(r'(%files[^\n]*)', content)
            if not m:
                raise ValueError('No %files section found')
            content = content.replace(m.group(1), f'{m.group(1)}\n{value}', 1)
            descriptions.append(f'added "{value}" to %files')

        elif op in ('add_buildrequires', 'add_requires'):
            tag = 'BuildRequires' if op == 'add_buildrequires' else 'Requires'
            if re.search(rf'^{tag}:\s*{re.escape(value)}\s*$', content, re.MULTILINE):
                continue
            anchor = re.search(rf'^({tag}:[^\n]*)', content, re.MULTILINE)
            if anchor:
                content = content.replace(anchor.group(1), f'{anchor.group(1)}\n{tag}: {value}', 1)
            else:
                # Insert after the License: tag
                lic = re.search(r'^(License:[^\n]*)', content, re.MULTILINE)
                if not lic:
                    raise ValueError(f'No anchor for {tag} insertion')
                content = content.replace(lic.group(1), f'{lic.group(1)}\n{tag}: {value}', 1)
            descriptions.append(f'added {tag}: {value}')

        elif op == 'set_license':
            new_content, n = re.subn(r'^License:[^\n]*', f'License: {value}', content, count=1, flags=re.MULTILINE)
            if n == 0:
                raise ValueError('No License: tag found')
            content = new_content
            descriptions.append(f'set License to {value}')

        elif op == 'add_pyproject_save_module':
            m = re.search(r'(%pyproject_save_files[^\n]*)', content)
            if not m:
                raise ValueError('No %pyproject_save_files line found')
            if f' {value}' in m.group(1):
                continue
            content = content.replace(m.group(1), f'{m.group(1)} {value}', 1)
            descriptions.append(f'added module "{value}" to %pyproject_save_files')

    if not descriptions:
        raise ValueError('No actions resulted in changes')
    return content, descriptions


def validate_spec(spec_content: str) -> bool:
    """Best-effort spec syntax validation via rpmspec --parse."""
    try:
        with tempfile.NamedTemporaryFile('w', suffix='.spec', delete=False) as f:
            f.write(spec_content)
            tmp = f.name
        try:
            result = subprocess.run(
                ['rpmspec', '--parse', tmp],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                logger.warning(f"AI fixer: rpmspec validation failed: {result.stderr[:500]}")
                return False
            return True
        finally:
            Path(tmp).unlink(missing_ok=True)
    except FileNotFoundError:
        logger.info('AI fixer: rpmspec not available, skipping syntax validation')
        return True
    except Exception as e:
        logger.warning(f'AI fixer: spec validation error: {e}')
        return True


# ─── Past-fix retrieval (few-shot RAG) ──────────────────────────────────────

_KEYWORD_RE = re.compile(
    r'python3?dist\(([^)]+)\)'          # python3dist(pkg)
    r'|python3?-([a-z0-9_-]+)'          # python3-pkg
    r'|(nothing provides)'
    r'|(unpackaged file)'
    r'|(no such file)'
    r'|(error in building)'
    r'|(cannot find)'
    r'|(no module named)'
    r'|(missing dependency)'
    r'|(failed to build)',
    re.IGNORECASE,
)


def _extract_keywords(text: str) -> set:
    """Pull recognisable tokens from an error string for similarity scoring."""
    keywords = set()
    for m in _KEYWORD_RE.finditer(text):
        token = next((g for g in m.groups() if g), '').strip().lower()
        if token:
            keywords.add(token)
    # Also add plain words longer than 5 chars that look like package names
    for word in re.findall(r'\b[a-z][a-z0-9_-]{4,}\b', text.lower()):
        if '-' in word or '_' in word:
            keywords.add(word)
    return keywords


def get_past_fix_examples(error_ctx: str, max_examples: int = 3) -> list[dict]:
    """
    Retrieve past AI fixes whose error fingerprint overlaps with the current
    error context.  Returns fixes from packages that had a successful build
    (rpm_path set) recorded AFTER the fix revision was created — regardless of
    the package's current build_status.

    Returns a list of dicts: [{"error_excerpt": ..., "actions": [...]}]
    """
    try:
        from django.db.models import F
        from backend.apps.packages.models import SpecFileRevision
        current_kw = _extract_keywords(error_ctx)
        if not current_kw:
            return []

        # Candidate pool: AI-fixed revisions with stored context where a
        # successful build (rpm_path present, last_built_at after the fix)
        # happened after the fix was applied — the fix actually worked.
        candidates = (
            SpecFileRevision.objects
            .filter(
                commit_message__startswith='AI-fixed:',
                fix_context__isnull=False,
                package__rpm_path__isnull=False,
                package__last_built_at__isnull=False,
                package__last_built_at__gt=F('created_at'),
            )
            .select_related('package')
            .only('commit_message', 'fix_context', 'created_at', 'package__name')
        )

        scored = []
        for rev in candidates:
            ctx = rev.fix_context or {}
            past_kw = set(ctx.get('error_keywords', []))
            overlap = len(current_kw & past_kw)
            if overlap > 0:
                scored.append((overlap, rev))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        seen_actions = set()
        for _, rev in scored[:max_examples * 3]:          # over-fetch, dedupe
            ctx = rev.fix_context or {}
            actions_key = tuple(sorted(ctx.get('actions', [])))
            if actions_key in seen_actions:
                continue
            seen_actions.add(actions_key)
            results.append({
                'package': rev.package.name,
                'error_excerpt': ctx.get('error_excerpt', ''),
                'actions': ctx.get('actions', []),
                'descriptions': rev.commit_message[len('AI-fixed:'):].strip(),
            })
            if len(results) >= max_examples:
                break
        return results

    except Exception as e:
        logger.debug(f'AI fixer: past-fix retrieval failed: {e}')
        return []


def _format_examples(examples: list[dict]) -> str:
    if not examples:
        return ''
    lines = ['## Relevant past fixes (few-shot examples from this system)']
    for i, ex in enumerate(examples, 1):
        lines.append(f'\n### Example {i} (package: {ex["package"]})')
        if ex['error_excerpt']:
            lines.append(f'Error contained:\n  {ex["error_excerpt"][:300]}')
        lines.append(f'Actions that fixed it: {ex["descriptions"]}')
    return '\n'.join(lines)


# ─── Concurrency semaphore ───────────────────────────────────────────────────

_SLOT_KEY = 'ai_fixer:active_count'
_SLOT_TTL = 7200   # 2 h safety TTL — prevents a crashed worker leaking a slot
_POLL_INTERVAL = 10  # seconds between slot-availability checks


def _try_acquire_slot(max_concurrent: int) -> bool:
    """
    Atomically increment the active-fixer counter if it is below the limit.
    Returns True when a slot was successfully acquired.
    Django's cache.incr() is atomic against a Redis backend.
    Falls back to True (no limiting) if the cache backend is unavailable.
    """
    from django.core.cache import cache
    try:
        try:
            new_val = cache.incr(_SLOT_KEY)
        except ValueError:
            # Key doesn't exist yet — initialise and claim the first slot
            cache.set(_SLOT_KEY, 1, _SLOT_TTL)
            return True
        if new_val <= max_concurrent:
            # Refresh TTL so it doesn't expire mid-run
            cache.expire(_SLOT_KEY, _SLOT_TTL)
            return True
        # Over the limit — give the slot back
        try:
            cache.decr(_SLOT_KEY)
        except Exception:
            pass
        return False
    except Exception as e:
        # Cache unavailable — allow through without limiting
        logger.warning(f'AI fixer: semaphore cache error ({e}), skipping concurrency limit')
        return True


def _release_slot() -> None:
    from django.core.cache import cache
    try:
        val = cache.decr(_SLOT_KEY)
        if val < 0:
            cache.set(_SLOT_KEY, 0, _SLOT_TTL)
    except Exception:
        pass


def _acquire_slot_blocking(max_concurrent: int, wait_timeout: int) -> bool:
    """
    Block (polling every _POLL_INTERVAL seconds) until a slot is free or
    wait_timeout is exceeded. Returns True if a slot was acquired.
    """
    import time
    if max_concurrent <= 0:
        return False
    deadline = time.monotonic() + wait_timeout
    while time.monotonic() < deadline:
        if _try_acquire_slot(max_concurrent):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        logger.info(
            f'AI fixer: concurrency limit ({max_concurrent}) reached, '
            f'waiting up to {int(remaining)}s for a slot…'
        )
        time.sleep(min(_POLL_INTERVAL, remaining))
    return False


# ─── Public entry point ─────────────────────────────────────────────────────


def attempt_ai_fix(package_id: int, build_log: str, root_log: str = '', ai_attempt: int = 0) -> bool:
    """
    Try to fix a failed build with the LLM. Mirrors the rule-based fixer
    contract: on success creates a new SpecFileRevision and returns True
    (the caller then retries the build). Returns False otherwise.
    """
    from backend.apps.packages.models import Package, SpecFileRevision

    if not is_enabled():
        return False

    try:
        package = Package.objects.get(id=package_id)
        current_spec = SpecFileRevision.objects.filter(
            package=package
        ).order_by('-created_at').first()
        if not current_spec:
            return False

        cfg = get_config()
        # Cap AI fixes per rebuild cycle (ai_attempt is tracked by the caller)
        if ai_attempt >= cfg['max_attempts']:
            logger.info(f'AI fixer: max attempts ({cfg["max_attempts"]}) reached for {package.name} this build, skipping')
            return False

        # Acquire a concurrency slot — block until one is free or timeout
        max_concurrent = cfg['max_concurrent']
        # Use the LLM request timeout as the max wait; a slot should free up
        # within roughly that window.
        wait_timeout = cfg['timeout']
        if not _acquire_slot_blocking(max_concurrent, wait_timeout):
            logger.warning(
                f'AI fixer: could not acquire a slot for {package.name} '
                f'after {wait_timeout}s (limit={max_concurrent}), skipping'
            )
            return False

        try:
            error_ctx = extract_error_context(build_log, root_log, cfg['max_log_lines'])
            spec_ctx = extract_spec_context(current_spec.content)

            # Retrieve similar past fixes to help the model (few-shot RAG)
            examples = get_past_fix_examples(error_ctx)
            examples_section = _format_examples(examples)
            if examples:
                logger.info(f'AI fixer: injecting {len(examples)} past-fix example(s) for {package.name}')

            prompt = (
                f"Package: {package.name} {package.version}\n\n"
                f"## Build error excerpt\n{error_ctx}\n\n"
                f"## Relevant spec sections\n{spec_ctx}\n"
                + (f"\n{examples_section}\n" if examples_section else '')
            )

            logger.info(f'AI fixer: querying {cfg["backend"]}/{cfg["model"]} for {package.name}')
            raw = _query_llm(prompt)
            actions = parse_actions(raw)
            if not actions:
                logger.info(f'AI fixer: model proposed no fix for {package.name}')
                return False

            new_content, descriptions = apply_actions(current_spec.content, actions)

            if not validate_spec(new_content):
                logger.warning(f'AI fixer: proposed spec failed validation for {package.name}')
                return False

            # Build error fingerprint so this fix can be retrieved as a past example
            error_keywords = sorted(_extract_keywords(error_ctx))
            fix_context = {
                'error_excerpt': error_ctx[:400],
                'error_keywords': error_keywords,
                'actions': [a.get('op', '') for a in actions if isinstance(a, dict)],
            }

            SpecFileRevision.objects.create(
                package=package,
                content=new_content,
                commit_message=f'AI-fixed: {"; ".join(descriptions)}',
                fix_context=fix_context,
            )
            logger.info(f'AI fixer: applied fix for {package.name}: {descriptions}')
            return True

        finally:
            _release_slot()

    except requests.exceptions.ConnectionError:
        logger.warning('AI fixer: LLM backend unreachable, skipping')
        return False
    except Exception as e:
        logger.warning(f'AI fixer: failed for package {package_id}: {e}')
        return False
