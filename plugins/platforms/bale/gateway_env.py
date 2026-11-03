from gateway.config import Platform
from gateway.platform_env import EnvCred, home_step, reply_mode_step

ENV_ENABLE_CREDENTIALS = ("BALE_BOT_TOKEN",)
ENV_OVERRIDES = (
    EnvCred(Platform.BALE, ("BALE_BOT_TOKEN",), token="BALE_BOT_TOKEN"),
    reply_mode_step(Platform.BALE, "BALE_REPLY_TO_MODE"),
    home_step(Platform.BALE, "BALE_HOME_CHANNEL"),
)
AUTHZ = {
    "allowed_users_env": "BALE_ALLOWED_USERS",
    "allow_all_env": "BALE_ALLOW_ALL_USERS",
    "allowlist_suppresses_pairing": True,
}
