import yaml
import os
from dataclasses import dataclass
from typing import Optional

@dataclass
class Config:
    # LLM settings
    llm_provider: str = "openai"
    llm_model: str = "gpt-4"
    llm_temperature: float = 0.2
    llm_timeout: int = 120
    llm_max_retries: int = 2
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    ollama_base_url: str = "http://localhost:11434"
    
    # Database
    database_url: str = "sqlite:///data/lyrics_system.db"
    
    # Providers
    genius_token: Optional[str] = None
    musixmatch_api_key: Optional[str] = None
    
    # Framework
    framework_directory: str = "frameworks"
    default_framework: str = "vanilla"
    
    # API
    api_host: str = "0.0.0.0"
    api_port: int = 5001
    api_debug: bool = False
    
    # Logging
    log_level: str = "INFO"
    log_file: Optional[str] = None
    
    @classmethod
    def load(cls, config_path: str = "config.yaml") -> "Config":
        """Load configuration from YAML file"""
        # Adjust path to be relative to project root if called from src/core
        if not os.path.exists(config_path) and not config_path.startswith('/'):
            # Assuming project root is two levels up from src/core
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
            potential_path = os.path.join(project_root, config_path)
            if os.path.exists(potential_path):
                config_path = potential_path
            else:
                # Fallback for when running from project root directly
                pass # Keep original config_path

        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                data = yaml.safe_load(f) or {}
        else:
            print(f"Warning: Config file not found at {config_path}. Using default values.")
            data = {}
        
        # Flatten nested config for simpler access
        config_dict = {}
        
        # LLM settings
        llm = data.get('llm', {})
        config_dict.update({
            'llm_provider': llm.get('provider', cls.llm_provider),
            'llm_model': llm.get('model', cls.llm_model),
            'llm_temperature': llm.get('temperature', cls.llm_temperature),
            'llm_timeout': llm.get('timeout_seconds', cls.llm_timeout),
            'llm_max_retries': llm.get('max_retries', cls.llm_max_retries),
            'openai_api_key': llm.get('openai_api_key', cls.openai_api_key),
            'anthropic_api_key': llm.get('anthropic_api_key', cls.anthropic_api_key),
            'ollama_base_url': llm.get('ollama_base_url', cls.ollama_base_url),
        })
        
        # Other settings
        db_config = data.get('database', {})
        providers_config = data.get('providers', {})
        framework_config = data.get('framework', {})
        api_config = data.get('api', {})
        logging_config = data.get('logging', {})

        config_dict.update({
            'database_url': db_config.get('url', cls.database_url),
            'genius_token': providers_config.get('genius_token', cls.genius_token),
            'musixmatch_api_key': providers_config.get('musixmatch_api_key', cls.musixmatch_api_key),
            'framework_directory': framework_config.get('directory', cls.framework_directory),
            'default_framework': framework_config.get('default', cls.default_framework),
            'api_host': api_config.get('host', cls.api_host),
            'api_port': api_config.get('port', cls.api_port),
            'api_debug': api_config.get('debug', cls.api_debug),
            'log_level': logging_config.get('level', cls.log_level),
            'log_file': logging_config.get('log_file', cls.log_file),
        })
        
        # Override API keys and sensitive tokens from environment variables if set
        # This allows for secure deployment without hardcoding keys in config.yaml
        # and ensures environment variables take precedence.
        env_openai_key = os.environ.get('OPENAI_API_KEY')
        if env_openai_key:
            config_dict['openai_api_key'] = env_openai_key
        
        env_anthropic_key = os.environ.get('ANTHROPIC_API_KEY')
        if env_anthropic_key:
            config_dict['anthropic_api_key'] = env_anthropic_key

        env_genius_token = os.environ.get('GENIUS_TOKEN')
        if env_genius_token:
            config_dict['genius_token'] = env_genius_token

        env_musixmatch_key = os.environ.get('MUSIXMATCH_API_KEY')
        if env_musixmatch_key:
            config_dict['musixmatch_api_key'] = env_musixmatch_key
            
        return cls(**config_dict)
