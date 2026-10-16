import tempfile

import nonebot

_tmp = tempfile.mkdtemp(prefix="wows-test-")
nonebot.init(driver="~fastapi", _env_file=None, command_start={"/"},
             localstore_data_dir=f"{_tmp}/data", localstore_cache_dir=f"{_tmp}/cache",
             localstore_config_dir=f"{_tmp}/config")
plugin = nonebot.load_plugin("nonebot_plugin_wows_asia")
assert plugin is not None, "Plugin failed to load"
