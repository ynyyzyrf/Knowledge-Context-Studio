import json, os
from pathlib import Path
config = json.loads(os.environ["OPENVIKING_CONF_CONTENT"])
assert config["server"]["auth_mode"] == "api_key"
assert config["server"]["root_api_key"]
p = Path("/tmp/kcs-engine.json")
p.write_text(json.dumps(config))
p.chmod(0o600)
os.execv("/app/.venv/bin/python", ["python", "-I", "-m", "openviking_cli.server_bootstrap", "--config", str(p)])
