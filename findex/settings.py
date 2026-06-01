"""設定管理: 環境変数 > ~/.findex/config.toml > .env の優先順位で読み込む"""
from dataclasses import dataclass
from pathlib import Path
import os
import tomllib

from dotenv import load_dotenv

CONFIG_PATH = Path.home() / ".findex" / "config.toml"


@dataclass
class Settings:
    edinet_api_key: str = ""
    jquants_api_key: str = ""
    _workers: int = 1  # 並列数（CLIから設定）

    @classmethod
    def load(cls) -> "Settings":
        # .env を読み込む（環境変数が既にある場合は上書きしない）
        load_dotenv(override=False)

        # config.toml を読み込む
        cfg: dict = {}
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "rb") as f:
                cfg = tomllib.load(f).get("api_keys", {})

        return cls(
            edinet_api_key=os.getenv("EDINET_API_KEY", cfg.get("edinet", "")),
            jquants_api_key=os.getenv("JQUANTS_API_KEY", cfg.get("jquants", "")),
        )

    def save(self) -> None:
        """APIキーを ~/.findex/config.toml に保存する（chmod 600）"""
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        content = (
            "[api_keys]\n"
            f'edinet  = "{self.edinet_api_key}"\n'
            f'jquants = "{self.jquants_api_key}"\n'
        )
        CONFIG_PATH.write_text(content)
        CONFIG_PATH.chmod(0o600)
