"""Repo-wide safety checks: secret scan, no order/execution code, no network
at import time, standard library only. Runs offline. Scans every .py/.md/.json/
.toml/.cfg/.ini/.txt/.sh file in the repo root (parent of tests/)."""
import ast, os, re, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXT_EXT = {".py", ".md", ".json", ".toml", ".cfg", ".ini", ".txt", ".sh", ".yml", ".yaml", ".env"}
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv"}
SELF = {os.path.join("tests", "test_security.py"), "SECURITY.md"}

SECRET_PATTERNS = {
    "aws_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "slack_token": re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}"),
    "github_token": re.compile(r"gh[pousr]_[0-9A-Za-z]{30,}"),
    "openai_style": re.compile(r"sk-[A-Za-z0-9]{24,}"),
    "bearer": re.compile(r"[Bb]earer\s+[A-Za-z0-9._-]{20,}"),
    "assign_secret": re.compile(
        r"""(?i)\b(api[_-]?key|secret|passwd|password|token|private[_-]?key)\b\s*[:=]\s*["'][A-Za-z0-9/+_=.-]{12,}["']"""),
    "url_creds": re.compile(r"https?://[^/\s:@]+:[^/\s:@]+@"),
}
PERSONAL = [re.compile(r"\+?20\s?1\d{9}"), re.compile(r"(?i)\bkhames\b"), re.compile(r"(?i)elasuoty")]

# Order/execution surface: forbidden identifiers and imports.
FORBIDDEN_IMPORTS = {"ccxt", "alpaca_trade_api", "alpaca", "binance", "ib_insync", "robin_stocks",
                     "oandapyv20", "krakenex", "coinbase", "pybit", "web3", "selenium", "playwright",
                     "paramiko", "smtplib", "keyring"}
ORDER_NAME = re.compile(r"(?i)^(place|submit|send|create|cancel|execute|market|limit)_?(order|trade|buy|sell)s?$|"
                        r"^(buy|sell)(_market|_limit|_now)?$|^(create|place)_order$|^execute_trade$")
ORDER_TEXT = re.compile(r"(?i)/(api/v\d/)?(order|orders|trade|withdraw|transfer)\b.*(POST|signature|timestamp)|"
                        r"\bnewOrder\b|\bplace_order\b|\bcreate_order\b|\bsubmit_order\b")


def iter_files():
    for d, dirs, files in os.walk(ROOT):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for f in files:
            p = os.path.join(d, f)
            rel = os.path.relpath(p, ROOT)
            if os.path.splitext(f)[1].lower() in TEXT_EXT or f in {".env", ".env.local"}:
                yield rel, p


def read(p):
    with open(p, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def py_files():
    return [(r, p) for r, p in iter_files() if r.endswith(".py")]


class SecretScan(unittest.TestCase):
    def test_no_secrets(self):
        hits = []
        for rel, p in iter_files():
            if rel in SELF:
                continue
            txt = read(p)
            for name, rx in SECRET_PATTERNS.items():
                if rx.search(txt):
                    hits.append(f"{rel}: {name}")
        self.assertEqual(hits, [], "possible secrets: " + "; ".join(hits))

    def test_no_env_or_key_files(self):
        bad = []
        for d, dirs, files in os.walk(ROOT):
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
            for f in files:
                if f.startswith(".env") or f.endswith((".pem", ".key", ".p12", ".pfx")) or f in {"credentials.json", "secrets.json"}:
                    bad.append(os.path.relpath(os.path.join(d, f), ROOT))
        self.assertEqual(bad, [])

    def test_nothing_personal(self):
        hits = []
        for rel, p in iter_files():
            if rel in SELF:
                continue
            txt = read(p)
            for rx in PERSONAL:
                if rx.search(txt):
                    hits.append(f"{rel}: {rx.pattern}")
        self.assertEqual(hits, [], "personal data about the user must not be in the repo")


class NoExecutionCode(unittest.TestCase):
    def test_no_trading_or_network_client_imports(self):
        hits = []
        for rel, p in py_files():
            try:
                tree = ast.parse(read(p))
            except SyntaxError as e:
                hits.append(f"{rel}: syntax error {e}")
                continue
            for n in ast.walk(tree):
                mods = []
                if isinstance(n, ast.Import):
                    mods = [a.name for a in n.names]
                elif isinstance(n, ast.ImportFrom) and n.module:
                    mods = [n.module]
                for m in mods:
                    if m.split(".")[0] in FORBIDDEN_IMPORTS:
                        hits.append(f"{rel}: imports {m}")
        self.assertEqual(hits, [])

    def test_no_order_functions(self):
        hits = []
        for rel, p in py_files():
            if rel.startswith("tests" + os.sep):
                continue
            tree = ast.parse(read(p))
            for n in ast.walk(tree):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and ORDER_NAME.match(n.name):
                    hits.append(f"{rel}: def {n.name}")
        self.assertEqual(hits, [])

    def test_no_order_endpoints(self):
        hits = []
        for rel, p in py_files():
            if rel.startswith("tests" + os.sep):
                continue
            if ORDER_TEXT.search(read(p)):
                hits.append(rel)
        self.assertEqual(hits, [])

    def test_no_non_get_http(self):
        """Adapters only read. Flag POST/PUT/DELETE/PATCH requests and signing."""
        rx = re.compile(r"""method\s*=\s*["'](POST|PUT|DELETE|PATCH)["']|requests\.(post|put|delete|patch)\(|hmac\.new\(""")
        hits = [rel for rel, p in py_files() if not rel.startswith("tests" + os.sep) and rx.search(read(p))]
        self.assertEqual(hits, [], "write/signed HTTP calls found: review manually")


# Documented exception (SECURITY.md): only the scheduled pipeline job may import these, installed from requirements-pipeline.txt.
PIPELINE_THIRD_PARTY = {'numpy', 'sklearn'}


class StdlibOnly(unittest.TestCase):
    def test_imports_are_stdlib_or_local(self):
        std = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else None
        if std is None:
            self.skipTest("needs Python 3.10+")
        local = {os.path.splitext(f)[0] for f in os.listdir(ROOT)} | \
                {d for d in os.listdir(ROOT) if os.path.isdir(os.path.join(ROOT, d))}
        hits = []
        for rel, p in py_files():
            for n in ast.walk(ast.parse(read(p))):
                mods = []
                if isinstance(n, ast.Import):
                    mods = [a.name for a in n.names]
                elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                    mods = [n.module]
                for m in mods:
                    top = m.split(".")[0]
                    if top not in std and top not in local and not (rel.startswith(('pipeline', 'tests/test_research', 'tests/test_lenses')) and top in PIPELINE_THIRD_PARTY):
                        hits.append(f"{rel}: {m}")
        self.assertEqual(hits, [], "third-party imports")


if __name__ == "__main__":
    unittest.main()
