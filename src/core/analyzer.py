import os
import json
import logging
from typing import Dict, Any, Optional, List
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_community.llms import Ollama
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic.v1 import SecretStr # Updated for Pydantic v1 compatibility

from src.core.config import Config
from src.core.database import Database

logger = logging.getLogger(__name__)

class LyricsAnalyzer:
    def __init__(self, config: Config, database: Database):
        self.config = config
        self.db = database
        self.llm = self._create_llm()
        self.frameworks = self._load_frameworks()
    
    def _create_llm(self):
        """Create LangChain LLM based on configuration"""
        provider = self.config.llm_provider.lower()
        logger.info(f"Initializing LLM with provider: {provider}, model: {self.config.llm_model}")
        
        try:
            if provider == "openai":
                if not self.config.openai_api_key:
                    raise ValueError("OpenAI API key is not configured.")
                return ChatOpenAI(
                    model=self.config.llm_model,
                    temperature=self.config.llm_temperature,
                    api_key=self.config.openai_api_key,
                    request_timeout=self.config.llm_timeout,
                    max_retries=self.config.llm_max_retries
                )
            elif provider == "anthropic":
                if not self.config.anthropic_api_key:
                    raise ValueError("Anthropic API key is not configured.")
                return ChatAnthropic(
                    model=self.config.llm_model,
                    temperature=self.config.llm_temperature,
                    api_key=SecretStr(self.config.anthropic_api_key),
                    timeout=float(self.config.llm_timeout), # Ensure timeout is float for Anthropic
                    max_retries=self.config.llm_max_retries
                )
            elif provider == "ollama":
                return Ollama(
                    model=self.config.llm_model,
                    base_url=self.config.ollama_base_url,
                    temperature=self.config.llm_temperature,
                    # Ollama timeout can be set via headers if needed, or through specific client options
                    # request_timeout=self.config.llm_timeout # Not a direct param for Ollama constructor
                )
            else:
                raise ValueError(f"Unsupported LLM provider: {provider}")
        except Exception as e:
            logger.error(f"Failed to initialize LLM provider {provider}: {e}", exc_info=True)
            raise ConnectionError(f"Could not initialize LLM provider {provider}: {e}") from e

    def _resolve_framework_dir(self) -> str:
        """Resolves the framework directory path relative to the project root."""
        # Assuming this file (analyzer.py) is in src/core/
        # Project root is two levels up.
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        return os.path.join(project_root, self.config.framework_directory)
    
    def _load_frameworks(self) -> Dict[str, Dict[str, str]]:
        """Load analysis frameworks from text files"""
        frameworks = {}
        # Resolve framework directory relative to project root
        framework_dir = self._resolve_framework_dir()
        
        if not os.path.exists(framework_dir) or not os.path.isdir(framework_dir):
            logger.warning(f"Framework directory not found or is not a directory: {framework_dir}")
            return frameworks
        
        logger.info(f"Loading frameworks from: {framework_dir}")
        for filename in os.listdir(framework_dir):
            if filename.endswith('.txt'):
                framework_name = filename[:-4]  # Remove .txt extension
                filepath = os.path.join(framework_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                        
                    lines = content.split('\n')
                    version = "1.0"  # default version
                    prompt_content = content

                    if lines and lines[0].lower().startswith('# version:'):
                        try:
                            version_str = lines[0].split(':', 1)[1].strip()
                            # Basic validation for version format (e.g., X.Y, X.Y.Z)
                            if re.match(r"^\d+(\.\d+)*$", version_str):
                                version = version_str
                                prompt_content = '\n'.join(lines[1:]).strip() # Remove version line
                            else:
                                logger.warning(f"Invalid version format in {filename}: {lines[0]}. Using default {version}.")
                        except IndexError:
                            logger.warning(f"Malformed version line in {filename}: {lines[0]}. Using default {version}.")
                    
                    if not prompt_content:
                        logger.warning(f"Framework '{framework_name}' from {filename} is empty after processing version. Skipping.")
                        continue

                    frameworks[framework_name] = {
                        'prompt': prompt_content,
                        'version': version
                    }
                    logger.debug(f"Loaded framework: {framework_name} v{version}")
                except Exception as e:
                    logger.error(f"Failed to load framework {filename}: {e}", exc_info=True)
        
        if not frameworks:
            logger.warning(f"No frameworks loaded from {framework_dir}. Analysis may not work as expected.")
        return frameworks
    
    def analyze_lyrics(self, lyrics: str, framework_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Analyze lyrics with specified framework. Returns None on critical failure."""
        if not self.llm:
            logger.error("LLM not initialized. Cannot perform analysis.")
            raise RuntimeError("LLM is not available for analysis.")

        if framework_name is None:
            framework_name = self.config.default_framework
            logger.info(f"No framework specified, using default: {framework_name}")
        
        if not self.frameworks:
            logger.error(f"No analysis frameworks loaded. Cannot analyze with '{framework_name}'.")
            raise ValueError("No analysis frameworks are loaded.")

        if framework_name not in self.frameworks:
            logger.error(f"Framework not found: {framework_name}. Available: {list(self.frameworks.keys())}")
            raise ValueError(f"Framework not found: {framework_name}")
        
        framework = self.frameworks[framework_name]
        framework_version = framework['version']
        
        # Check cache
        cached_result = self.db.get_cached_analysis(lyrics, framework_name, framework_version)
        if cached_result:
            logger.info(f"Found cached analysis result for framework '{framework_name}' v{framework_version}")
            return cached_result
        
        # Run analysis
        logger.info(f"Running analysis with framework: {framework_name} v{framework_version}")
        try:
            # Ensure lyrics placeholder is present in prompt, otherwise append lyrics.
            prompt_template = framework['prompt']
            if '[PASTE LYRICS HERE]' in prompt_template:
                filled_prompt = prompt_template.replace('[PASTE LYRICS HERE]', lyrics)
            else:
                logger.warning(f"Placeholder '[PASTE LYRICS HERE]' not found in framework '{framework_name}'. Appending lyrics to the end of the prompt.")
                filled_prompt = f"{prompt_template}\n\nLyrics to analyze:\n{lyrics}"

            messages = [
                SystemMessage(content="You are an AI assistant specialized in analyzing song lyrics. Provide your analysis in JSON format."),
                HumanMessage(content=filled_prompt)
            ]
            
            response = self.llm.invoke(messages)
            
            if not response or not hasattr(response, 'content') or not response.content:
                logger.error("LLM returned an empty or invalid response.")
                raise ValueError("AI model returned an empty response.")

            # Attempt to parse response content as JSON
            # The response.content might already be a dict if the LLM is configured for JSON output mode
            if isinstance(response.content, dict):
                result = response.content
            elif isinstance(response.content, str):
                # Clean the string: find the first '{' and last '}' to extract JSON part
                try:
                    json_start = response.content.index('{')
                    json_end = response.content.rindex('}') + 1
                    json_str = response.content[json_start:json_end]
                    result = json.loads(json_str)
                except (ValueError, json.JSONDecodeError) as je:
                    logger.error(f"Failed to parse LLM response string as JSON. String was: '{response.content}'. Error: {je}")
                    raise ValueError(f"Invalid JSON response from AI model: {je}")
            else:
                logger.error(f"LLM response content is not a string or dict: {type(response.content)}")
                raise ValueError("AI model returned an unexpected response format.")
            
            # Store in cache
            self.db.store_analysis(lyrics, framework_name, framework_version, result)
            logger.info(f"Successfully analyzed and cached result for framework '{framework_name}' v{framework_version}")
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}. Response content: {getattr(response, 'content', 'N/A')}", exc_info=True)
            # Depending on policy, you might return a specific error structure or None
            # For now, re-raising a clear error for the caller to handle.
            raise ValueError(f"Invalid response format from AI model, not valid JSON: {e}")
        except Exception as e:
            logger.error(f"Analysis error with framework '{framework_name}': {e}", exc_info=True)
            # Re-raise as a runtime error to indicate a failure in the analysis process itself.
            raise RuntimeError(f"Analysis failed for framework '{framework_name}': {str(e)}")
    
    def get_available_frameworks(self) -> List[Dict[str, str]]:
        """Get list of available frameworks with their names and versions."""
        if not self.frameworks:
            logger.info("No frameworks loaded to list.")
            return []
        return [
            {'name': name, 'version': info['version']}
            for name, info in self.frameworks.items()
        ]

# Required for version parsing in _load_frameworks
import re
